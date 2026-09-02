from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .analytics import SOIL_ANALYTICS_VERSION, latest_observations, load_territory_context
from .registry import load_source

DELIVERY_SCHEMA_VERSION = 1
DELIVERY_ALGORITHM_VERSION = "soil-delivery-v4"


def _json_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def _official(row: pd.Series) -> dict:
    return {
        "observationId": row["observation_id"],
        "metricId": row["metric_id"],
        "periodStart": row["period_start"],
        "periodEnd": row["period_end"],
        "value": float(row["value_decimal"]),
        "unit": row["unit_ucum"],
    }


def _territory(territory: dict, context: dict[str, dict]) -> dict:
    parents: list[dict] = []
    parent_id = territory.get("parent_territory_id")
    while parent_id:
        parent = context[parent_id]
        parents.append({"territoryId": parent["territory_id"], "territoryVersionId": parent["territory_version_id"], "level": parent["level"], "istatCode": parent["istat_code"], "name": parent["name"]})
        parent_id = parent.get("parent_territory_id")
    return {
        "territoryId": territory["territory_id"],
        "territoryVersionId": territory["territory_version_id"],
        "level": territory["level"],
        "istatCode": territory["istat_code"],
        "name": territory["name"],
        "referenceDate": territory["reference_date"],
        "parents": parents,
    }


def _comparison(latest_lookup: dict[tuple[str, str, str, str], pd.Series], territory: dict, observation: pd.Series, context: dict[str, dict]) -> list[dict]:
    output: list[dict] = []
    scope = {"province": "province", "region": "region", "country": "italy"}
    parent_id = territory.get("parent_territory_id")
    while parent_id:
        parent = context[parent_id]
        key = (parent_id, observation["metric_id"], observation["period_start"], observation["period_end"])
        target = latest_lookup.get(key)
        label = scope.get(parent["level"])
        if label:
            if target is None:
                output.append({"scope": label, "status": "unavailable", "reason": "missing_same_period"})
            elif target["territory_version_id"].rsplit("@", 1)[-1] != observation["territory_version_id"].rsplit("@", 1)[-1]:
                output.append({"scope": label, "status": "unavailable", "reason": "territory_reference_mismatch"})
            else:
                output.append({"scope": label, "status": "available", "territoryId": parent_id, "observation": _official(target)})
        parent_id = parent.get("parent_territory_id")
    return output


def _derived(rows: pd.DataFrame) -> list[dict]:
    if rows.empty:
        return []
    def simplify(raw: pd.Series) -> dict:
        row = raw.to_dict()
        def change(name: str) -> dict:
            return {"status": _json_value(row.get(f"change_{name}_status")), "value": _json_value(row.get(f"change_{name}_value")), "unit": _json_value(row.get(f"change_{name}_unit")), "reason": _json_value(row.get(f"change_{name}_reason"))}
        def benchmark(scope: str) -> dict:
            return {"peerCount": _json_value(row.get(f"{scope}_peer_count")), "percentile": _json_value(row.get(f"{scope}_percentile")), "percentileStatus": _json_value(row.get(f"{scope}_percentile_status")), "rank": _json_value(row.get(f"{scope}_ranking")), "rankStatus": _json_value(row.get(f"{scope}_ranking_status"))}
        return {
            "kind": "derived_analytics_summary", "metricId": row["metric_id"], "analyticsId": row["analytics_id"],
            "algorithmVersion": row["algorithm_version"], "analyticsRef": "derived/soil/algorithm_version=soil-analytics-v1/analytics.parquet",
            "changes": {"previous": change("previous"), "fiveYears": change("5y"), "tenYears": change("10y")},
            "trend": {key: _json_value(row.get(f"trend_{key}")) for key in ("status", "slope_per_year", "unit", "direction", "r_squared", "coverage_observations", "coverage_expected", "reason")},
            "benchmarks": {scope: benchmark(scope) for scope in ("national", "regional", "provincial")},
        }
    return [simplify(row) for _, row in rows.iterrows()]


def _profile_shard(territory: dict, context: dict[str, dict]) -> tuple[str, str]:
    if territory["level"] == "municipality":
        province = context[territory["province_territory_id"]]
        return "municipality", province["istat_code"]
    if territory["level"] == "province":
        region = context[territory["region_territory_id"]]
        return "province", region["istat_code"]
    return territory["level"], "all"


def generate_soil_delivery(
    canonical_path: Path, analytics_path: Path, canonical_root: Path, raw_root: Path,
    destination: Path, release_id: str, force: bool = False,
) -> dict:
    index_path = destination / "soil" / "index.json"
    if index_path.exists() and not force:
        previous = json.loads(index_path.read_text())
        if previous.get("algorithmVersion") == DELIVERY_ALGORITHM_VERSION and previous.get("analyticsAlgorithmVersion") == SOIL_ANALYTICS_VERSION:
            files = sorted(path for path in (destination / "soil").rglob("*.json"))
            return {"changed": False, "skipped": True, "files": files, "bytes": sum(path.stat().st_size for path in files)}

    for generated in (destination / "soil").rglob("*.json"):
        generated.unlink()

    observations = pd.read_parquet(canonical_path)
    analytics = pd.read_parquet(analytics_path)
    context = load_territory_context(canonical_root)
    latest = latest_observations(observations)
    latest_lookup = {(row["territory_id"], row["metric_id"], row["period_start"], row["period_end"]): row for _, row in latest.iterrows()}
    by_territory_observations = defaultdict(list)
    for _, row in observations.sort_values(["metric_id", "period_end", "period_start"]).iterrows():
        by_territory_observations[row["territory_id"]].append(row)
    by_territory_latest = defaultdict(list)
    for _, row in latest.iterrows():
        by_territory_latest[row["territory_id"]].append(row)
    by_territory_analytics = defaultdict(list)
    for territory_id, rows in analytics.groupby("territory_id"):
        by_territory_analytics[territory_id] = rows

    source = load_source("ispra-soil")
    raw_metadata = raw_root / "raw" / "ispra-soil-2025" / "consumo-di-suolo-2025.xlsx.metadata.json"
    provenance = {
        "schemaVersion": DELIVERY_SCHEMA_VERSION,
        "releaseId": release_id,
        "theme": "soil",
        "dataset": source,
        "raw": json.loads(raw_metadata.read_text()),
        "officialVsDerived": {
            "official_observation": "Valore pubblicato da ISPRA/SNPA, normalizzato senza modificarne il valore.",
            "derived_metric": "Elaborazione deterministica di Stato d'Italia; algoritmo e input dichiarati.",
        },
    }
    _write_json(destination / "soil" / "provenance.json", provenance)

    shards: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for territory_id in sorted(by_territory_observations):
        territory = context[territory_id]
        history = defaultdict(list)
        for row in by_territory_observations[territory_id]:
            history[row["metric_id"]].append(_official(row))
        latest_rows = by_territory_latest[territory_id]
        profile = {
            "territory": _territory(territory, context),
            "theme": "soil",
            "latestObservations": [_official(row) for row in sorted(latest_rows, key=lambda item: item["metric_id"])],
            "historicalSeries": [
                {"metricId": metric_id, "columns": ["observationId", "periodStart", "periodEnd", "value", "unit"],
                 "values": [[item["observationId"], item["periodStart"], item["periodEnd"], item["value"], item["unit"]] for item in rows]}
                for metric_id, rows in sorted(history.items())
            ],
            "derivedMetrics": _derived(by_territory_analytics[territory_id]),
            "comparisons": {row["metric_id"]: _comparison(latest_lookup, territory, row, context) for row in latest_rows},
            "provenanceRef": "delivery/soil/provenance.json",
        }
        shards[_profile_shard(territory, context)].append(profile)
    profile_paths: list[str] = []
    for (level, shard), profiles in sorted(shards.items()):
        logical_path = f"delivery/soil/profiles/{level}/{shard}.json"
        _write_json(destination / logical_path.removeprefix("delivery/"), {
            "schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "soil",
            "territoryLevel": level, "profiles": profiles,
        })
        profile_paths.append(logical_path)

    map_paths: list[str] = []
    for (metric_id, start, end, level), values in observations.groupby(["metric_id", "period_start", "period_end", "territory_level"]):
        period_key = f"{start[:4]}-{end[:4]}"
        logical_path = f"delivery/soil/maps/{metric_id}/{period_key}/{level}.json"
        first = values.iloc[0]
        _write_json(destination / logical_path.removeprefix("delivery/"), {
            "schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "soil", "kind": "official_map_values",
            "metricId": metric_id, "unit": first["unit_ucum"], "periodStart": start, "periodEnd": end,
            "territoryLevel": level, "territoryReferenceDate": first["territory_version_id"].rsplit("@", 1)[-1],
            "columns": ["territoryId", "value"], "values": [[row["territory_id"], float(row["value_decimal"])] for _, row in values.iterrows()],
            "provenanceRef": "delivery/soil/provenance.json",
        })
        map_paths.append(logical_path)

    ranking_paths: list[str] = []
    analytics_lookup = analytics.set_index(["territory_id", "metric_id"])
    for (metric_id, start, end, level), official in latest.groupby(["metric_id", "period_start", "period_end", "territory_level"]):
        summaries = [analytics_lookup.loc[(row["territory_id"], metric_id)] for _, row in official.iterrows()]
        if not any(summary["national_percentile_status"] == "available" for summary in summaries):
            continue
        rows = []
        for _, value in official.iterrows():
            territory = context[value["territory_id"]]
            summary = analytics_lookup.loc[(value["territory_id"], metric_id)]
            rows.append({
                "territoryId": value["territory_id"], "name": territory["name"], "istatCode": territory["istat_code"],
                "value": float(value["value_decimal"]), "percentile": _json_value(summary["national_percentile"]),
                "rank": _json_value(summary["national_ranking"]),
            })
        rows.sort(key=lambda item: (item["rank"] is None, item["rank"], item["territoryId"]))
        period_key = f"{start[:4]}-{end[:4]}"
        logical_path = f"delivery/soil/rankings/{metric_id}/{period_key}/{level}.json"
        _write_json(destination / logical_path.removeprefix("delivery/"), {
            "schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "soil", "kind": "derived_ranking",
            "algorithmVersion": SOIL_ANALYTICS_VERSION, "metricId": metric_id, "periodStart": start, "periodEnd": end,
            "territoryLevel": level, "rows": rows, "provenanceRef": "delivery/soil/provenance.json",
        })
        ranking_paths.append(logical_path)

    geometry = [f"delivery/soil/geometry/{path.name}" for path in sorted((destination / "soil" / "geometry").glob("*.pmtiles"))]
    if {Path(path).name for path in geometry} != {"istat-municipality-2025.pmtiles", "istat-province-2025.pmtiles", "istat-region-2025.pmtiles"}:
        raise ValueError("Missing PMTiles geometry required for soil delivery")
    index = {
        "schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "soil", "algorithmVersion": DELIVERY_ALGORITHM_VERSION,
        "analyticsAlgorithmVersion": SOIL_ANALYTICS_VERSION, "provenance": "delivery/soil/provenance.json",
        "profileShards": profile_paths, "maps": map_paths, "rankings": ranking_paths, "geometry": geometry,
    }
    _write_json(index_path, index)
    files = sorted(path for path in (destination / "soil").rglob("*.json"))
    return {"changed": True, "files": files, "bytes": sum(path.stat().st_size for path in files), "profiles": len(profile_paths), "maps": len(map_paths), "rankings": len(ranking_paths)}
