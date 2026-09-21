import asyncio
import os
import sys
from pathlib import Path

import config

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-breakpad",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-sync",
    # Extra stability flags for containerized environments
    "--disable-features=TranslateUI,BlinkGenPropertyTrees",
    "--single-process",
]


class BrowserLaunchError(Exception):
    """Chromium persistent context failed to launch or closed immediately."""


def clean_profile_locks(profile_dir: Path):
    """Safely cleans stale Chromium locks when browser previously crashed."""
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "lockfile"):
        lock_path = profile_dir / lock_name
        try:
            if lock_path.is_symlink() or lock_path.exists():
                lock_path.unlink(missing_ok=True)
                print(f"[browser] Cleaned stale profile lock: {lock_path}", flush=True)
        except Exception as e:
            print(f"[browser] Failed to remove {lock_path}: {e}", flush=True)


def _should_use_headless(use_extension: bool) -> bool:
    """
    Determines whether to use headless mode.
    
    Rules:
    - Windows: use config.HEADLESS (default True in local dev)
    - Linux without DISPLAY: always headless=new (extension won't work, fallback to non-extension path)
    - Linux with DISPLAY (Xvfb): use headful if extension is needed, headless otherwise
    
    Note: Chromium extensions CANNOT run in headless=new mode.
    If an extension is required but DISPLAY is missing, we'll run without extension.
    """
    if sys.platform == "win32":
        return config.HEADLESS

    # On Linux/Railway/Docker
    display = os.getenv("DISPLAY", "").strip()
    if display:
        # Xvfb is available
        if use_extension:
            # Extensions need headful mode + Xvfb
            print(f"[browser] DISPLAY={display} found. Running HEADFUL for extension support.", flush=True)
            return False
        else:
            # No extension needed, can use headless
            return True
    else:
        # No display server - must use headless=new
        if use_extension:
            print(
                "[browser] WARNING: DISPLAY not set. Chromium extensions CANNOT run in headless=new mode. "
                "Extension will be DISABLED for this launch. Set up Xvfb if extension is required.",
                flush=True,
            )
        return True


async def launch_account_context(p, account: str, headless: bool = None, use_extension: bool = False):
    """Launches accounts/<account> profile, returns BrowserContext with crash-retry. Caller must close.

    p: async_playwright() instance
    headless: None = auto-detect based on platform and DISPLAY
    use_extension: True = load Dola extension (requires headful + Xvfb on Linux)
    """
    profile_dir = Path(config.ACCOUNTS_DIR) / account
    if not profile_dir.exists():
        raise FileNotFoundError(
            f"Account profile does not exist: {profile_dir} (run python add_account.py {account} first)"
        )

    # Determine headless mode
    if headless is None:
        launch_headless = _should_use_headless(use_extension)
    else:
        launch_headless = headless

    args = list(LAUNCH_ARGS)

    # If headless, add the modern headless flag
    if launch_headless:
        if "--headless=new" not in args:
            args.append("--headless=new")
    
    # Extension setup (only if headful, since extensions don't work in headless)
    effective_extension = use_extension and not launch_headless
    if effective_extension:
        if not config.EXTENSION_ENABLED:
            raise RuntimeError("Dola extension is disabled (DOLA_EXTENSION_ENABLED=0)")
        extension_dir = Path(config.EXTENSION_DIR).resolve()
        if not extension_dir.exists():
            raise FileNotFoundError(f"Dola extension directory does not exist: {extension_dir}")
        args.extend([
            f"--disable-extensions-except={extension_dir}",
            f"--load-extension={extension_dir}",
        ])
        print(f"[browser] Extension loaded: {extension_dir}", flush=True)

    kwargs = {
        "headless": launch_headless,
        "args": args,
        "chromium_sandbox": False,
        "locale": "ja-JP",
        "timezone_id": "Asia/Tokyo",
    }
    if config.PROXY:
        kwargs["proxy"] = {"server": config.PROXY}

    max_attempts = 3
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        clean_profile_locks(profile_dir)

        attempt_kwargs = dict(kwargs)
        attempt_kwargs["args"] = list(args)

        # On retry in Linux, if headful failed, force headless
        if attempt > 1 and sys.platform != "win32" and not launch_headless:
            print(
                f"[browser] Retrying '{account}' (attempt {attempt}) - forcing --headless=new to bypass display crash...",
                flush=True,
            )
            attempt_kwargs["headless"] = True
            headless_args = [a for a in attempt_kwargs["args"] if not a.startswith("--disable-extensions-except") and not a.startswith("--load-extension")]
            if "--headless=new" not in headless_args:
                headless_args.append("--headless=new")
            attempt_kwargs["args"] = headless_args

        print(
            f"[browser] Launching context for '{account}' "
            f"(attempt {attempt}/{max_attempts}): "
            f"headless={attempt_kwargs['headless']}, "
            f"DISPLAY={os.getenv('DISPLAY', 'NOT_SET')}, "
            f"extension={effective_extension and attempt == 1}, "
            f"profile={profile_dir}",
            flush=True,
        )
        try:
            return await p.chromium.launch_persistent_context(str(profile_dir), **attempt_kwargs)
        except Exception as exc:
            last_exc = exc
            print(
                f"[browser] FAILED to launch context for '{account}' "
                f"(attempt {attempt}/{max_attempts}): {type(exc).__name__}: {exc}",
                flush=True,
            )
            clean_profile_locks(profile_dir)
            if attempt < max_attempts:
                wait = 3 * attempt  # progressive backoff: 3s, 6s
                print(f"[browser] Waiting {wait}s before retry...", flush=True)
                await asyncio.sleep(wait)

    raise BrowserLaunchError(
        f"Failed to launch Chromium context for '{account}' after {max_attempts} attempts: {last_exc}"
    ) from last_exc


def cookie_value(cookies: list, name: str) -> str:
    """Extracts cookie value from context.cookies() result."""
    return next((c["value"] for c in cookies if c["name"] == name and c["value"]), "")


async def check_login_state(account: str) -> bool:
    """Opens Dola in headless mode and checks whether session is active."""
    from patchright.async_api import async_playwright
    async with async_playwright() as p:
        context = await launch_account_context(p, account, headless=True, use_extension=False)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.dola.com/chat", timeout=60000, wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)
            cookies = await context.cookies("https://www.dola.com")
            if not cookie_value(cookies, "sessionid"):
                return False
            return bool(await page.evaluate(
                """() => !!(document.querySelector('textarea')
                        || document.querySelector('[contenteditable="true"]')
                        || document.querySelector('input[type="text"]'))"""
            ))
        finally:
            await context.close()
