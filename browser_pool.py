"""Browser Account Pool: Manages accounts/ profiles with rotation, cooldowns, and daily limits."""
import asyncio
import os
import shutil
import sqlite3
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None
from pathlib import Path

from dola_client import CreditError
from browser import BrowserLaunchError
from video_worker_ui import (
    AccountLimitedError, CreditInsufficientError, RiskControlError, generate_video, resume_video,
)
import config

DAILY_LIMIT = int(os.getenv("DOLA_ACCOUNT_DAILY_LIMIT", "2"))
COOLDOWN_SEC = 1800  # 30-minute cooldown on risk control / captcha


class AllAccountsLimitedError(RuntimeError):
    """All active schedulable accounts have reached daily video limit."""


class AllAccountsQuotaBlockedError(RuntimeError):
    """All active schedulable accounts are known to have insufficient credits."""


def get_reset_tz(name: str | None = None):
    tz_name = name or getattr(config, "LIMIT_RESET_TZ", "Asia/Tokyo") or "Asia/Tokyo"
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    offsets = {"Asia/Tokyo": 9, "Asia/Hong_Kong": 8, "UTC": 0}
    return timezone(timedelta(hours=offsets.get(tz_name, 9)))


def next_daily_reset() -> float:
    """Calculates next daily quota reset timestamp at midnight Tokyo (or fallback 24h)."""
    try:
        tz = get_reset_tz()
        now = datetime.now(tz)
        tomorrow = now.date() + timedelta(days=1)
        reset = datetime.combine(tomorrow, dt_time.min, tzinfo=tz)
        return reset.timestamp()
    except Exception as e:
        print(f"[pool] Failed to calculate reset time, using 24h fallback: {e}", flush=True)
        return time.time() + 86400


def calculate_account_status(meta: dict, used_today: int, daily_limit: int) -> tuple[str, float | None, str]:
    """
    Calculates the high-level status of an account:
    Returns (status, cooldown_until, reason)
    Statuses:
    - 'disabled_manual'
    - 'session_expired'
    - 'cooldown_risk'
    - 'cooldown_daily'
    - 'active'
    """
    now = time.time()

    # 1. Disabled manual by admin
    if not meta.get("scheduling", 1):
        return "disabled_manual", None, "Disabled by administrator"

    # 2. Session expired
    login_ok = meta.get("login_ok")
    if login_ok is not None and not login_ok:
        return "session_expired", None, "Session expired, login required"

    # 3. Cooldown risk (captcha / Cloudflare risk control)
    cooldown_until = meta.get("cooldown_until") or 0
    if cooldown_until > now:
        return "cooldown_risk", cooldown_until, meta.get("limit_reason") or "Risk control / captcha active"

    # 4. Cooldown daily (credit exhausted or daily limit reached)
    quota_until = meta.get("quota_blocked_until") or 0
    rate_until = meta.get("rate_limited_until") or 0

    if quota_until > now:
        return "cooldown_daily", quota_until, meta.get("quota_reason") or "daily_credit_exhausted"
    if rate_until > now:
        return "cooldown_daily", rate_until, meta.get("limit_reason") or "daily_limit_reached"
    if used_today >= daily_limit:
        return "cooldown_daily", next_daily_reset(), "daily_limit_reached"
    if meta.get("credit_balance") is not None and meta.get("credit_balance") < 2:
        return "cooldown_daily", next_daily_reset(), "daily_credit_exhausted"

    # 5. Active
    return "active", None, ""


class BrowserPool:
    def __init__(self, accounts_dir: str | None = None, db_path: str | None = None,
                 max_concurrency: int | None = None):
        self.accounts_dir = Path(accounts_dir or config.ACCOUNTS_DIR)
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        db_file = db_path or config.POOL_DB_PATH
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
        concurrency = max_concurrency if max_concurrency is not None else config.MAX_CONCURRENCY
        self.semaphore = asyncio.Semaphore(concurrency)
        self._locks: dict[str, asyncio.Lock] = {}
        self._conn = sqlite3.connect(db_file, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS usage (account TEXT, day TEXT, used INTEGER, "
            "PRIMARY KEY(account, day))"
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts_meta (
                name TEXT PRIMARY KEY,
                scheduling INTEGER DEFAULT 1,
                note TEXT DEFAULT '',
                email TEXT DEFAULT '',
                created_at REAL,
                last_used_at REAL DEFAULT 0,
                login_ok INTEGER,
                login_checked_at REAL DEFAULT 0,
                cooldown_until REAL DEFAULT 0,
                rate_limited_until REAL DEFAULT 0,
                limit_reason TEXT DEFAULT '',
                quota_blocked_until REAL DEFAULT 0,
                quota_reason TEXT DEFAULT '',
                credit_balance INTEGER,
                credit_checked_at REAL DEFAULT 0
            )
            """
        )
        self._conn.commit()
        # Legacy migration: add metadata columns if missing
        for column, definition in (
            ("email", "TEXT DEFAULT ''"),
            ("rate_limited_until", "REAL DEFAULT 0"),
            ("limit_reason", "TEXT DEFAULT ''"),
            ("quota_blocked_until", "REAL DEFAULT 0"),
            ("quota_reason", "TEXT DEFAULT ''"),
            ("credit_balance", "INTEGER"),
            ("credit_checked_at", "REAL DEFAULT 0"),
        ):
            try:
                self._conn.execute(f"ALTER TABLE accounts_meta ADD COLUMN {column} {definition}")
                self._conn.commit()
            except sqlite3.OperationalError:
                pass

    # ===== Account Discovery & Metadata =====

    def _ensure_meta(self, name: str):
        self._conn.execute(
            "INSERT OR IGNORE INTO accounts_meta (name, created_at) VALUES (?, ?)",
            (name, time.time()),
        )
        self._conn.commit()

    @property
    def accounts(self) -> list:
        if not self.accounts_dir.exists():
            return []
        names = sorted(d.name for d in self.accounts_dir.iterdir()
                       if d.is_dir() and not d.name.startswith("."))
        for n in names:
            self._ensure_meta(n)
        return names

    def _meta(self, name: str):
        return self._conn.execute(
            "SELECT * FROM accounts_meta WHERE name=?", (name,)).fetchone()

    def _current_day(self) -> str:
        tz = get_reset_tz()
        return datetime.now(tz).date().isoformat()

    def used_today(self, account: str) -> int:
        row = self._conn.execute(
            "SELECT used FROM usage WHERE account=? AND day=?",
            (account, self._current_day()),
        ).fetchone()
        return row[0] if row else 0

    def _claim(self, account: str):
        self._conn.execute(
            "INSERT INTO usage(account, day, used) VALUES (?,?,1) "
            "ON CONFLICT(account, day) DO UPDATE SET used=used+1",
            (account, self._current_day()),
        )
        self._conn.commit()

    def _next_limit_reset(self) -> float:
        """Calculates next daily quota reset timestamp."""
        return next_daily_reset()

    def _clear_expired_rate_limits(self):
        """Cleans up expired cooldowns and restores accounts to pool."""
        now = time.time()
        cur = self._conn.execute(
            """
            UPDATE accounts_meta 
            SET rate_limited_until=0, limit_reason='', 
                quota_blocked_until=0, quota_reason='',
                credit_balance=NULL
            WHERE (rate_limited_until > 0 AND rate_limited_until <= ?) 
               OR (quota_blocked_until > 0 AND quota_blocked_until <= ?)
            """, (now, now))
        cur_risk = self._conn.execute(
            """
            UPDATE accounts_meta
            SET cooldown_until=0
            WHERE cooldown_until > 0 AND cooldown_until <= ?
            """, (now,))
        if cur.rowcount or cur_risk.rowcount:
            self._conn.commit()

    def _mark_daily_cooldown(self, account: str, reason: str = "daily_credit_exhausted", balance: int = 0):
        """Puts account into daily credit cooldown until next midnight reset."""
        reset_time = next_daily_reset()
        self._conn.execute(
            """
            UPDATE accounts_meta 
            SET quota_blocked_until=?, quota_reason=?, credit_balance=?, last_used_at=? 
            WHERE name=?
            """,
            (reset_time, reason[:300], balance, time.time(), account),
        )
        self._conn.commit()
        print(f"[pool] Account '{account}' entered cooldown_daily until {datetime.fromtimestamp(reset_time).isoformat()} ({reason})", flush=True)

    def _mark_daily_limit(self, account: str, reason: str = "daily_limit_reached"):
        """Marks account as reaching daily limit until next midnight reset."""
        reset_time = next_daily_reset()
        self._conn.execute(
            "INSERT INTO usage(account, day, used) VALUES (?,?,?) "
            "ON CONFLICT(account, day) DO UPDATE SET used=MAX(used, excluded.used)",
            (account, self._current_day(), DAILY_LIMIT),
        )
        self._conn.execute(
            """
            UPDATE accounts_meta 
            SET last_used_at=?, rate_limited_until=?, limit_reason=? 
            WHERE name=?
            """,
            (time.time(), reset_time, reason[:300], account),
        )
        self._conn.commit()
        print(f"[pool] Account '{account}' entered cooldown_daily (limit) until {datetime.fromtimestamp(reset_time).isoformat()} ({reason})", flush=True)

    def _mark_risk_cooldown(self, account: str, reason: str = "risk_control", duration_sec: int = COOLDOWN_SEC):
        """Puts account into risk control cooldown for 30-60 minutes."""
        cooldown_until = time.time() + duration_sec
        self._conn.execute(
            """
            UPDATE accounts_meta 
            SET cooldown_until=?, limit_reason=?, last_used_at=? 
            WHERE name=?
            """,
            (cooldown_until, reason[:300], time.time(), account),
        )
        self._conn.commit()
        print(f"[pool] Account '{account}' entered cooldown_risk for {duration_sec//60}m: {reason}", flush=True)

    def list_accounts(self) -> list:
        """Dashboard view: combines metadata, quota, and busy status."""
        self._clear_expired_rate_limits()
        now = time.time()
        out = []
        for a in self.accounts:
            m = self._meta(a)
            used = self.used_today(a)
            lock = self._locks.get(a)
            m_dict = dict(m) if m else {}
            status, cd_until, reason = calculate_account_status(m_dict, used, DAILY_LIMIT)

            out.append({
                "name": a,
                "status": status,
                "cooldown_until": cd_until or 0,
                "reason": reason,
                "scheduling": bool(m["scheduling"]) if m else True,
                "note": m["note"] if m else "",
                "email": m["email"] if m else "",
                "created_at": m["created_at"] if m else 0,
                "last_used_at": m["last_used_at"] if m else 0,
                "login_ok": m["login_ok"] if m else None,
                "login_checked_at": m["login_checked_at"] if m else 0,
                # Backward compatibility flags:
                "cooling": status == "cooldown_risk",
                "rate_limited": status == "cooldown_daily" and bool(m and m["rate_limited_until"] > now),
                "rate_limited_until": m["rate_limited_until"] if m and m["rate_limited_until"] else 0,
                "limit_reason": m["limit_reason"] if m else "",
                "quota_blocked": status == "cooldown_daily" and bool(m and m["quota_blocked_until"] > now),
                "quota_blocked_until": m["quota_blocked_until"] if m and m["quota_blocked_until"] else 0,
                "daily_credit_cooldown": status == "cooldown_daily",
                "credit_cooldown_until": m["quota_blocked_until"] if m and m["quota_blocked_until"] else 0,
                "quota_reason": m["quota_reason"] if m else "",
                "credit_balance": m["credit_balance"] if m else None,
                "credit_checked_at": m["credit_checked_at"] if m else 0,
                "used_today": used,
                "limit": DAILY_LIMIT,
                "remaining": max(0, DAILY_LIMIT - used),
                "busy": bool(lock and lock.locked()),
            })
        return out

    def set_scheduling(self, name: str, on: bool):
        self._conn.execute(
            "UPDATE accounts_meta SET scheduling=? WHERE name=?", (1 if on else 0, name))
        self._conn.commit()

    def set_email(self, name: str, email: str):
        self._conn.execute(
            "UPDATE accounts_meta SET email=? WHERE name=?", (email, name))
        self._conn.commit()

    def set_login_status(self, name: str, ok: bool):
        self._conn.execute(
            "UPDATE accounts_meta SET login_ok=?, login_checked_at=? WHERE name=?",
            (1 if ok else 0, time.time(), name),
        )
        self._conn.commit()

    def set_note(self, name: str, note: str):
        self._conn.execute(
            "UPDATE accounts_meta SET note=? WHERE name=?", (note, name))
        self._conn.commit()

    def delete_account(self, name: str):
        lock = self._locks.get(name)
        if lock and lock.locked():
            raise RuntimeError("Account is generating video, cannot delete")
        d = self.accounts_dir / name
        if d.exists():
            shutil.rmtree(d)
        self._conn.execute("DELETE FROM accounts_meta WHERE name=?", (name,))
        self._conn.commit()

    async def verify_account(self, name: str) -> bool:
        """Verifies login state in headless mode and updates cache."""
        if name not in self.accounts:
            raise FileNotFoundError(f"Profile does not exist: {name}")
        lock = self._locks.setdefault(name, asyncio.Lock())
        if lock.locked():
            raise RuntimeError("Account is generating video, please verify later")
        from browser import check_login_state
        ok = await check_login_state(name)
        self._conn.execute(
            "UPDATE accounts_meta SET login_ok=?, login_checked_at=? WHERE name=?",
            (1 if ok else 0, time.time(), name),
        )
        self._conn.commit()
        return ok

    # ===== Scheduling =====

    def _set_credit_balance(self, account: str, balance: int, source: str = ""):
        bal = max(0, int(balance))
        self._conn.execute(
            "UPDATE accounts_meta SET credit_balance=?, credit_checked_at=? WHERE name=?",
            (bal, time.time(), account),
        )
        if bal < 2:
            self._mark_daily_cooldown(account, reason=source or "daily_credit_exhausted", balance=bal)
        self._conn.commit()

    def _credit_available(self, account: str, required: int = 2) -> bool:
        row = self._meta(account)
        return not row or row["credit_balance"] is None or row["credit_balance"] >= required

    def _schedulable(self, a: dict) -> bool:
        """Determines if account is ready to generate video right now."""
        status = a.get("status", "active")
        cooldown_until = a.get("cooldown_until") or 0
        now = time.time()

        if status == "cooldown_daily":
            if cooldown_until and now >= cooldown_until:
                return True
            return False

        if status == "cooldown_risk":
            if cooldown_until and now >= cooldown_until:
                return True
            return False

        if status != "active":
            return False

        if a.get("used_today", 0) >= a.get("limit", DAILY_LIMIT):
            return False

        if a.get("credit_balance") is not None and a.get("credit_balance") < 2:
            return False

        return True

    @property
    def all_accounts_limited(self) -> bool:
        """Returns True if all active accounts have reached daily limit or daily cooldown."""
        candidates = [a for a in self.list_accounts() if a["scheduling"] and a["status"] != "disabled_manual"]
        if not candidates:
            return False
        return all(a["status"] == "cooldown_daily" for a in candidates) and any("limit" in a.get("reason", "").lower() for a in candidates)

    @property
    def all_accounts_quota_blocked(self) -> bool:
        """Returns True if all active accounts have exhausted credits."""
        candidates = [a for a in self.list_accounts() if a["scheduling"] and a["status"] != "disabled_manual"]
        if not candidates:
            return False
        return all(a["status"] == "cooldown_daily" for a in candidates)

    @property
    def available(self) -> bool:
        return any(self._schedulable(a) for a in self.list_accounts())

    @property
    def cookie_count(self) -> int:  # /health compatibility
        return len(self.accounts)

    def account_status(self) -> list:
        return [{
            "account": a["name"],
            "status": a["status"],
            "cooldown_until": a["cooldown_until"],
            "reason": a["reason"],
            "used_today": a["used_today"],
            "limit": a["limit"],
            "remaining": a["remaining"],
            "rate_limited": a["rate_limited"],
            "rate_limited_until": a["rate_limited_until"],
            "quota_blocked": a["quota_blocked"],
            "quota_blocked_until": a["quota_blocked_until"],
            "credit_balance": a["credit_balance"],
            "busy": a["busy"],
        } for a in self.list_accounts()]

    async def resume_video(self, account: str, conversation_id: str, timeout: int,
                           on_poll=None) -> dict:
        """Resumes an accepted session without re-scheduling."""
        async with self.semaphore:
            lock = self._locks.setdefault(account, asyncio.Lock())
            async with lock:
                def on_balance(balance, source=""):
                    self._set_credit_balance(account, balance, source)
                try:
                    result = await resume_video(account, conversation_id, timeout,
                                                on_poll=on_poll, on_balance=on_balance)
                    self._claim(account)
                    self._conn.execute(
                        "UPDATE accounts_meta SET last_used_at=? WHERE name=?",
                        (time.time(), account))
                    self._conn.commit()
                    return result
                except TimeoutError:
                    self._claim(account)
                    self._conn.commit()
                    raise

    async def generate_video(self, prompt: str, ratio: str = None, duration: int = None,
                             model: str = "seedance_v2.5", on_conversation_id=None,
                             on_poll=None, on_balance=None,
                             reference_image_paths: list[str] | None = None) -> dict:
        """Picks an idle schedulable account; automatically rotates on quota/risk limits."""
        async with self.semaphore:
            last_err = None
            browser_launch_failures = 0

            for a in self.list_accounts():
                if not self._schedulable(a):
                    continue
                account = a["name"]
                lock = self._locks.setdefault(account, asyncio.Lock())
                if lock.locked():
                    continue
                async with lock:
                    # Re-check after lock acquired
                    curr_meta = next((x for x in self.list_accounts() if x['name'] == account), None)
                    if not curr_meta or not self._schedulable(curr_meta):
                        continue
                    try:
                        def on_balance_cb(balance, source=""):
                            self._set_credit_balance(account, balance, source)

                        try:
                            result = await generate_video(
                                account, prompt, ratio, duration, model=model,
                                on_conversation_id=on_conversation_id, on_poll=on_poll,
                                on_balance=on_balance_cb, reference_image_paths=reference_image_paths)
                        except (CreditInsufficientError, AccountLimitedError, CreditError, RiskControlError, TimeoutError, FileNotFoundError, BrowserLaunchError):
                            raise
                        except Exception as ui_err:
                            print(f"[pool] {account} UI mode error ({ui_err}), falling back to protocol worker...", flush=True)
                            import video_worker
                            result = await video_worker.generate_video(
                                account, prompt, ratio=ratio or "16:9", duration=duration or 10)
                        self._claim(account)
                        self._conn.execute(
                            "UPDATE accounts_meta SET last_used_at=? WHERE name=?",
                            (time.time(), account))
                        self._conn.commit()
                        return result
                    except BrowserLaunchError as e:
                        print(f"[pool] {account} Chromium launch error: {e}. Skipping account without touching credit cooldown.", flush=True)
                        browser_launch_failures += 1
                        last_err = e
                        continue
                    except CreditInsufficientError as e:
                        print(f"[pool] {account} insufficient points, placing in cooldown_daily: {e}", flush=True)
                        self._mark_daily_cooldown(account, reason=str(e), balance=0)
                        last_err = e
                        continue
                    except AccountLimitedError as e:
                        print(f"[pool] {account} reached daily limit, placing in cooldown_daily: {e}", flush=True)
                        self._mark_daily_limit(account, reason=str(e))
                        last_err = e
                        continue
                    except CreditError as e:
                        print(f"[pool] {account} out of quota, placing in cooldown_daily: {e}", flush=True)
                        self._mark_daily_cooldown(account, reason=str(e), balance=0)
                        last_err = e
                        continue
                    except RiskControlError as e:
                        print(f"[pool] {account} risk control triggered, placing in cooldown_risk (30m): {e}", flush=True)
                        self._mark_risk_cooldown(account, reason=str(e), duration_sec=COOLDOWN_SEC)
                        last_err = e
                        continue
                    except TimeoutError as e:
                        # Once conversation_id is assigned, task continues on Dola side;
                        # do not re-submit to prevent duplicate credit consumption.
                        self._claim(account)
                        self._conn.execute(
                            "UPDATE accounts_meta SET last_used_at=? WHERE name=?",
                            (time.time(), account))
                        self._conn.commit()
                        raise
                    except FileNotFoundError as e:
                        print(f"[pool] {account} profile missing, skipping: {e}", flush=True)
                        last_err = e
                        continue

            if self.all_accounts_quota_blocked:
                raise AllAccountsQuotaBlockedError(
                    f"429: All schedulable accounts have insufficient points: {last_err or 'No accounts'}"
                )
            if self.all_accounts_limited:
                raise AllAccountsLimitedError(
                    f"429: All schedulable accounts have reached Dola daily limit: {last_err or 'No accounts'}"
                )
            if browser_launch_failures > 0 and not self.available:
                raise RuntimeError(
                    f"Browser failed to launch on {browser_launch_failures} accounts. Check Xvfb and Chromium dependencies: {last_err}"
                )
            raise RuntimeError(f"No available accounts in pool: {last_err or 'No accounts'}")
