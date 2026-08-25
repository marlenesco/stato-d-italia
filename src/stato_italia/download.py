from __future__ import annotations

import shutil
import json
import mimetypes
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .common import json_dump, now_iso, sha256_file


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.links.append(value)


def resolve_download_url(source: dict) -> str:
    """Resolve one direct asset advertised by an official landing page.

    File names are source contracts too. A changed or ambiguous landing page must
    fail before any raw bytes are accepted.
    """
    pattern = source.get("download_link_filename_pattern")
    if not pattern:
        return str(source["download_url"])
    landing_url = str(source["landing_url"])
    response = requests.get(
        landing_url,
        timeout=(15, 60),
        headers={"User-Agent": "stato-italia-data/0.1"},
    )
    response.raise_for_status()
    collector = _LinkCollector()
    collector.feed(response.text)
    filename_pattern = re.compile(str(pattern))
    candidates = sorted({
        urljoin(response.url, link)
        for link in collector.links
        if filename_pattern.fullmatch(Path(urlparse(urljoin(response.url, link)).path).name)
    })
    if len(candidates) != 1:
        raise ValueError(
            f"Unexpected official download links for {source['source_id']}: "
            f"expected exactly one filename matching {pattern!r}, found={candidates}"
        )
    return candidates[0]


def _source_context(source: dict) -> dict:
    return {
        "landing_url": source.get("landing_url"),
        "dataset_version": source.get("dataset_version"),
        "license": source.get("license"),
        "methodology_url": source.get("methodology_url"),
        "geographical_granularity": source.get("geographical_granularity"),
        "temporal_granularity": source.get("temporal_granularity"),
    }


def _local_metadata(
    url: str, destination: Path, source_id: str, prior: dict | None, source_context: dict | None,
) -> dict:
    """Record user-supplied raw bytes without pretending they were downloaded."""
    checksum = sha256_file(destination)
    metadata = {
        "source_id": source_id,
        "acquired_at": now_iso(),
        "acquisition_mode": "local_supplied",
        "resolved_url": None,
        "requested_url": url,
        "filename": destination.name,
        "bytes": destination.stat().st_size,
        "sha256": checksum,
        "content_type": mimetypes.guess_type(destination.name)[0],
        "etag": None,
        "last_modified": None,
        "unchanged": bool(prior and prior.get("sha256") == checksum),
    }
    return metadata | (source_context or {})


def download(
    url: str, destination: Path, source_id: str, *, offline: bool = False, source_context: dict | None = None,
) -> dict:
    """Download once, keep source HTTP facts alongside immutable raw bytes."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    metadata_path = destination.with_suffix(destination.suffix + ".metadata.json")
    prior = json.loads(metadata_path.read_text()) if destination.exists() and metadata_path.exists() else None
    if offline:
        if not destination.exists():
            raise FileNotFoundError(
                f"Offline source asset missing for {source_id}: {destination}. "
                "Place the official raw file at this exact path, then run again."
            )
        if prior and prior.get("source_id") != source_id:
            raise ValueError(
                f"Offline source metadata mismatch for {destination}: "
                f"expected source_id={source_id!r}, got={prior.get('source_id')!r}"
            )
        metadata = _local_metadata(url, destination, source_id, prior, source_context)
        json_dump(metadata_path, metadata)
        return metadata
    headers = {"User-Agent": "stato-italia-data/0.1"}
    # A path can retain its filename while its official URL changes. Never use
    # validators from the old URL: a 304 would keep stale or redirected bytes.
    conditional_prior = prior if prior and prior.get("requested_url") == url else None
    if conditional_prior and conditional_prior.get("etag"):
        headers["If-None-Match"] = conditional_prior["etag"]
    if conditional_prior and conditional_prior.get("last_modified"):
        headers["If-Modified-Since"] = conditional_prior["last_modified"]
    with requests.get(url, stream=True, timeout=(15, 180), headers=headers) as response:
        if response.status_code == 304:
            if conditional_prior is None:
                raise ValueError(f"Unexpected 304 without a matching prior URL: {url}")
            conditional_prior["checked_at"] = now_iso()
            conditional_prior["unchanged"] = True
            conditional_prior.update(source_context or {})
            json_dump(metadata_path, conditional_prior)
            return conditional_prior
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
    } | (source_context or {})
    json_dump(metadata_path, metadata)
    return metadata


def download_registered_source(source: dict, destination: Path, *, offline: bool = False) -> dict:
    """Acquire a registry source, retaining both landing and resolved URLs."""
    if offline:
        metadata_path = destination.with_suffix(destination.suffix + ".metadata.json")
        prior = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        url = str(prior.get("requested_url") or source.get("download_url") or source["landing_url"])
    else:
        url = resolve_download_url(source)
    return download(
        url,
        destination,
        str(source["source_id"]),
        offline=offline,
        source_context=_source_context(source),
    )


def raw_path(root: Path, source_id: str, url: str, suffix: str) -> Path:
    basename = Path(urlparse(url).path).name or f"download{suffix}"
    if not basename.endswith(suffix):
        basename += suffix
    return root / "raw" / source_id / basename
