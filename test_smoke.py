"""Comprehensive Smoke Test for dola-render-gateway."""
import asyncio
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

# Mock patchright and aiohttp if not installed in local environment
for mod in ("patchright", "patchright.async_api", "aiohttp"):
    try:
        __import__(mod)
    except ImportError:
        sys.modules[mod] = MagicMock()

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from browser import BrowserLaunchError
from browser_pool import (
    DAILY_LIMIT,
    BrowserPool,
    calculate_account_status,
    next_daily_reset,
)
from store import TaskStore
from supabase_client import supabase_mgr


def test_config():
    print("Testing config defaults...", flush=True)
    assert config.MAX_CONCURRENCY == 1, f"Expected concurrency 1, got {config.MAX_CONCURRENCY}"
    assert config.HEADLESS is False, f"Expected HEADLESS False, got {config.HEADLESS}"
    assert config.EXTENSION_ENABLED is True, "Expected EXTENSION_ENABLED True"
    assert config.LIMIT_RESET_TZ == "Asia/Tokyo", f"Expected Asia/Tokyo, got {config.LIMIT_RESET_TZ}"
    print("[OK] config defaults verified", flush=True)


def test_next_daily_reset():
    print("Testing Tokyo midnight reset calculation...", flush=True)
    reset_ts = next_daily_reset()
    now = time.time()
    diff_hours = (reset_ts - now) / 3600
    assert 0 < diff_hours <= 25, f"Reset time should be within 24h, got {diff_hours}h"
    print(f"[OK] next_daily_reset() returned {reset_ts} ({diff_hours:.2f} hours from now)", flush=True)


def test_account_lifecycle_statuses():
    print("Testing 5-status lifecycle...", flush=True)
    now = time.time()
    cases = [
        # active
        ({"scheduling": 1, "login_ok": 1, "credit_balance": 30}, 0, "active"),
        # cooldown_daily (quota blocked)
        ({"scheduling": 1, "login_ok": 1, "quota_blocked_until": now + 3600}, 0, "cooldown_daily"),
        # cooldown_daily (daily limit)
        ({"scheduling": 1, "login_ok": 1, "rate_limited_until": now + 3600}, 0, "cooldown_daily"),
        # cooldown_daily (credit balance < 2)
        ({"scheduling": 1, "login_ok": 1, "credit_balance": 1}, 0, "cooldown_daily"),
        # cooldown_daily (used_today >= limit)
        ({"scheduling": 1, "login_ok": 1, "credit_balance": 30}, DAILY_LIMIT, "cooldown_daily"),
        # cooldown_risk (captcha)
        ({"scheduling": 1, "login_ok": 1, "cooldown_until": now + 600}, 0, "cooldown_risk"),
        # session_expired (login failed)
        ({"scheduling": 1, "login_ok": 0}, 0, "session_expired"),
        # disabled_manual (admin toggle)
        ({"scheduling": 0, "login_ok": 1}, 0, "disabled_manual"),
    ]
    for meta, used, expected in cases:
        st, cd, re = calculate_account_status(meta, used, DAILY_LIMIT)
        assert st == expected, f"Expected {expected}, got {st} (meta={meta}, used={used})"
    print("[OK] All 5 account statuses verified successfully", flush=True)


def test_task_store():
    print("Testing TaskStore operations...", flush=True)
    db_test = "scratch_test_tasks.db"
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = db_test + suffix
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass
    try:
        store = TaskStore(db_test)
        task_id = "test_task_123"
        store.create(task_id, "seedance_v2.5", "test prompt", "16:9", 10, None, {})
        t = store.get(task_id)
        assert t["status"] == "queued", f"Expected queued, got {t['status']}"

        store.update(task_id, status="processing", conversation_id="conv_abc", account="test_acc")
        t = store.get(task_id)
        assert t["status"] == "processing"
        assert t["conversation_id"] == "conv_abc"
        assert t["account"] == "test_acc"

        store.update(task_id, status="completed", video_url="https://example.com/video.mp4")
        t = store.get(task_id)
        assert t["status"] == "completed"
        assert t["video_url"] == "https://example.com/video.mp4"
        print("[OK] TaskStore operations passed", flush=True)
    finally:
        for suffix in ("", "-journal", "-wal", "-shm"):
            p = db_test + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


def test_supabase_manager():
    print("Testing Supabase manager graceful fallback...", flush=True)
    assert isinstance(supabase_mgr.is_configured, bool)
    print("[OK] Supabase manager initialized safely", flush=True)


if __name__ == "__main__":
    test_config()
    test_next_daily_reset()
    test_account_lifecycle_statuses()
    test_task_store()
    test_supabase_manager()
    print("\nALL SMOKE TESTS PASSED! Ready for production deployment.", flush=True)
