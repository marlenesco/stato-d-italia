from __future__ import annotations

import shutil
import json
from pathlib import Path
from urllib.parse import urlparse

import requests

from .common import json_dump, now_iso, sha256_file


def download(url: str, destination: Path, source_id: str) -> dict:
    """Download once, keep source HTTP facts alongside immutable raw bytes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    metadata_path = destination.with_suffix(destination.suffix + ".metadata.json")
    prior = json.loads(metadata_path.read_text()) if destination.exists() and metadata_path.exists() else None
    headers = {"User-Agent": "stato-italia-data/0.1"}
    if prior and prior.get("etag"):
        headers["If-None-Match"] = prior["etag"]
    if prior and prior.get("last_modified"):
        headers["If-Modified-Since"] = prior["last_modified"]
    with requests.get(url, stream=True, timeout=(15, 180), headers=headers) as response:
        if response.status_code == 304 and prior:
            prior["checked_at"] = now_iso()
            prior["unchanged"] = True
            json_dump(metadata_path, prior)
            return prior
        response.raise_for_status()
        with temporary.open("wb") as target:
            shutil.copyfileobj(response.raw, target)
        headers = {key.lower(): value for key, value in response.headers.items()}
    temporary.replace(destination)
    checksum = sha256_file(destination)
    metadata = {
        "source_id": source_id,
        "acquired_at": now_iso(),
        "resolved_url": str(response.url),
        "requested_url": url,
        "filename": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": checksum,
        "content_type": headers.get("content-type"),
        "etag": headers.get("etag"),
        "last_modified": headers.get("last-modified"),
        "unchanged": bool(prior and prior.get("sha256") == checksum),
    }
    json_dump(metadata_path, metadata)
    return metadata


def raw_path(root: Path, source_id: str, url: str, suffix: str) -> Path:
    basename = Path(urlparse(url).path).name or f"download{suffix}"
    if not basename.endswith(suffix):
        basename += suffix
    return root / "raw" / source_id / basename
