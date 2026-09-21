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


async def launch_account_context(p, account: str, headless: bool = None, use_extension: bool = False):
    """Launches accounts/<account> profile, returns BrowserContext with crash-retry. Caller must close.

    p: async_playwright() instance
    headless: None = uses config.HEADLESS
    """
    profile_dir = Path(config.ACCOUNTS_DIR) / account
    if not profile_dir.exists():
        raise FileNotFoundError(
            f"Account profile does not exist: {profile_dir} (run python add_account.py {account} first)"
        )
    launch_headless = config.HEADLESS if headless is None else headless
    args = list(LAUNCH_ARGS)
    if use_extension:
        if not config.EXTENSION_ENABLED:
            raise RuntimeError("Dola extension is disabled (DOLA_EXTENSION_ENABLED=0)")
        extension_dir = Path(config.EXTENSION_DIR).resolve()
        if not extension_dir.exists():
            raise FileNotFoundError(f"Dola extension directory does not exist: {extension_dir}")
        # Chromium debugger extension: On headless Linux server without display, keep headless and use --headless=new
        if sys.platform != "win32" and not os.getenv("DISPLAY"):
            launch_headless = True
            if "--headless=new" not in args:
                args.append("--headless=new")
        else:
            launch_headless = False

        args.extend([
            f"--disable-extensions-except={extension_dir}",
            f"--load-extension={extension_dir}",
        ])
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
        current_headless = launch_headless
        current_args = list(args)
        # Fallback to --headless=new if X11/Xvfb fails or closes immediately on Linux
        if attempt > 1 and sys.platform != "win32" and not current_headless:
            print(f"[browser] Retrying '{account}' in --headless=new mode to bypass display crash...", flush=True)
            current_headless = True
            if "--headless=new" not in current_args:
                current_args.append("--headless=new")

        attempt_kwargs = dict(kwargs)
        attempt_kwargs["headless"] = current_headless
        attempt_kwargs["args"] = current_args
        attempt_kwargs["chromium_sandbox"] = False

        print(f"[browser] Launching context for '{account}' (attempt {attempt}/{max_attempts}): headless={current_headless}, DISPLAY={os.getenv('DISPLAY', 'none')}, profile={profile_dir}", flush=True)
        try:
            return await p.chromium.launch_persistent_context(str(profile_dir), **attempt_kwargs)
        except Exception as exc:
            last_exc = exc
            print(f"[browser] FAILED to launch context for '{account}' (attempt {attempt}): {type(exc).__name__}: {exc}", flush=True)
            clean_profile_locks(profile_dir)
            if attempt < max_attempts:
                print("[browser] Waiting 3 seconds before retry...", flush=True)
                await asyncio.sleep(3)

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
        context = await launch_account_context(p, account)
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
