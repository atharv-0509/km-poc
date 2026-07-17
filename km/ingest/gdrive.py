"""Google Drive source connector (service-account, read-only).

Unlike the format connectors, this is a *source* connector: it pulls files
out of a Drive folder and hands each one to the existing format connectors via
`ingest_path`, so xlsx/pdf/pptx/docx/csv/images all work unchanged. It never
writes to Drive and requests only the read-only scope.

Auth model (plain Gmail / folder-sharing):
  1. Create a Google Cloud service account and download its JSON key.
  2. Enable the Drive API on that project.
  3. Share the office Drive folder with the service account's email
     (…@<project>.iam.gserviceaccount.com) as *Viewer*.
  4. Point KM_GDRIVE_CREDENTIALS (or GOOGLE_APPLICATION_CREDENTIALS) at the
     JSON key and pass the folder id.

Google-native files are exported to Office formats on the way out (Sheets→xlsx,
Docs→docx, Slides→pptx) so they flow through the same connectors. See
docs/GDRIVE_SETUP.md for the full walkthrough.

Requires `google-api-python-client` and `google-auth` (optional). Absent → the
connector raises a clear, actionable error (a Drive pull the user explicitly
asked for should fail loudly, not skip silently).
"""

from __future__ import annotations

import io
import os
import tempfile
from collections.abc import Iterator

from ..schema import Record
from . import ingest_path

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Google-native mime type -> (export mime, file extension).
_EXPORT = {
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
_FOLDER_MIME = "application/vnd.google-apps.folder"


def _resolve_credentials(creds_path: str | None) -> str:
    path = (
        creds_path
        or os.environ.get("KM_GDRIVE_CREDENTIALS")
        or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )
    if not path or not os.path.exists(path):
        raise FileNotFoundError(
            "Service-account JSON key not found. Set KM_GDRIVE_CREDENTIALS to "
            "the key file path (see docs/GDRIVE_SETUP.md)."
        )
    return path


def _build_service(creds_path: str):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except Exception as exc:  # pragma: no cover - depends on optional libs
        raise ImportError(
            "Google Drive connector needs google-api-python-client and "
            "google-auth. Install with: pip install km-poc[gdrive]"
        ) from exc

    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_folder(service, folder_id: str, recursive: bool = True) -> list[dict]:
    """Return file metadata dicts under `folder_id` (recursing by default)."""
    files: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageSize=100,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f["mimeType"] == _FOLDER_MIME:
                if recursive:
                    files.extend(list_folder(service, f["id"], recursive))
            else:
                files.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def _download(service, meta: dict, dest_dir: str) -> str | None:
    """Download or export one Drive file to dest_dir; return the local path."""
    from googleapiclient.http import MediaIoBaseDownload

    mime = meta["mimeType"]
    name = meta["name"]
    if mime in _EXPORT:
        export_mime, ext = _EXPORT[mime]
        request = service.files().export_media(fileId=meta["id"], mimeType=export_mime)
        if not name.lower().endswith(ext):
            name += ext
    elif mime.startswith("application/vnd.google-apps"):
        return None  # forms, drawings, etc. — nothing we can ingest
    else:
        request = service.files().get_media(fileId=meta["id"], supportsAllDrives=True)

    safe = name.replace("/", "_")
    path = os.path.join(dest_dir, f"{meta['id']}__{safe}")
    buf = io.FileIO(path, "wb")
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    buf.close()
    return path


def ingest_gdrive(
    folder_id: str,
    creds_path: str | None = None,
    recursive: bool = True,
    dest_dir: str | None = None,
) -> Iterator[Record]:
    """Pull every ingestible file under a Drive folder and yield raw Records.

    Records carry the Drive file name as source_file and note the Drive id in
    `extra`, so provenance points back to the origin file.
    """
    creds_path = _resolve_credentials(creds_path)
    service = _build_service(creds_path)

    tmp = dest_dir or tempfile.mkdtemp(prefix="km_gdrive_")
    os.makedirs(tmp, exist_ok=True)

    for meta in list_folder(service, folder_id, recursive=recursive):
        local = _download(service, meta, tmp)
        if not local:
            continue
        for rec in ingest_path(local):
            # Restore the real Drive file name and record the origin id.
            rec.source_file = meta["name"]
            rec.extra = {**rec.extra, "gdrive_id": meta["id"],
                         "gdrive_modified": meta.get("modifiedTime")}
            rec.id = rec.compute_id()
            yield rec
