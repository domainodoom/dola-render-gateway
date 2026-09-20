"""Supabase Integration: Task state syncing and video storage with 24-hour expiration."""
import asyncio
import os
import time
from pathlib import Path
from typing import Optional

import aiohttp
import config


class SupabaseManager:
    def __init__(self):
        self.url = config.SUPABASE_URL.rstrip("/")
        self.key = config.SUPABASE_SERVICE_ROLE_KEY
        self.bucket = config.SUPABASE_STORAGE_BUCKET or "videos"

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    def _headers(self, content_type: str = "application/json") -> dict:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": content_type,
        }

    async def sync_task(self, task_dict: dict) -> bool:
        """Upserts task metadata into Supabase dola_render_tasks table."""
        if not self.is_configured:
            return False
        endpoint = f"{self.url}/rest/v1/dola_render_tasks"
        headers = self._headers()
        headers["Prefer"] = "resolution=merge-duplicates"

        payload = {
            "id": task_dict.get("id"),
            "model": task_dict.get("model"),
            "prompt": task_dict.get("prompt"),
            "ratio": task_dict.get("ratio"),
            "duration": task_dict.get("duration"),
            "status": task_dict.get("status"),
            "account": task_dict.get("account"),
            "conversation_id": task_dict.get("conversation_id"),
            "video_url": task_dict.get("video_url"),
            "error": task_dict.get("error"),
            "updated_at": "now()",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(endpoint, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status in (200, 201, 204):
                        return True
                    text = await resp.text()
                    print(f"[supabase] sync_task HTTP {resp.status}: {text[:200]}", flush=True)
                    return False
        except Exception as e:
            print(f"[supabase] sync_task failed: {e}", flush=True)
            return False

    async def upload_video(self, local_path: str, task_id: str, expires_in: int = 86400) -> Optional[str]:
        """
        Uploads local video to Supabase Storage, generates 24-hour signed URL,
        and deletes local file if successful.
        """
        if not self.is_configured:
            return None
        file_path = Path(local_path)
        if not file_path.exists():
            return None

        object_name = f"{task_id}.mp4"
        upload_endpoint = f"{self.url}/storage/v1/object/{self.bucket}/{object_name}"
        headers = self._headers(content_type="video/mp4")
        headers["x-upsert"] = "true"

        try:
            with open(file_path, "rb") as f:
                data = f.read()

            async with aiohttp.ClientSession() as session:
                # 1. Upload to Supabase Storage
                async with session.post(upload_endpoint, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    if resp.status not in (200, 201):
                        err_text = await resp.text()
                        print(f"[supabase] upload HTTP {resp.status}: {err_text[:200]}", flush=True)
                        return None

                # 2. Generate 24-hour signed URL
                sign_endpoint = f"{self.url}/storage/v1/object/sign/{self.bucket}/{object_name}"
                sign_payload = {"expiresIn": expires_in}
                async with session.post(sign_endpoint, json=sign_payload, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status in (200, 201):
                        res_json = await resp.json()
                        signed_path = res_json.get("signedURL") or res_json.get("signedUrl")
                        if signed_path:
                            final_url = f"{self.url}/storage/v1{signed_path}" if not signed_path.startswith("http") else signed_path
                            print(f"[supabase] Successfully uploaded {object_name} (signed URL valid for {expires_in // 3600}h)", flush=True)

                            # 3. Clean up local file after upload
                            try:
                                file_path.unlink(missing_ok=True)
                                print(f"[supabase] Removed local file: {local_path}", flush=True)
                            except Exception as rm_err:
                                print(f"[supabase] Failed to remove local file: {rm_err}", flush=True)

                            return final_url

                    # Fallback to public URL if bucket is public
                    public_url = f"{self.url}/storage/v1/object/public/{self.bucket}/{object_name}"
                    try:
                        file_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return public_url

        except Exception as e:
            print(f"[supabase] upload_video error: {e}", flush=True)
            return None


supabase_mgr = SupabaseManager()
