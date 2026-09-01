from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .common import sha256_file

ALGORITHM_VERSION = "territory-profile-insights-v1"

DOMAIN_DEFINITIONS = (
    {
        "id": "soil", "title": "Suolo", "metric": "soil_net_consumption_hectares",
        "label": "Incremento netto di suolo consumato", "source": "Osservazione ufficiale ISPRA / SNPA",
        "kind": "official_observation", "levels": {"municipality", "province", "region"}, "direction": "less_is_better",
        "href": "/suolo?metric=soil_net_consumption_hectares&level={level}&period={period}&territory={territory}#mappa",
    },
    {
        "id": "forests", "title": "Foreste", "metric": "tree_cover_mean",
        "label": "Copertura arborea media", "source": "Elaborazione zonale Copernicus",
        "kind": "derived_metric", "levels": {"municipality", "province", "region"}, "direction": "context_only",
        "href": "/foreste?metric=tree_cover_mean&level={level}&period={period}&territory={territory}#mappa",
    },
    {
        "id": "water", "title": "Acqua", "metric": "water_total_precipitation_mm",
        "label": "Precipitazione totale", "source": "Stima ufficiale modellistica BIGBANG 10.0",
        "kind": "official_model", "levels": {"region"}, "direction": "context_only",
        "href": "/acqua?metric=water_total_precipitation_mm&period={period}&territory={territory}#atlante",
    },
    {
        "id": "risk", "title": "Dissesto", "metric": "hydrogeological_landslide_very_high_hazard_area_km2",
        "label": "Superficie a pericolosità da frana molto elevata", "source": "Osservazione ufficiale ISPRA IdroGEO",
        "kind": "official_observation", "levels": {"municipality", "province", "region"}, "direction": "less_is_better",
        "href": "/dissesto?metric=hydrogeological_landslide_very_high_hazard_area_km2&level={level}&period={period}&territory={territory}#mappa",
    },
    {
        "id": "emissions", "title": "Emissioni", "metric": "emissions_pollutant_002",
        "label": "Ossidi di azoto · automobili su strade urbane (gasolio)", "source": "Osservazione ufficiale ISPRA · SNAP 07010302",
        "kind": "official_observation", "levels": {"province"}, "direction": "less_is_better",
        "href": "/emissioni?view=provincial&period={period}&territory={territory}#mappa", "snap": "07010302",
    },
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def _rows(table: pd.DataFrame, definition: dict, territory_id: str) -> list[dict]:
    rows = table[(table["territory_id"] == territory_id) & (table["metric_id"] == definition["metric"])]
    if "value_state" in rows:
        rows = rows[rows["value_state"].eq("observed")]
    if definition.get("snap"):
        rows = rows[rows["source_dimensions_json"].map(lambda raw: json.loads(raw).get("snap_code") == definition["snap"])]
    result = []
    for row in rows.sort_values(["period_end", "period_start"]).itertuples():
        result.append({"periodStart": row.period_start, "periodEnd": row.period_end, "value": float(row.value_decimal), "unit": row.unit_ucum})
    return result


def _comparison(series: list[dict], direction: str) -> dict:
    if len(series) < 2:
        return {"status": "unavailable", "reason": "single_snapshot"}
    previous, latest = series[-2:]
    if previous["unit"] != latest["unit"] or previous["value"] == 0:
        return {"status": "unavailable", "reason": "incomparable_period"}
    delta = latest["value"] - previous["value"]
    percent = delta / abs(previous["value"]) * 100
    if direction == "less_is_better":
        status = "improving" if delta < 0 else "worsening" if delta > 0 else "stable"
    else:
        status = "changed" if delta else "stable"
    return {"status": "available", "direction": status, "delta": delta, "percent": percent, "from": previous["periodEnd"], "to": latest["periodEnd"]}


def _unavailable(definition: dict, level: str) -> dict:
    reason = "source_not_published_at_this_level" if level not in definition["levels"] else "not_in_published_coverage"
    return {"id": definition["id"], "title": definition["title"], "availability": "unavailable", "reason": reason}


def generate_territory_insights_delivery(
    soil_path: Path, forests_path: Path | None, water_path: Path, dissesto_path: Path, emissions_path: Path,
    territory_root: Path, destination: Path, release_id: str, force: bool = False,
) -> dict:
    root = destination / "territory-insights"
    index_path = root / "index.json"
    inputs = [soil_path, water_path, dissesto_path, emissions_path, forests_path]
    signature = "|".join(sha256_file(path) if path and path.exists() else "absent" for path in inputs)
    if index_path.exists() and not force and json.loads(index_path.read_text()).get("inputSignature") == signature:
        files = sorted(root.rglob("*.json"))
        return {"changed": False, "files": files, "bytes": sum(path.stat().st_size for path in files)}
    tables = {
        "soil": pd.read_parquet(soil_path), "water": pd.read_parquet(water_path), "risk": pd.read_parquet(dissesto_path),
        "emissions": pd.read_parquet(emissions_path), "forests": pd.read_parquet(forests_path) if forests_path and forests_path.exists() else pd.DataFrame(),
    }
    territories = []
    for level in ("municipality", "province", "region"):
        frame = pd.read_parquet(territory_root / "territories" / "reference_year=2025" / f"{level}.parquet")
        territories.extend(frame[["territory_id", "name", "istat_code"]].assign(level=level).to_dict("records"))
    profiles: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for territory in territories:
        level = territory["level"]
        domains = []
        for definition in DOMAIN_DEFINITIONS:
            if level not in definition["levels"]:
                domains.append(_unavailable(definition, level)); continue
            series = _rows(tables[definition["id"]], definition, territory["territory_id"])
            if not series:
                domains.append(_unavailable(definition, level)); continue
            latest = series[-1]
            period = f"{latest['periodStart'][:4]}-{latest['periodEnd'][:4]}"
            domains.append({
                "id": definition["id"], "title": definition["title"], "availability": "available", "label": definition["label"],
                "source": definition["source"], "kind": definition["kind"], "latest": latest, "series": series,
                "comparison": _comparison(series, definition["direction"]),
                "href": definition["href"].format(level=level, period=period, territory=territory["territory_id"]),
            })
        shard = territory["istat_code"][:3] if level == "municipality" else "all"
        profiles[(level, shard)].append({"territoryId": territory["territory_id"], "domains": domains})
    paths = []
    for (level, shard), entries in sorted(profiles.items()):
        logical = f"delivery/territory-insights/{level}/{shard}.json"
        _write(destination / logical.removeprefix("delivery/"), {"schemaVersion": 1, "releaseId": release_id, "algorithmVersion": ALGORITHM_VERSION, "territoryLevel": level, "profiles": entries})
        paths.append(logical)
    _write(index_path, {"schemaVersion": 1, "releaseId": release_id, "algorithmVersion": ALGORITHM_VERSION, "inputSignature": signature, "profileShards": paths})
    files = sorted(root.rglob("*.json"))
    return {"changed": True, "files": files, "bytes": sum(path.stat().st_size for path in files), "profiles": len(territories)}
