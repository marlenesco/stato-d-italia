from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .registry import load_source

DELIVERY_SCHEMA_VERSION = 1
DELIVERY_ALGORITHM_VERSION = "dissesto-delivery-v1"
MAPPABLE_LEVELS = ("municipality", "province", "region")


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def generate_dissesto_delivery(
    canonical_path: Path, destination: Path, release_id: str, geometry: dict[str, Path], force: bool = False,
) -> dict:
    """Generate browser-ready official IdroGEO snapshots without derived rankings."""
    index_path = destination / "dissesto" / "index.json"
    if index_path.exists() and not force:
        previous = json.loads(index_path.read_text())
        if previous.get("algorithmVersion") == DELIVERY_ALGORITHM_VERSION:
            files = sorted(path for path in (destination / "dissesto").rglob("*.json"))
            return {"changed": False, "skipped": True, "files": files, "bytes": sum(path.stat().st_size for path in files)}
    if set(geometry) != set(MAPPABLE_LEVELS) or not all(path.exists() for path in geometry.values()):
        raise ValueError("Missing 2024 ISTAT PMTiles geometry required for IdroGEO delivery")
    for generated in (destination / "dissesto").rglob("*.json"):
        generated.unlink()

    table = pd.read_parquet(canonical_path)
    required = {"metric_id", "territory_id", "territory_level", "period_start", "period_end", "value_decimal", "value_state", "unit_ucum", "territory_version_id"}
    missing = required - set(table.columns)
    if missing:
        raise ValueError(f"Dissesto canonical contract missing columns: {sorted(missing)}")
    observed = table[table["value_state"] == "observed"].copy()
    if observed.empty:
        raise ValueError("Dissesto canonical contains no observed values for delivery")

    root = destination / "dissesto"
    _write(root / "provenance.json", {
        "schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "dissesto",
        "dataset": load_source("ispra-idrogeo-risk-2024"),
        "officialVsDerived": {
            "official_observation": "Indicatori aggregati ufficiali ISPRA IdroGEO.",
            "derived_metric": "Nessuna metrica derivata o ranking pubblicato in questa release.",
        },
        "missingValuePolicy": "Il valore -1 della fonte è pubblicato come unavailable e non compare come zero nella mappa.",
    })

    maps: list[str] = []
    for (metric, start, end, level), rows in observed[observed["territory_level"].isin(MAPPABLE_LEVELS)].groupby(
        ["metric_id", "period_start", "period_end", "territory_level"], sort=True,
    ):
        reference_dates = rows["territory_version_id"].str.rsplit("@", n=1).str[-1].unique().tolist()
        if reference_dates != ["2024-01-01"]:
            raise ValueError(f"Unexpected IdroGEO territory reference for {metric}/{level}: {reference_dates}")
        period_key = f"{start[:4]}-{end[:4]}"
        logical_path = f"delivery/dissesto/maps/{metric}/{period_key}/{level}.json"
        _write(destination / logical_path.removeprefix("delivery/"), {
            "schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "dissesto",
            "kind": "official_snapshot_map_values", "metricId": metric, "unit": rows.iloc[0]["unit_ucum"],
            "periodStart": start, "periodEnd": end, "territoryLevel": level,
            "territoryReferenceDate": "2024-01-01", "columns": ["territoryId", "value"],
            "values": [[row.territory_id, float(row.value_decimal)] for row in rows.itertuples()],
            "provenanceRef": "delivery/dissesto/provenance.json",
        })
        maps.append(logical_path)

    geometry_paths = [f"delivery/dissesto/geometry/{geometry[level].name}" for level in MAPPABLE_LEVELS]
    _write(index_path, {
        "schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "dissesto",
        "algorithmVersion": DELIVERY_ALGORITHM_VERSION, "provenance": "delivery/dissesto/provenance.json",
        "maps": maps, "rankings": [], "geometry": geometry_paths,
    })
    files = sorted(path for path in root.rglob("*.json"))
    return {"changed": True, "files": files, "maps": len(maps), "bytes": sum(path.stat().st_size for path in files)}
