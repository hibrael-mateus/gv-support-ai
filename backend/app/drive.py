"""Google Drive integration restricted to the authorized folder (and its subfolders).

OAuth: the analyst picks the OAuth client JSON (Desktop app) in the setup wizard; the resulting
token is stored in Windows Credential Manager, never in files, Git or the executable.
Scope is drive.readonly: the app can never modify the Drive.
"""
from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterator
from typing import Any

from . import rag
from .db import connection, set_meta
from .extract import extract_pages
from .jobs import JobContext
from .security import ACCEPTED_SOURCE, classify_source
from .settings import ALLOWED_GOOGLE_DRIVE_FOLDER_ID, get_secret, load_config, set_secret

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_SECRET = "google_oauth_token"
SERVICE_ACCOUNT_SECRET = "google_service_account"  # website servers: key JSON of an account the folder is shared with
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}
MAX_BYTES = 50 * 1024 * 1024
FIELDS = "id,name,mimeType,modifiedTime,parents,md5Checksum,size,webViewLink,version"


class DriveNotConfigured(RuntimeError):
    pass


def authorize(client_secret_path: str) -> dict[str, Any]:
    """Interactive OAuth in the system browser (loopback redirect)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  success_message="GV Support AI conectado ao Google Drive. Pode fechar esta janela.")
    set_secret(TOKEN_SECRET, creds.to_json())
    return status()


def disconnect() -> None:
    set_secret(TOKEN_SECRET, "")


def _credentials():
    if sa := get_secret(SERVICE_ACCOUNT_SECRET):
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_info(json.loads(sa), scopes=SCOPES)
    raw = get_secret(TOKEN_SECRET)
    if not raw:
        raise DriveNotConfigured("Google Drive não conectado. Use Configurações > Google Drive.")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_info(json.loads(raw), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        set_secret(TOKEN_SECRET, creds.to_json())
    return creds


class GoogleDriveGateway:
    def __init__(self, service=None, allowed_folder_id: str = ALLOWED_GOOGLE_DRIVE_FOLDER_ID):
        self._service = service
        self.allowed_folder_id = allowed_folder_id
        self._parents: dict[str, list[str]] = {}

    @property
    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build

            self._service = build("drive", "v3", credentials=_credentials(), cache_discovery=False)
        return self._service

    def parents(self, file_id: str) -> list[str]:
        if file_id not in self._parents:
            data = self.service.files().get(fileId=file_id, fields="id,parents", supportsAllDrives=True).execute()
            self._parents[file_id] = list(data.get("parents", []))
        return self._parents[file_id]

    def folder_info(self) -> dict[str, Any]:
        return self.service.files().get(fileId=self.allowed_folder_id, fields="id,name,webViewLink",
                                        supportsAllDrives=True).execute()

    def _children(self, folder_id: str) -> Iterator[dict[str, Any]]:
        token = None
        while True:
            resp = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false", fields=f"nextPageToken,files({FIELDS})",
                pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
            ).execute()
            for item in resp.get("files", []):
                self._parents[item["id"]] = list(item.get("parents", []))
                yield item
            token = resp.get("nextPageToken")
            if not token:
                return

    def walk(self) -> Iterator[tuple[dict[str, Any], str]]:
        """All files below the authorized folder, with their relative path."""
        stack = [(self.allowed_folder_id, "")]
        seen = {self.allowed_folder_id}
        while stack:
            folder_id, path = stack.pop()
            for item in self._children(folder_id):
                if item["mimeType"] == FOLDER_MIME:
                    if item["id"] not in seen:
                        seen.add(item["id"])
                        stack.append((item["id"], f"{path}/{item['name']}"))
                else:
                    yield item, path

    def download(self, item: dict[str, Any]) -> tuple[bytes, str]:
        from googleapiclient.http import MediaIoBaseDownload

        mime = item["mimeType"]
        if mime in EXPORTS:
            export_mime, ext = EXPORTS[mime]
            data = self.service.files().export(fileId=item["id"], mimeType=export_mime).execute()
            return data, item["name"] + ext
        if int(item.get("size") or 0) > MAX_BYTES:
            raise ValueError("Arquivo maior que 50 MB")
        buf = io.BytesIO()
        req = self.service.files().get_media(fileId=item["id"], supportsAllDrives=True)
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue(), item["name"]


def status() -> dict[str, Any]:
    connected = bool(get_secret(TOKEN_SECRET) or get_secret(SERVICE_ACCOUNT_SECRET))
    return {"connected": connected, "allowed_folder_id": ALLOWED_GOOGLE_DRIVE_FOLDER_ID,
            "client_secret_configured": bool(load_config().get("google_client_secret_path"))}


def sync(ctx: JobContext | None = None, *, gateway: GoogleDriveGateway | None = None, full: bool = False,
         embedder: Callable[[list[str]], list[list[float]] | None] | None = None) -> dict[str, Any]:
    """Incremental sync: only new/changed files are (re)indexed; removed files leave the index."""
    gateway = gateway or GoogleDriveGateway()
    cfg = load_config()
    with connection() as conn:
        known = {r["drive_file_id"]: (r["modified_time"], r["hash"]) for r in
                 conn.execute("SELECT drive_file_id, modified_time, hash FROM sources")}
    if full:
        rag.clear_index()
        known = {}

    items = list(gateway.walk())
    total = len(items)
    seen: set[str] = set()
    counts = {"new": 0, "updated": 0, "unchanged": 0, "removed": 0, "rejected": 0, "errors": 0, "total": total}
    for n, (item, path) in enumerate(items, start=1):
        fid, name = item["id"], item["name"]
        if ctx:
            ctx.progress(n, total, name)
        if item["mimeType"] == SHORTCUT_MIME:
            counts["rejected"] += 1  # shortcuts may point outside the authorized folder: never followed
            continue
        if item["mimeType"].startswith(("image/", "video/", "audio/")):
            continue
        if classify_source(fid, gateway.parents, gateway.allowed_folder_id) != ACCEPTED_SOURCE:
            counts["rejected"] += 1
            if ctx:
                ctx.log(f"REJECTED_SOURCE {name}")
            continue
        seen.add(fid)
        signature = (item.get("modifiedTime", ""), item.get("md5Checksum") or item.get("version", ""))
        if fid in known and known[fid] == signature:
            counts["unchanged"] += 1
            continue
        try:
            data, fname = gateway.download(item)
            pages = extract_pages(fname, data, item["mimeType"])
            rag.index_document(
                drive_file_id=fid, name=name, pages=pages, parents_lookup=gateway.parents,
                mime_type=item["mimeType"], path=path, folder_id=(item.get("parents") or [""])[0],
                modified_time=signature[0], file_hash=signature[1], web_url=item.get("webViewLink", ""),
                embedder=embedder, chunk_size=int(cfg.get("chunk_size", 1200)),
                allowed_folder_id=gateway.allowed_folder_id,
            )
            counts["updated" if fid in known else "new"] += 1
        except Exception as exc:
            counts["errors"] += 1
            rag.record_error(fid, name, str(exc))
            if ctx:
                ctx.log(f"ERRO {name}: {exc}")
    for fid in set(known) - seen:
        rag.remove_document(fid)
        counts["removed"] += 1
    from datetime import datetime, timezone

    set_meta("last_sync", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return counts
