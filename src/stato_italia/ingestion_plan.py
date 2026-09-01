from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import json_dump, now_iso, sha256_file

PLAN_SCHEMA_VERSION = 1
ASSET_STATUSES = {"changed", "unchanged", "unverifiable"}


@dataclass(frozen=True)
class PlanContext:
    payload: dict[str, Any]
    raw_root: Path
    entries: dict[tuple[str, str], dict[str, Any]]


_ACTIVE_PLAN: PlanContext | None = None


def load_ingestion_plan(path: Path, *, scope: str, active_release_id: str, raw_root: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if payload.get("schemaVersion") != PLAN_SCHEMA_VERSION:
        raise ValueError("Unsupported ingestion-plan schema")
    if payload.get("scope") != scope:
        raise ValueError(f"Ingestion plan scope mismatch: expected {scope}")
    if payload.get("activeReleaseId") != active_release_id:
        raise ValueError("Ingestion plan does not reference the active release")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("Ingestion plan sources must be an array")
    entries: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in sources:
        if not isinstance(entry, dict) or entry.get("status") not in ASSET_STATUSES:
            raise ValueError("Invalid ingestion-plan source entry")
        key = (str(entry.get("source_id")), str(entry.get("asset_path")))
        if key in entries:
            raise ValueError(f"Duplicate ingestion-plan asset: {key[1]}")
        entries[key] = entry
    global _ACTIVE_PLAN
    _ACTIVE_PLAN = PlanContext(payload=payload, raw_root=raw_root, entries=entries)
    return payload


def clear_ingestion_plan() -> None:
    global _ACTIVE_PLAN
    _ACTIVE_PLAN = None


def active_ingestion_plan() -> dict[str, Any] | None:
    return _ACTIVE_PLAN.payload if _ACTIVE_PLAN else None


def source_family_changed(prefix: str) -> bool:
    if _ACTIVE_PLAN is None:
        return True
    return any(
        entry["status"] == "changed" and source_id.startswith(prefix)
        for (source_id, _asset_path), entry in _ACTIVE_PLAN.entries.items()
    )


def catalog_changed() -> bool:
    if _ACTIVE_PLAN is None:
        return True
    return _ACTIVE_PLAN.payload.get("catalog", {}).get("status") == "changed"


def planned_catalog_check() -> dict[str, Any] | None:
    """Return and validate the Copernicus catalog body staged by preflight."""
    if _ACTIVE_PLAN is None:
        return None
    entry = _ACTIVE_PLAN.payload.get("catalog")
    if not isinstance(entry, dict) or entry.get("status") != "changed":
        return None
    staged = entry.get("stagedPath")
    expected = entry.get("signature")
    if not isinstance(staged, str) or not isinstance(expected, str):
        raise ValueError("Changed Copernicus catalog lacks staged preflight state")
    staged_path = Path(staged)
    if not staged_path.is_file():
        raise FileNotFoundError("Changed Copernicus catalog staging is missing")
    payload = json.loads(staged_path.read_text())
    if payload.get("signature") != expected:
        raise ValueError("Changed Copernicus catalog staging signature mismatch")
    return payload


def _entry_for(destination: Path, source_id: str) -> dict[str, Any] | None:
    if _ACTIVE_PLAN is None:
        return None
    try:
        asset_path = str(destination.relative_to(_ACTIVE_PLAN.raw_root))
    except ValueError:
        return None
    return _ACTIVE_PLAN.entries.get((source_id, asset_path))


def planned_asset_status(destination: Path, source_id: str) -> str | None:
    entry = _entry_for(destination, source_id)
    return str(entry["status"]) if entry else None


def materialize_planned_asset(
    url: str,
    destination: Path,
    source_id: str,
    *,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Reuse trusted baseline or atomically promote a preflight body.

    Returning ``None`` authorizes the caller to contact upstream because the
    asset is changed without staged bytes or has no trusted baseline entry.
    """
    entry = _entry_for(destination, source_id)
    if entry is None:
        return None
    metadata_path = destination.with_suffix(destination.suffix + ".metadata.json")
    status = str(entry["status"])
    if status in {"unchanged", "unverifiable"}:
        expected = str(entry["baseline_sha256"])
        if not destination.is_file() or sha256_file(destination) != expected:
            raise ValueError(f"Trusted baseline asset is missing or stale after hydration: {entry['asset_path']}")
        if not metadata_path.is_file():
            raise FileNotFoundError(f"Trusted baseline metadata is missing after hydration: {entry['asset_path']}")
        metadata = json.loads(metadata_path.read_text())
        if metadata.get("source_id") != source_id or metadata.get("sha256") != expected:
            raise ValueError(f"Trusted baseline metadata mismatch: {entry['asset_path']}")
        return metadata | (source_context or {}) | {
            "unchanged": True,
            "plan_status": status,
            "local_path": str(destination),
            "metadata_path": str(metadata_path),
        }
    staged = entry.get("staged_path")
    if not staged:
        return None
    staged_path = Path(str(staged))
    observed_sha256 = str(entry["observed_sha256"])
    observed_bytes = int(entry["observed_bytes"])
    if not staged_path.is_file() or staged_path.stat().st_size != observed_bytes or sha256_file(staged_path) != observed_sha256:
        raise ValueError(f"Preflight staged asset checksum mismatch: {entry['asset_path']}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".promote", dir=destination.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(staged_path, temporary)
        if sha256_file(temporary) != observed_sha256:
            raise ValueError(f"Preflight staged asset checksum mismatch: {entry['asset_path']}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    prior = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    remote = entry.get("remote") if isinstance(entry.get("remote"), dict) else {}
    metadata = prior | {
        "source_id": source_id,
        "acquired_at": remote.get("checked_at") or now_iso(),
        "requested_url": remote.get("requested_url") or url,
        "resolved_url": remote.get("resolved_url") or url,
        "filename": destination.name,
        "bytes": observed_bytes,
        "sha256": observed_sha256,
        "content_type": remote.get("content_type"),
        "etag": remote.get("etag"),
        "last_modified": remote.get("last_modified"),
        "unchanged": False,
        "acquisition_mode": remote.get("acquisition_mode", prior.get("acquisition_mode", "official_http")),
    } | {key: value for key, value in remote.items() if key not in {"checked_at"}} | (source_context or {})
    json_dump(metadata_path, metadata)
    return metadata | {
        "plan_status": status,
        "local_path": str(destination),
        "metadata_path": str(metadata_path),
    }
