"""
Chromium Singleton Manager.

Menjaga SATU instance Playwright + Chromium yang hidup terus selama server berjalan.
- MAX_CONCURRENCY = 1: hanya 1 video pada satu waktu
- Akun aktif digunakan sampai habis quota, lalu rotate ke akun berikutnya
- Tidak pernah membuka lebih dari 1 Chromium process sekaligus
"""
import asyncio
import os
import sys
import time
from pathlib import Path

import config

# Singleton state
_playwright = None
_context = None
_active_account: str | None = None
_lock = asyncio.Lock()
_playwright_instance = None


async def _get_playwright():
    global _playwright_instance
    if _playwright_instance is None:
        from patchright.async_api import async_playwright
        _playwright_instance = await async_playwright().start()
        print("[chromium] Playwright started (singleton).", flush=True)
    return _playwright_instance


async def get_context(account: str):
    """
    Returns the existing Chromium context if it's for the same account.
    If a different account is requested, closes the old context and opens a new one.
    Only ONE context exists at any time.
    """
    global _context, _active_account

    async with _lock:
        # Already have the right context open
        if _context is not None and _active_account == account:
            try:
                # Quick liveness check
                _ = _context.pages
                print(f"[chromium] Reusing existing context for '{account}'.", flush=True)
                return _context
            except Exception:
                print(f"[chromium] Context for '{account}' is dead, reopening...", flush=True)
                _context = None
                _active_account = None

        # Close old context if switching accounts
        if _context is not None and _active_account != account:
            print(f"[chromium] Rotating from '{_active_account}' to '{account}'.", flush=True)
            try:
                await _context.close()
            except Exception as e:
                print(f"[chromium] Error closing old context: {e}", flush=True)
            _context = None
            _active_account = None

        # Open new context for the requested account
        print(f"[chromium] Opening Chromium for account '{account}'...", flush=True)
        p = await _get_playwright()

        from browser import launch_account_context
        ctx = await launch_account_context(p, account, headless=None, use_extension=False)
        _context = ctx
        _active_account = account
        print(f"[chromium] Context ready for '{account}'.", flush=True)
        return _context


async def close_current_context():
    """Explicitly close the current Chromium context (e.g., when account is exhausted)."""
    global _context, _active_account
    async with _lock:
        if _context is not None:
            print(f"[chromium] Closing context for '{_active_account}'.", flush=True)
            try:
                await _context.close()
            except Exception as e:
                print(f"[chromium] Error during close: {e}", flush=True)
            _context = None
            _active_account = None


async def shutdown():
    """Gracefully shut down Playwright on server exit."""
    global _playwright_instance, _context, _active_account
    await close_current_context()
    if _playwright_instance is not None:
        try:
            await _playwright_instance.stop()
            print("[chromium] Playwright stopped.", flush=True)
        except Exception:
            pass
        _playwright_instance = None
