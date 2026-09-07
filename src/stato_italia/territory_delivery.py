from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .common import sha256_file


DELIVERY_ALGORITHM_VERSION = "territory-identity-delivery-v2"
_LEVELS = ("municipality", "province", "region")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _identity(row: dict, parents: dict[str, dict]) -> dict:
    parent_code = row.get("parent_istat_code")
    parent_level = {"municipality": "province", "province": "region"}.get(str(row["level"]))
    parent = parents.get(f"{parent_level}:{parent_code}") if parent_level and parent_code else None
    hierarchy = ([] if parent is None else [parent])
    if parent is not None:
        hierarchy.extend(parent["parents"])
    return {
        "territoryId": row["territory_id"],
        "territoryVersionId": row["territory_version_id"],
        "level": row["level"],
        "istatCode": row["istat_code"],
        "name": row["name"],
        "referenceDate": row["reference_date"],
        "parents": hierarchy,
    }


def generate_territory_delivery(
    canonical_root: Path, destination: Path, release_id: str, *, force: bool = False,
) -> dict:
    """Publish compact 2025 territory identities, independent from every domain."""
    root = destination / "territories"
    index_path = root / "index.json"
    source_paths = [canonical_root / "territories" / "reference_year=2025" / f"{level}.parquet" for level in _LEVELS]
    if not all(path.is_file() for path in source_paths):
        raise FileNotFoundError("Territory identity delivery requires all 2025 canonical territory levels")
    signature = {path.name: sha256_file(path) for path in source_paths}
    if index_path.exists() and not force:
        previous = json.loads(index_path.read_text())
        if previous.get("algorithmVersion") == DELIVERY_ALGORITHM_VERSION and previous.get("canonicalSignature") == signature:
            files = sorted(root.rglob("*.json"))
            return {"changed": False, "files": files, "bytes": sum(path.stat().st_size for path in files)}
    if root.exists():
        shutil.rmtree(root)

    frames = {level: pd.read_parquet(path) for level, path in zip(_LEVELS, source_paths, strict=True)}
    required = {"territory_id", "territory_version_id", "level", "istat_code", "name", "parent_istat_code", "reference_date"}
    for level, frame in frames.items():
        if missing := required - set(frame.columns):
            raise ValueError(f"Territory identity canonical contract lacks fields for {level}: {sorted(missing)}")
        if set(frame["level"].astype(str)) != {level}:
            raise ValueError(f"Territory identity canonical level mismatch for {level}")
        if set(frame["reference_date"].astype(str)) != {"2025-01-01"}:
            raise ValueError(f"Territory identity delivery requires the 2025 reference for {level}")

    parents: dict[str, dict] = {}
    identities: dict[str, list[dict]] = {}
    for level in ("region", "province", "municipality"):
        records = []
        for row in frames[level].sort_values("territory_id").to_dict("records"):
            identity = _identity(row, parents)
            parents[f"{level}:{row['istat_code']}"] = identity
            records.append(identity)
        identities[level] = records
    identities["country"] = [{
        "territoryId": "it:country:IT", "territoryVersionId": "it:country:IT@2025-01-01",
        "level": "country", "istatCode": "IT", "name": "Italia", "referenceDate": "2025-01-01", "parents": [],
    }]

    shards: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for level, records in identities.items():
        for identity in records:
            shard = identity["istatCode"][:3] if level == "municipality" else "all"
            shards[(level, shard)].append(identity)
    paths: list[str] = []
    for (level, shard), records in sorted(shards.items()):
        logical = f"delivery/territories/{level}/{shard}.json"
        _write(destination / logical.removeprefix("delivery/"), {
            "schemaVersion": 1, "releaseId": release_id, "kind": "territory_identity_shard",
            "territoryLevel": level, "territories": records,
        })
        paths.append(logical)
    _write(index_path, {
        "schemaVersion": 1, "releaseId": release_id, "kind": "territory_identity_index",
        "algorithmVersion": DELIVERY_ALGORITHM_VERSION, "referenceDate": "2025-01-01",
        "canonicalSignature": signature, "shards": paths,
        "currentIdentityIds": {
            level: sorted(identity["territoryId"] for identity in records)
            for level, records in identities.items()
        },
    })
    files = sorted(root.rglob("*.json"))
    return {"changed": True, "files": files, "bytes": sum(path.stat().st_size for path in files), "territories": sum(len(items) for items in identities.values())}
