from __future__ import annotations

import json
from hashlib import sha256
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import requests

from .download import resolve_download_url

SOURCE_STATE_LOGICAL_PATH = "metadata/source-state.json"
SOURCE_STATE_SCHEMA_VERSION = 1
_LEGACY_KEYS = {
    "sourceId": "source_id", "assetPath": "asset_path", "resolvedUrl": "resolved_url",
    "lastModified": "last_modified", "datasetVersion": "dataset_version", "checkedAt": "checked_at",
}


def _normalised_state(state: dict[str, Any]) -> dict[str, Any]:
    """Read the short-lived camelCase migration format without changing it."""
    sources = []
    for source in state.get("sources", []):
        entry = dict(source)
        for old, new in _LEGACY_KEYS.items():
            if new not in entry and old in entry:
                entry[new] = entry.pop(old)
        sources.append(entry)
    return {**state, "sources": sources}


def _raw_path_for_sidecar(sidecar: Path) -> Path:
    suffix = ".metadata.json"
    if not str(sidecar).endswith(suffix):
        raise ValueError(f"Invalid raw metadata sidecar name: {sidecar}")
    return Path(str(sidecar)[: -len(suffix)])


def _entry(metadata: dict[str, Any], raw_path: Path, raw_root: Path) -> dict[str, Any]:
    return {
        "source_id": metadata["source_id"],
        "asset_path": str(raw_path.relative_to(raw_root)),
        "resolved_url": metadata.get("resolved_url"),
        "etag": metadata.get("etag"),
        "last_modified": metadata.get("last_modified"),
        "sha256": metadata["sha256"],
        "bytes": int(metadata["bytes"]),
        "dataset_version": metadata.get("dataset_version"),
        "period": metadata.get("period") or metadata.get("temporal_granularity"),
        "checked_at": metadata.get("checked_at") or metadata.get("acquired_at"),
        "landing_url": metadata.get("landing_url"),
        "download_link_filename_pattern": metadata.get("download_link_filename_pattern"),
        "preflight_method": metadata.get("preflight_method"),
        "source_signature": metadata.get("source_signature"),
    }


def build_source_state_from_metadata_paths(raw_root: Path, sidecars: Iterable[Path], *, include_catalog: Path | None = None) -> dict[str, Any]:
    """Build state from phase declarations, never from a global raw scan."""
    entries: list[dict[str, Any]] = []
    for sidecar in sorted(set(sidecars)):
        try:
            metadata = json.loads(sidecar.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid raw metadata sidecar: {sidecar}") from exc
        if not isinstance(metadata, dict) or not isinstance(metadata.get("source_id"), str):
            raise ValueError(f"Invalid raw metadata contract: {sidecar}")
        raw_path = _raw_path_for_sidecar(sidecar)
        required = ("sha256", "bytes")
        if any(metadata.get(key) is None for key in required):
            raise ValueError(f"Incomplete raw metadata contract: {sidecar}")
        entries.append(_entry(metadata, raw_path, raw_root))
    catalogs = [include_catalog] if include_catalog and include_catalog.exists() else []
    for catalog in catalogs:
        try:
            payload = json.loads(catalog.read_text())
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid geospatial catalog state: {catalog}") from exc
        if not isinstance(payload.get("source_id"), str) or not isinstance(payload.get("signature"), str):
            raise ValueError(f"Invalid geospatial catalog contract: {catalog}")
        entries.append({
            "source_id": payload["source_id"], "asset_path": str(catalog.relative_to(raw_root)),
            "resolved_url": None, "etag": None, "last_modified": None,
            "sha256": payload["signature"], "bytes": catalog.stat().st_size,
            "dataset_version": None, "period": None, "checked_at": payload.get("checked_at"), "kind": "catalog",
        })
    entries.sort(key=lambda entry: entry["asset_path"])
    if not entries:
        raise ValueError("Source state requires at least one declared raw asset")
    return {"schemaVersion": SOURCE_STATE_SCHEMA_VERSION, "sources": entries}


def build_source_state(raw_root: Path) -> dict[str, Any]:
    """Compatibility helper for legacy callers; new pipeline passes declarations."""
    return build_source_state_from_metadata_paths(raw_root, raw_root.rglob("*.metadata.json"))


def merge_source_states(previous: dict[str, Any] | None, current_scope: dict[str, Any], *, scope: str) -> dict[str, Any]:
    """Replace only one scope; preserve active entries owned by the other scope."""
    prior = _normalised_state(previous) if previous else {"schemaVersion": SOURCE_STATE_SCHEMA_VERSION, "sources": []}
    if prior.get("schemaVersion") != SOURCE_STATE_SCHEMA_VERSION:
        raise ValueError("Unsupported source-state schema")
    current = _normalised_state(current_scope)
    if scope != "all" and any(source_scope(str(entry["source_id"])) != scope for entry in current["sources"]):
        raise ValueError(f"Source-state declaration contains an entry outside {scope} scope")
    if scope == "all":
        merged = []
    else:
        merged = [entry for entry in prior["sources"] if source_scope(str(entry["source_id"])) != scope]
    merged.extend(current["sources"])
    merged.sort(key=lambda entry: entry["asset_path"])
    return {"schemaVersion": SOURCE_STATE_SCHEMA_VERSION, "sources": merged}


def comparable_state(state: dict[str, Any]) -> tuple[tuple[tuple[str, Any], ...], ...]:
    """Exclude only check timestamp: URL, validators and bytes remain provenance."""
    state = _normalised_state(state)
    if state.get("schemaVersion") != SOURCE_STATE_SCHEMA_VERSION or not isinstance(state.get("sources"), list):
        raise ValueError("Unsupported source-state schema")
    comparable = []
    for entry in state["sources"]:
        if not isinstance(entry, dict):
            raise ValueError("Invalid source-state entry")
        comparable.append(tuple(sorted((key, value) for key, value in entry.items() if key != "checked_at")))
    return tuple(sorted(comparable))


def source_state_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    if previous is None:
        return True
    # Persist a canonical snake_case representation once; this is a deliberate
    # provenance-format migration, not a source-content change.
    if any(any(key in entry for key in _LEGACY_KEYS) for entry in previous.get("sources", [])):
        return True
    return comparable_state(previous) != comparable_state(current)


def source_state_counts(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, int]:
    previous = _normalised_state(previous) if previous else None
    current_entries = {entry["asset_path"]: entry for entry in current["sources"]}
    previous_entries = {entry["asset_path"]: entry for entry in previous.get("sources", [])} if previous else {}
    changed = sum(
        1 for path, entry in current_entries.items()
        if path not in previous_entries or comparable_state({"schemaVersion": SOURCE_STATE_SCHEMA_VERSION, "sources": [previous_entries[path]]}) != comparable_state({"schemaVersion": SOURCE_STATE_SCHEMA_VERSION, "sources": [entry]})
    )
    return {"checked": len(current_entries), "changed": changed, "unchanged": len(current_entries) - changed}


def changed_source_entries(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    previous = _normalised_state(previous) if previous else None
    previous_entries = {entry["asset_path"]: entry for entry in previous.get("sources", [])} if previous else {}
    changed: list[dict[str, Any]] = []
    for entry in current["sources"]:
        earlier = previous_entries.get(entry["asset_path"])
        if earlier is None or comparable_state({"schemaVersion": SOURCE_STATE_SCHEMA_VERSION, "sources": [earlier]}) != comparable_state({"schemaVersion": SOURCE_STATE_SCHEMA_VERSION, "sources": [entry]}):
            changed.append(entry)
    return changed


def source_scope(source_id: str) -> str:
    return "geospatial" if source_id.startswith("copernicus-") else "data"


def scoped_source_state(state: dict[str, Any] | None, scope: str) -> dict[str, Any] | None:
    if state is None:
        return None
    state = _normalised_state(state)
    if scope == "all":
        return state
    return {
        "schemaVersion": SOURCE_STATE_SCHEMA_VERSION,
        "sources": [entry for entry in state["sources"] if source_scope(str(entry["source_id"])) == scope],
    }


def check_persisted_sources(state: dict[str, Any] | None, *, scope: str) -> dict[str, Any]:
    """GET-check active source state without relying on HEAD or local cache.

    A failed or unverifiable source stays changed: caller must run the fail-closed
    pipeline instead of treating it as a no-op.
    """
    if state is None:
        return {"scope": scope, "sourceChecks": 0, "sourcesChanged": 0, "sourcesUnchanged": 0, "changed": True, "reason": "no_persisted_source_state"}
    state = _normalised_state(state)
    entries = [entry for entry in state["sources"] if source_scope(str(entry["source_id"])) == scope]
    if scope == "geospatial" and not entries:
        return {"scope": scope, "sourceChecks": 0, "sourcesChanged": 0, "sourcesUnchanged": 0, "changed": True, "reason": "no_persisted_geospatial_state"}
    changed = 0
    unchanged = 0
    details: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("kind") == "catalog":
            continue
        if entry.get("preflight_method") == "idrogeo_exports_v1" or (
            entry.get("source_id") == "ispra-idrogeo-risk-2024"
            and str(entry.get("asset_path", "")).endswith("/idrogeo-risk-api-responses.zip")
        ):
            try:
                from .dissesto import check_dissesto_source

                check = check_dissesto_source(entry.get("source_signature"))
                is_changed = bool(check["changed"])
                changed += int(is_changed)
                unchanged += int(not is_changed)
                details.append({
                    "asset_path": entry["asset_path"],
                    "status": "changed" if is_changed else "unchanged",
                    "method": "idrogeo_exports_v1", "exports": check["exports"],
                })
            except Exception as exc:
                changed += 1
                details.append({"asset_path": entry["asset_path"], "status": "unverifiable", "reason": type(exc).__name__})
            continue
        url = entry.get("resolved_url")
        if entry.get("landing_url") and entry.get("download_link_filename_pattern"):
            try:
                resolved = resolve_download_url({
                    "landing_url": entry["landing_url"],
                    "download_link_filename_pattern": entry["download_link_filename_pattern"],
                })
            except Exception as exc:
                changed += 1
                details.append({"asset_path": entry["asset_path"], "status": "unverifiable", "reason": type(exc).__name__})
                continue
            if resolved != url:
                changed += 1
                details.append({"asset_path": entry["asset_path"], "status": "changed", "reason": "resolved_url_changed"})
                continue
            url = resolved
        if not url:
            changed += 1
            details.append({"asset_path": entry["asset_path"], "status": "unverifiable", "reason": "missing_resolved_url"})
            continue
        headers = {"User-Agent": "stato-italia-data/0.1"}
        if entry.get("etag"):
            headers["If-None-Match"] = str(entry["etag"])
        if entry.get("last_modified"):
            headers["If-Modified-Since"] = str(entry["last_modified"])
        try:
            with requests.get(str(url), stream=True, timeout=(15, 180), headers=headers) as response:
                if response.status_code == 304:
                    unchanged += 1
                    details.append({"asset_path": entry["asset_path"], "status": "unchanged", "method": "conditional_get"})
                    continue
                response.raise_for_status()
                response_etag = response.headers.get("ETag")
                if response_etag and response_etag == entry.get("etag"):
                    unchanged += 1
                    details.append({"asset_path": entry["asset_path"], "status": "unchanged", "method": "get_etag"})
                    continue
                digest = sha256()
                total = 0
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        digest.update(chunk)
                        total += len(chunk)
                same = digest.hexdigest() == entry["sha256"] and total == int(entry["bytes"])
                if same:
                    unchanged += 1
                    details.append({"asset_path": entry["asset_path"], "status": "unchanged", "method": "get_sha256"})
                else:
                    changed += 1
                    details.append({"asset_path": entry["asset_path"], "status": "changed", "method": "get_sha256"})
        except requests.RequestException as exc:
            changed += 1
            details.append({"asset_path": entry["asset_path"], "status": "unverifiable", "reason": type(exc).__name__})
    return {
        "scope": scope, "sourceChecks": len(entries), "sourcesChanged": changed,
        "sourcesUnchanged": unchanged, "changed": bool(changed), "sources": details,
    }


def declared_raw_paths(raw_root: Path) -> Iterable[Path]:
    """Return raw bytes and provenance sidecars declared by an acquisition, never all raw files."""
    for sidecar in sorted(raw_root.rglob("*.metadata.json")):
        raw_path = _raw_path_for_sidecar(sidecar)
        if raw_path.exists():
            yield raw_path
        yield sidecar
