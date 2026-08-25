from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .registry import load_source


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def generate_water_delivery(canonical_path: Path, destination: Path, release_id: str, force: bool = False) -> dict:
    index_path = destination / "water" / "index.json"
    if index_path.exists() and not force:
        return {"changed": False, "files": list((destination / "water").rglob("*.json"))}
    table = pd.read_parquet(canonical_path)
    source = load_source("ispra-bigbang")
    root = destination / "water"
    _write(root / "provenance.json", {"schemaVersion": 1, "releaseId": release_id, "theme": "water", "dataset": source, "officialVsDerived": {"official_observation": "Stima modello BIGBANG pubblicata da ISPRA; non misura diretta.", "derived_metric": "Non ancora disponibile per questo delivery."}})
    maps = []
    for (metric, year, level), rows in table[table.territory_level == "region"].groupby(["metric_id", "reference_year", "territory_level"]):
        logical = f"delivery/water/maps/{metric}/{year}/{level}.json"
        _write(destination / logical.removeprefix("delivery/"), {"schemaVersion": 1, "releaseId": release_id, "theme": "water", "kind": "official_model_map_values", "metricId": metric, "unit": "mm", "periodStart": f"{year}-01-01", "periodEnd": f"{year}-12-31", "territoryLevel": level, "columns": ["territoryId", "value"], "values": [[row.territory_id, float(row.value_decimal)] for row in rows.itertuples()], "provenanceRef": "delivery/water/provenance.json"})
        maps.append(logical)
    profiles = []
    for territory_id, rows in table.groupby("territory_id"):
        latest = rows.sort_values("reference_year").groupby("metric_id").tail(1)
        territory = latest.iloc[0]
        logical = f"delivery/water/profiles/{territory.territory_level}/{territory_id.rsplit(':', 1)[-1]}.json"
        _write(destination / logical.removeprefix("delivery/"), {"schemaVersion": 1, "releaseId": release_id, "theme": "water", "territory": {"territoryId": territory_id, "territoryVersionId": territory.territory_version_id, "level": territory.territory_level}, "latestObservations": [{"metricId": row.metric_id, "periodEnd": row.period_end, "value": float(row.value_decimal), "unit": row.unit_ucum} for row in latest.itertuples()], "historicalSeries": [{"metricId": metric, "values": [[int(row.reference_year), float(row.value_decimal)] for row in series.sort_values("reference_year").itertuples()]} for metric, series in rows.groupby("metric_id")], "provenanceRef": "delivery/water/provenance.json"})
        profiles.append(logical)
    geometry = ["delivery/soil/geometry/istat-region-2025.pmtiles"]
    _write(index_path, {"schemaVersion": 1, "releaseId": release_id, "theme": "water", "provenance": "delivery/water/provenance.json", "maps": maps, "profiles": profiles, "geometry": geometry})
    files = list(root.rglob("*.json"))
    return {"changed": True, "files": files, "maps": len(maps), "profiles": len(profiles), "bytes": sum(path.stat().st_size for path in files)}
