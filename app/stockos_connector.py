import ctypes
import hashlib
import json
import os
import secrets
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path


DEFAULT_API_BASE_URL = "https://api-stockos.buublex.com/api/v1"
VIDEO_EXTENSIONS = {".mp4", ".mov"}
_ENTROPY = b"BUUBLE-HairTutorial-StockOS-v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(data):
    if os.name != "nt":
        raise RuntimeError("StockOS credentials require Windows DPAPI")
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    protect = ctypes.windll.crypt32.CryptProtectData
    protect.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    protect.restype = wintypes.BOOL
    ok = protect(
        ctypes.byref(source), "StockOS Hair Tutorial", ctypes.byref(entropy),
        None, None, 0, ctypes.byref(output),
    )
    _ = source_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def _unprotect(data):
    if os.name != "nt":
        raise RuntimeError("StockOS credentials require Windows DPAPI")
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    unprotect = ctypes.windll.crypt32.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    unprotect.restype = wintypes.BOOL
    ok = unprotect(
        ctypes.byref(source), None, ctypes.byref(entropy),
        None, None, 0, ctypes.byref(output),
    )
    _ = source_buffer, entropy_buffer
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def provision_new_service_key(key_path):
    """Create a credential and return only its SHA-256 hash for server provisioning."""
    key_path = Path(key_path)
    raw_key = f"ht_{secrets.token_urlsafe(36)}"
    protected = _protect(raw_key.encode("utf-8"))
    key_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = key_path.with_suffix(key_path.suffix + ".tmp")
    temporary.write_bytes(protected)
    os.replace(temporary, key_path)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class StockOSConnector:
    def __init__(self, base_dir, session=None):
        self.base_dir = Path(base_dir)
        self.config_path = self.base_dir / "stockos_connector.json"
        self.key_path = self.base_dir / ".stockos_connector.key"
        self._lock = threading.Lock()
        self.session = session
        self.config = self.load_config()

    def load_config(self):
        defaults = {
            "enabled": False,
            "api_base_url": DEFAULT_API_BASE_URL,
            "campaign_id": "",
            "campaign_name": "Hair Tutorial Ready",
            "timeout_seconds": 3600,
            "schedule_after_reviewed_upload": True,
        }
        if not self.config_path.exists():
            return defaults
        try:
            loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                defaults.update(loaded)
        except Exception:
            pass
        return defaults

    def save_config(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.config_path)

    def set_enabled(self, enabled):
        self.config["enabled"] = bool(enabled)
        self.save_config()

    def configured(self):
        # Connection readiness is separate from the UI's auto-send preference.
        # Manual review-and-send must keep working while auto-send is disabled.
        return bool(
            self.config.get("campaign_id")
            and self.key_path.exists()
        )

    def _service_key(self):
        if not self.key_path.exists():
            raise RuntimeError("StockOS service key is not installed")
        return _unprotect(self.key_path.read_bytes()).decode("utf-8")

    def _client(self):
        if self.session is not None:
            return self.session
        import requests
        return requests

    def _url(self, route):
        return f"{str(self.config['api_base_url']).rstrip('/')}/{route.lstrip('/')}"

    def _headers(self):
        return {"X-Buuble-Service-Key": self._service_key()}

    @staticmethod
    def _payload(response):
        response.raise_for_status()
        payload = response.json()
        for _ in range(2):
            if isinstance(payload, dict) and "data" in payload and payload.get("error") in (None, {}):
                payload = payload["data"]
        return payload

    def campaigns(self):
        response = self._client().get(
            self._url("external/social-video/campaigns"),
            headers=self._headers(),
            timeout=30,
        )
        return self._payload(response)

    def progress(self, post_id):
        response = self._client().get(
            self._url(f"external/social-video/posts/{post_id}/progress"),
            headers=self._headers(),
            timeout=30,
        )
        return self._payload(response)

    def schedule_recommended(self, post_ids, start_date=None):
        """Place reviewed uploads in the campaign's next free 3-per-week slots."""
        ids = [str(value) for value in post_ids if value]
        if not ids:
            return []
        body = {"postIds": ids}
        if start_date:
            body["startDate"] = str(start_date)
        response = self._client().post(
            self._url(
                f"external/social-video/campaigns/{self.config['campaign_id']}/schedule-recommended"
            ),
            headers={**self._headers(), "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        return self._payload(response)

    def wait_for_processing(self, post_id, video_path, progress_callback=None):
        deadline = time.monotonic() + int(self.config.get("timeout_seconds", 3600))
        terminal = {"REVIEW_REQUIRED", "READY", "FAILED", "REJECTED", "META_MANUAL", "PUBLISHED"}
        last_progress = {}
        consecutive_errors = 0
        while time.monotonic() < deadline:
            try:
                current = self.progress(post_id)
                consecutive_errors = 0
                if isinstance(current, dict):
                    last_progress = current
                    status = str(current.get("status") or "PROCESSING").upper()
                    percent = int(current.get("percent") or 0)
                    stage = str(current.get("stage") or status)
                    self._update_sidecar(video_path, {
                        "upload_status": status.lower(),
                        "processing_percent": percent,
                        "processing_stage": stage,
                        "last_checked_at": datetime.now().isoformat(timespec="seconds"),
                    })
                    if progress_callback:
                        progress_callback(percent, stage, status)
                    if status in terminal:
                        if status in {"FAILED", "REJECTED"}:
                            raise RuntimeError(f"StockOS processing ended with {status}: {stage}")
                        return current
            except RuntimeError:
                raise
            except Exception as exc:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    self._update_sidecar(video_path, {
                        "last_error": f"Progress check failed: {exc}"[:1000],
                    })
                if progress_callback:
                    progress_callback(0, "Waiting for StockOS status", "PROCESSING")
            time.sleep(2)
        self._update_sidecar(video_path, {
            "upload_status": "processing",
            "last_error": "StockOS is still processing; status can be checked again later",
        })
        return last_progress

    def upload_video(self, video_path, progress_callback=None):
        video_path = Path(video_path)
        if video_path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError("StockOS accepts MP4 or MOV files only")
        if self.is_uploaded(video_path):
            data = self._read_sidecar(video_path)
            stockos = data.get("stockos") if isinstance(data, dict) else {}
            post_id = stockos.get("post_id") if isinstance(stockos, dict) else None
            cover = self._cover_path(video_path, data)
            if post_id and cover and not stockos.get("cover_uploaded"):
                self._upload_cover(post_id, cover, video_path)
            return {"skipped": True, "reason": "already uploaded", "id": post_id}
        self._update_sidecar(video_path, {"upload_status": "uploading", "last_error": None})
        try:
            mime = "video/quicktime" if video_path.suffix.lower() == ".mov" else "video/mp4"
            with video_path.open("rb") as stream:
                response = self._client().post(
                    self._url(f"external/social-video/campaigns/{self.config['campaign_id']}/upload"),
                    headers=self._headers(),
                    files={"file": (video_path.name, stream, mime)},
                    data={"alreadyBranded": "true", "preserveSourceAudio": "true"},
                    timeout=(20, int(self.config.get("timeout_seconds", 3600))),
                )
            payload = self._payload(response)
            if not isinstance(payload, dict) or not payload.get("id"):
                raise RuntimeError("StockOS returned no post ID")
            self._update_sidecar(video_path, {
                "post_id": payload["id"],
                "upload_status": "processing",
                "duplicate": bool(payload.get("duplicate")),
                "uploaded_at": datetime.now().isoformat(timespec="seconds"),
                "campaign_id": self.config["campaign_id"],
                "campaign_name": self.config.get("campaign_name"),
                "overlay_mode": "NONE",
                "source_already_branded": True,
                "preserve_source_audio": True,
                "last_error": None,
            })
            cover = self._cover_path(video_path)
            if cover:
                self._upload_cover(payload["id"], cover, video_path)
            self.wait_for_processing(
                payload["id"],
                video_path,
                progress_callback=progress_callback,
            )
            return payload
        except Exception as exc:
            self._update_sidecar(video_path, {
                "upload_status": "failed",
                "last_error": str(exc)[:1000],
                "failed_at": datetime.now().isoformat(timespec="seconds"),
            })
            raise

    def _upload_cover(self, post_id, cover_path, video_path):
        cover_path = Path(cover_path)
        mime = "image/png" if cover_path.suffix.lower() == ".png" else "image/jpeg"
        try:
            with cover_path.open("rb") as stream:
                response = self._client().post(
                    self._url(f"external/social-video/posts/{post_id}/thumbnail"),
                    headers=self._headers(),
                    files={"file": (cover_path.name, stream, mime)},
                    timeout=(20, int(self.config.get("timeout_seconds", 3600))),
                )
            self._payload(response)
            self._update_sidecar(video_path, {
                "cover_uploaded": True,
                "cover_file": str(cover_path),
                "cover_uploaded_at": datetime.now().isoformat(timespec="seconds"),
                "cover_upload_error": None,
            })
        except Exception as exc:
            # The video remains valid even if a platform thumbnail endpoint is
            # temporarily unavailable.  A later Send to StockOS retries it.
            self._update_sidecar(video_path, {
                "cover_uploaded": False,
                "cover_file": str(cover_path),
                "cover_upload_error": str(exc)[:1000],
            })

    def _cover_path(self, video_path, data=None):
        video_path = Path(video_path)
        data = data if isinstance(data, dict) else self._read_sidecar(video_path)
        configured = data.get("cover_file") if isinstance(data, dict) else None
        candidates = [Path(configured)] if configured else []
        candidates.extend([
            video_path.with_name(f"{video_path.stem}_COVER.jpg"),
            video_path.with_name(f"{video_path.stem}_COVER.png"),
        ])
        return next((path for path in candidates if path.is_file()), None)

    def is_uploaded(self, video_path):
        data = self._read_sidecar(Path(video_path))
        stockos = data.get("stockos") if isinstance(data, dict) else None
        return bool(isinstance(stockos, dict) and stockos.get("post_id"))

    def pending_videos(self, folder):
        folder = Path(folder)
        return [
            path for path in sorted(folder.iterdir())
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and not self.is_uploaded(path)
        ] if folder.exists() else []

    @staticmethod
    def _sidecar(video_path):
        return video_path.with_suffix(video_path.suffix + ".json")

    def _read_sidecar(self, video_path):
        sidecar = self._sidecar(video_path)
        if not sidecar.exists():
            return {}
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _update_sidecar(self, video_path, values):
        sidecar = self._sidecar(video_path)
        with self._lock:
            data = self._read_sidecar(video_path)
            current = data.get("stockos") if isinstance(data.get("stockos"), dict) else {}
            data["stockos"] = {**current, **values}
            temporary = sidecar.with_suffix(sidecar.suffix + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, sidecar)
