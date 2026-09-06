from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd

from .common import sha256_file


ALGORITHM_VERSION = "territory-profile-insights-v2"

_DEFINITIONS = {
    "soil": {
        "title": "Suolo", "metric": "soil_net_consumption_hectares", "label": "Incremento netto di suolo consumato",
        "source": "Osservazione ufficiale ISPRA / SNPA", "kind": "official_observation", "levels": {"municipality", "province", "region"},
        "direction": "less_is_better", "comparison": "same_metric_unit",
        "href": "/suolo?metric=soil_net_consumption_hectares&level={level}&period={period}&territory={territory}#mappa",
    },
    "forests": {
        "title": "Foreste", "metric": "tree_cover_mean", "label": "Copertura arborea media",
        "source": "Elaborazione zonale Copernicus", "kind": "derived_metric", "levels": {"municipality", "province", "region"},
        "direction": "context_only", "comparison": "same_metric_unit_method_geometry",
        "href": "/foreste?metric=tree_cover_mean&level={level}&period={period}&territory={territory}#mappa",
    },
    "water": {
        "title": "Acqua", "label": "Precipitazione totale", "levels": {"province", "region"}, "direction": "context_only",
        "comparison": "same_metric_unit_method_geometry",
    },
    "risk": {
        "title": "Dissesto", "metric": "hydrogeological_landslide_very_high_hazard_area_km2",
        "label": "Superficie a pericolosità da frana molto elevata", "source": "Osservazione ufficiale ISPRA IdroGEO",
        "kind": "official_observation", "levels": {"municipality", "province", "region"}, "direction": "less_is_better",
        "comparison": "not_supported",
        "href": "/dissesto?metric=hydrogeological_landslide_very_high_hazard_area_km2&level={level}&period={period}&territory={territory}#mappa",
    },
    "emissions": {
        "title": "Emissioni", "metric": "emissions_pollutant_002", "label": "Ossidi di azoto · automobili su strade urbane (gasolio)",
        "source": "Osservazione ufficiale ISPRA · SNAP 07010302", "kind": "official_observation", "levels": {"province"},
        "direction": "less_is_better", "comparison": "not_supported", "snap": "07010302",
        "href": "/emissioni?view=provincial&period={period}&territory={territory}#mappa",
    },
}

_RISK_SNAPSHOTS = (
    ("Alluvioni", "hydrogeological_flood_high_hazard_area_km2", "Superficie a pericolosità idraulica elevata"),
    ("Alluvioni", "hydrogeological_flood_high_hazard_population", "Popolazione in area a pericolosità idraulica elevata"),
    ("Frane", "hydrogeological_landslide_very_high_hazard_area_km2", "Superficie a pericolosità da frana molto elevata"),
    ("Frane", "hydrogeological_landslide_very_high_hazard_population", "Popolazione in area a pericolosità da frana molto elevata"),
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def _geometry_reference(row: pd.Series | dict) -> str | None:
    value = row.get("territory_geometry_reference")
    if value is not None and not pd.isna(value):
        return str(value).split("#", 1)[0]
    version = row.get("territory_version_id")
    level = row.get("territory_level")
    if version is None or level is None or pd.isna(version) or pd.isna(level):
        return None
    return f"canonical/territories/reference_year={str(version).rsplit('@', 1)[-1][:4]}/{level}.parquet"


def _methodology_reference(row: pd.Series | dict) -> str | None:
    values = []
    for key in ("methodology_version", "algorithm_version"):
        value = row.get(key)
        if value is not None and not pd.isna(value):
            values.append(str(value))
    return "|".join(values) or None


def _point(row: pd.Series | dict, *, metric_id: str | None = None) -> dict:
    point = {
        "metricId": metric_id or str(row["metric_id"]), "periodStart": str(row["period_start"]),
        "periodEnd": str(row["period_end"]), "value": float(row["value_decimal"]), "unit": str(row["unit_ucum"]),
    }
    if geometry := _geometry_reference(row):
        point["geometryReference"] = geometry
    if methodology := _methodology_reference(row):
        point["methodologyReference"] = methodology
    return point


TableIndex = dict[tuple[str, str], pd.DataFrame]


def _index_table(table: pd.DataFrame) -> TableIndex:
    if table.empty:
        return {}
    return {
        (str(territory_id), str(metric)): rows.sort_values(["period_end", "period_start"])
        for (territory_id, metric), rows in table.groupby(["territory_id", "metric_id"], sort=False)
    }


def _load_index(path: Path, metrics: set[str], *, snap: str | None = None) -> TableIndex:
    table = pd.read_parquet(path)
    table = table[table["metric_id"].isin(metrics)]
    if snap:
        table = table[table["source_dimensions_json"].map(lambda raw: json.loads(raw).get("snap_code") == snap)]
    return _index_table(table)


def _rows(table: TableIndex, territory_id: str, metric: str, snap: str | None = None) -> list[dict]:
    rows = table.get((territory_id, metric))
    if rows is None:
        return []
    rows = rows.copy()
    if "value_state" in rows:
        rows = rows[rows["value_state"].eq("observed")]
    if snap:
        rows = rows[rows["source_dimensions_json"].map(lambda raw: json.loads(raw).get("snap_code") == snap)]
    return [_point(row) for _, row in rows.sort_values(["period_end", "period_start"]).iterrows()]


def comparison_for_series(series: list[dict], direction: str, policy: str) -> dict:
    """Return a comparison only when every declared prerequisite is evidenced."""
    if len(series) < 2:
        return {"status": "unavailable", "reason": "single_snapshot"}
    if policy == "not_supported":
        return {"status": "unavailable", "reason": "comparison_not_supported"}
    previous, latest = series[-2:]
    if previous["metricId"] != latest["metricId"]:
        return {"status": "unavailable", "reason": "different_metric"}
    if previous["unit"] != latest["unit"]:
        return {"status": "unavailable", "reason": "unit_changed"}
    if "method" in policy:
        if not previous.get("methodologyReference") or not latest.get("methodologyReference") or previous["methodologyReference"] != latest["methodologyReference"]:
            return {"status": "unavailable", "reason": "methodology_changed"}
    if "geometry" in policy:
        if not previous.get("geometryReference") or not latest.get("geometryReference") or previous["geometryReference"] != latest["geometryReference"]:
            return {"status": "unavailable", "reason": "geometry_changed"}
    if previous["value"] == 0:
        return {"status": "unavailable", "reason": "missing_previous_period"}
    delta = latest["value"] - previous["value"]
    if direction == "less_is_better":
        status = "improving" if delta < 0 else "worsening" if delta > 0 else "stable"
    else:
        status = "changed" if delta else "stable"
    return {"status": "available", "direction": status, "delta": delta, "percent": delta / abs(previous["value"]) * 100, "from": previous["periodEnd"], "to": latest["periodEnd"]}


def _unavailable(domain: str, level: str) -> dict:
    definition = _DEFINITIONS[domain]
    reason = "source_not_published_at_this_level" if level not in definition["levels"] else "not_in_published_coverage"
    return {"id": domain, "title": definition["title"], "availability": "unavailable", "reason": reason}


def _domain(domain: str, table: TableIndex, territory_id: str, level: str, *, metric: str | None = None, kind: str | None = None, source: str | None = None) -> dict:
    definition = _DEFINITIONS[domain]
    if level not in definition["levels"]:
        return _unavailable(domain, level)
    series = _rows(table, territory_id, metric or definition["metric"], definition.get("snap"))
    if not series:
        return _unavailable(domain, level)
    latest = series[-1]
    period = f"{latest['periodStart'][:4]}-{latest['periodEnd'][:4]}"
    return {
        "id": domain, "title": definition["title"], "availability": "available", "label": definition["label"],
        "source": source or definition["source"], "kind": kind or definition["kind"], "latest": latest, "series": series,
        "comparison": comparison_for_series(series, definition["direction"], definition["comparison"]),
        "href": definition["href"].format(level=level, period=period, territory=territory_id),
    }


def _forest_domain(zonal: TableIndex, infc: pd.DataFrame, territory_id: str, level: str) -> dict:
    result = _domain("forests", zonal, territory_id, level)
    if result["availability"] == "unavailable":
        return result
    groups = [{"id": "copernicus", "title": "Copernicus", "kind": "derived_metric", "source": "Elaborazione zonale Copernicus", "metrics": [{"label": result["label"], "series": result["series"]}]}]
    official_rows = [] if infc.empty else infc[infc["territory_id"] == territory_id]
    if not isinstance(official_rows, list) and not official_rows.empty:
        metrics = []
        for metric, rows in official_rows.groupby("metric_id", sort=True):
            points = [_point(row) for _, row in rows.sort_values(["period_end", "period_start"]).iterrows()]
            metrics.append({"label": str(metric), "series": points})
        groups.append({"id": "infc", "title": "INFC", "kind": "official_observation", "source": "Statistiche ufficiali INFC2015", "metrics": metrics})
    result["groups"] = groups
    return result


def _risk_domain(table: TableIndex, territory_id: str, level: str) -> dict:
    result = _domain("risk", table, territory_id, level)
    if result["availability"] == "unavailable":
        return result
    snapshots = []
    for family, metric, label in _RISK_SNAPSHOTS:
        series = _rows(table, territory_id, metric)
        if series:
            snapshots.append({"family": family, "metricId": metric, "label": label, "latest": series[-1], "series": series})
    result["snapshots"] = snapshots
    return result


def _water_domain(official: TableIndex, derived: pd.DataFrame, territory_id: str, level: str) -> dict:
    definition = _DEFINITIONS["water"]
    if level not in definition["levels"]:
        return _unavailable("water", level)
    is_derived = level == "province"
    metric = "water_total_precipitation_mm_zonal_mean" if is_derived else "water_total_precipitation_mm"
    if is_derived and not derived.empty:
        table = _index_table(derived.copy().assign(
            metric_id=lambda frame: frame["derived_metric_id"],
            period_start=lambda frame: frame["reference_year"].map(lambda year: f"{int(year)}-01-01"),
            period_end=lambda frame: frame["reference_year"].map(lambda year: f"{int(year)}-12-31"),
            methodology_version=lambda frame: frame["source_dataset_version"],
        ))
    else:
        table = {} if is_derived else official
    series = _rows(table, territory_id, metric)
    if not series:
        return _unavailable("water", level)
    latest = series[-1]
    period = f"{latest['periodStart'][:4]}-{latest['periodEnd'][:4]}"
    return {
        "id": "water", "title": "Acqua", "availability": "available", "label": definition["label"],
        "source": "Elaborazione Stato d’Italia su raster ISPRA BIGBANG 10.0" if is_derived else "Stima modellistica ufficiale ISPRA BIGBANG 10.0",
        "kind": "derived_metric" if is_derived else "official_model", "latest": latest, "series": series,
        "comparison": comparison_for_series(series, definition["direction"], definition["comparison"]),
        "href": f"/acqua?level={level}&metric={metric}&period={period}&territory={territory_id}#atlante",
    }


def generate_territory_insights_delivery(
    soil_path: Path, forests_path: Path | None, water_path: Path, dissesto_path: Path, emissions_path: Path,
    territory_root: Path, destination: Path, release_id: str, force: bool = False, *,
    derived_water_path: Path | None = None, infc_path: Path | None = None,
) -> dict:
    root = destination / "territory-insights"
    index_path = root / "index.json"
    inputs = [soil_path, forests_path, water_path, dissesto_path, emissions_path, derived_water_path, infc_path]
    signature = "|".join(sha256_file(path) if path and path.exists() else "absent" for path in inputs)
    if index_path.exists() and not force and json.loads(index_path.read_text()).get("inputSignature") == signature:
        files = sorted(root.rglob("*.json"))
        return {"changed": False, "files": files, "bytes": sum(path.stat().st_size for path in files)}
    if root.exists():
        shutil.rmtree(root)
    tables = {
        "soil": _load_index(soil_path, {"soil_net_consumption_hectares"}),
        "water": _load_index(water_path, {"water_total_precipitation_mm"}),
        "risk": _load_index(dissesto_path, {item[1] for item in _RISK_SNAPSHOTS}),
        "emissions": _load_index(emissions_path, {"emissions_pollutant_002"}, snap="07010302"),
        "forests": _load_index(forests_path, {"tree_cover_mean"}) if forests_path and forests_path.exists() else {},
        "water_derived": pd.read_parquet(derived_water_path) if derived_water_path and derived_water_path.exists() else pd.DataFrame(),
        "infc": pd.read_parquet(infc_path) if infc_path and infc_path.exists() else pd.DataFrame(),
    }
    territories = []
    for level in ("municipality", "province", "region"):
        frame = pd.read_parquet(territory_root / "territories" / "reference_year=2025" / f"{level}.parquet")
        territories.extend(frame[["territory_id", "name", "istat_code"]].assign(level=level).to_dict("records"))
    profiles: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for territory in territories:
        level, territory_id = territory["level"], territory["territory_id"]
        domains = [
            _domain("soil", tables["soil"], territory_id, level),
            _water_domain(tables["water"], tables["water_derived"], territory_id, level),
            _forest_domain(tables["forests"], tables["infc"], territory_id, level),
            _risk_domain(tables["risk"], territory_id, level),
            _domain("emissions", tables["emissions"], territory_id, level),
        ]
        shard = territory["istat_code"][:3] if level == "municipality" else "all"
        profiles[(level, shard)].append({"territoryId": territory_id, "domains": domains})
    paths = []
    for (level, shard), entries in sorted(profiles.items()):
        logical = f"delivery/territory-insights/{level}/{shard}.json"
        _write(destination / logical.removeprefix("delivery/"), {"schemaVersion": 1, "releaseId": release_id, "algorithmVersion": ALGORITHM_VERSION, "territoryLevel": level, "profiles": entries})
        paths.append(logical)
    _write(index_path, {"schemaVersion": 1, "releaseId": release_id, "algorithmVersion": ALGORITHM_VERSION, "inputSignature": signature, "profileShards": paths})
    files = sorted(root.rglob("*.json"))
    return {"changed": True, "files": files, "bytes": sum(path.stat().st_size for path in files), "profiles": len(territories)}
