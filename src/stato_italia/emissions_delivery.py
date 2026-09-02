from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .registry import load_source

DELIVERY_SCHEMA_VERSION = 1
DELIVERY_ALGORITHM_VERSION = "emissions-explorer-v2"
MAP_DEFAULT_METRIC_ID = "emissions_pollutant_002"
MAP_DEFAULT_SNAP_CODE = "07010302"
MAP_REFERENCE_YEARS = (2019, 2023)
GHG_LABELS = {
    "emissions_ghg_co2e": "CO2 equivalente", "emissions_ghg_co2": "CO2", "emissions_ghg_ch4": "CH4",
    "emissions_ghg_n2o": "N2O", "emissions_ghg_f_gases": "gas fluorurati", "emissions_ghg_f_gases_co2e": "gas fluorurati in CO2 equivalente",
}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def _dimensions(value: str) -> dict:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Unexpected emissions source dimensions contract")
    return parsed


def _observed_with_dimensions(table: pd.DataFrame) -> pd.DataFrame:
    observed = table.loc[table["value_state"] == "observed"].copy()
    if observed.empty:
        raise ValueError("Emissions canonical table has no observed values")
    observed["_dimensions"] = observed["source_dimensions_json"].map(_dimensions)
    return observed


def _national_series(table: pd.DataFrame, dataset: str) -> list[dict]:
    observed = _observed_with_dimensions(table)
    if dataset == "ghg":
        observed["dimension_code"] = observed["_dimensions"].map(lambda value: value["inventory_category"])
        observed["dimension_label"] = observed["dimension_code"]
        observed["metric_label"] = observed["metric_id"].map(GHG_LABELS)
        if observed["metric_label"].isna().any():
            raise ValueError("Unexpected ISPRA GHG metric identifier")
    elif dataset == "nfr":
        observed["dimension_code"] = observed["_dimensions"].map(lambda value: value["nfr_code"])
        observed["dimension_label"] = observed["_dimensions"].map(lambda value: value["nfr_label"])
        observed["metric_label"] = observed["_dimensions"].map(lambda value: value["pollutant_label"])
    else:
        raise ValueError(f"Unsupported national emissions dataset: {dataset}")
    observed["source_unit"] = observed["_dimensions"].map(lambda value: value["source_unit"])
    result: list[dict] = []
    columns = ["metric_id", "metric_label", "dimension_code", "dimension_label", "source_unit", "unit_ucum"]
    for key, rows in observed.groupby(columns, sort=True, dropna=False):
        metric_id, metric_label, dimension_code, dimension_label, source_unit, unit = key
        ordered = rows.sort_values("reference_year")
        if ordered["reference_year"].duplicated().any():
            raise ValueError(f"Duplicate official national emissions observation: {dataset} {metric_id} {dimension_code}")
        result.append({
            "id": f"{metric_id}:{dimension_code}", "metricId": metric_id, "metricLabel": metric_label,
            "dimensionCode": dimension_code, "dimensionLabel": dimension_label, "sourceUnit": source_unit, "unit": unit,
            "values": [[int(row.reference_year), float(row.value_decimal)] for row in ordered.itertuples()],
        })
    return result


def _write_provincial_maps(table: pd.DataFrame, destination: Path, release_id: str) -> list[dict]:
    observed = _observed_with_dimensions(table)
    for key in ("pollutant_code", "pollutant_label", "snap_code", "snap_label"):
        observed[key] = observed["_dimensions"].map(lambda value, dimension=key: value[dimension])
    catalog: dict[tuple[str, str], dict] = {}
    for (metric_id, reference_year), metric_rows in observed.groupby(["metric_id", "reference_year"], sort=True):
        map_path = f"delivery/emissions/maps/{metric_id}/{reference_year}/province.json"
        snapshots: list[dict] = []
        for key, rows in metric_rows.groupby(["pollutant_code", "pollutant_label", "snap_code", "snap_label", "unit_ucum"], sort=True, dropna=False):
            pollutant_code, pollutant_label, snap_code, snap_label, unit = key
            if rows["territory_id"].duplicated().any():
                raise ValueError(f"Duplicate ISPRA provincial emissions observation: {metric_id} {snap_code} {reference_year}")
            snapshots.append({"sourceDimensions": {"pollutant_code": pollutant_code, "pollutant_label": pollutant_label, "snap_code": snap_code, "snap_label": snap_label}, "unit": unit, "values": [[row.territory_id, float(row.value_decimal)] for row in rows.sort_values("territory_id").itertuples()]})
            entry = catalog.setdefault((metric_id, snap_code), {"id": f"{metric_id}:{snap_code}", "metricId": metric_id, "pollutantCode": pollutant_code, "pollutantLabel": pollutant_label, "snapCode": snap_code, "snapLabel": snap_label, "unit": unit, "mapPaths": {}})
            if entry["pollutantLabel"] != pollutant_label or entry["snapLabel"] != snap_label or entry["unit"] != unit:
                raise ValueError(f"Inconsistent ISPRA provincial map catalog entry: {metric_id} {snap_code}")
            entry["mapPaths"][str(reference_year)] = map_path
        _write(destination / map_path.removeprefix("delivery/"), {"schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "emissions", "kind": "official_snapshot_map_collection", "metricId": metric_id, "periodStart": f"{reference_year}-01-01", "periodEnd": f"{reference_year}-12-31", "territoryLevel": "province", "territoryReferenceDate": f"{reference_year}-01-01", "snapshots": snapshots, "provenanceRef": "delivery/emissions/provenance.json"})
    return sorted(catalog.values(), key=lambda item: (item["pollutantLabel"], item["snapLabel"], item["snapCode"]))


def generate_emissions_delivery(
    greenhouse_gases_path: Path, air_pollutants_nfr_path: Path, provincial_path: Path,
    province_geometry_paths: dict[int, Path], destination: Path, release_id: str, force: bool = False,
) -> dict:
    index_path = destination / "emissions" / "index.json"
    if index_path.exists() and not force:
        previous = json.loads(index_path.read_text())
        if previous.get("algorithmVersion") == DELIVERY_ALGORITHM_VERSION:
            files = sorted(path for path in (destination / "emissions").rglob("*.json"))
            return {"changed": False, "skipped": True, "files": files, "bytes": sum(path.stat().st_size for path in files)}
    ghg, nfr, provincial = (pd.read_parquet(path) for path in (greenhouse_gases_path, air_pollutants_nfr_path, provincial_path))
    required = {"metric_id", "reference_year", "source_dimensions_json", "value_decimal", "value_state", "unit_ucum"}
    for name, table in (("GHG", ghg), ("NFR", nfr), ("provincial", provincial)):
        missing = required - set(table.columns)
        if missing:
            raise ValueError(f"{name} emissions canonical contract missing columns: {sorted(missing)}")
    if set(province_geometry_paths) != set(MAP_REFERENCE_YEARS) or not all(path.exists() for path in province_geometry_paths.values()):
        raise ValueError("Missing matching ISTAT province PMTiles geometry required for emissions delivery")
    root = destination / "emissions"
    for generated in root.rglob("*.json"):
        generated.unlink()
    _write(root / "provenance.json", {"schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "emissions", "datasets": {"greenhouseGases": load_source("ispra-emissions-ghg-2026"), "airPollutantsNfr": load_source("ispra-emissions-nfr-2026"), "provincial": load_source("ispra-emissions-provincial-2026")}, "officialVsDerived": {"national_territorial_inventory": "Inventario nazionale ISPRA: non emissione dichiarata da singolo stabilimento e non concentrazione misurata nell'aria.", "provincial_disaggregation": "Stima ISPRA top-down per provincia e attività SNAP; non viene trasformata in dato comunale.", "derived_metric": "Questo delivery non somma attività SNAP e non pubblica ranking o percentili."}})
    ghg_path = "delivery/emissions/national/greenhouse-gases.json"
    nfr_path = "delivery/emissions/national/air-pollutants-nfr.json"
    provincial_catalog_path = "delivery/emissions/provincial/catalog.json"
    ghg_series, nfr_series = _national_series(ghg, "ghg"), _national_series(nfr, "nfr")
    provincial_catalog = _write_provincial_maps(provincial, destination, release_id)
    map_paths = sorted({path for item in provincial_catalog for path in item["mapPaths"].values()})
    _write(destination / ghg_path.removeprefix("delivery/"), {"schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "kind": "official_national_series", "dataset": "greenhouse_gases", "series": ghg_series, "provenanceRef": "delivery/emissions/provenance.json"})
    _write(destination / nfr_path.removeprefix("delivery/"), {"schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "kind": "official_national_series", "dataset": "air_pollutants_nfr", "series": nfr_series, "provenanceRef": "delivery/emissions/provenance.json"})
    _write(destination / provincial_catalog_path.removeprefix("delivery/"), {"schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "kind": "official_provincial_map_catalog", "territoryLevel": "province", "combinations": provincial_catalog, "provenanceRef": "delivery/emissions/provenance.json"})
    default = next((item for item in provincial_catalog if item["metricId"] == MAP_DEFAULT_METRIC_ID and item["snapCode"] == MAP_DEFAULT_SNAP_CODE), None)
    total = next((item for item in ghg_series if item["metricId"] == "emissions_ghg_co2e" and item["dimensionCode"] == "Total (net emissions) (4)"), None)
    if default is None or total is None:
        raise ValueError("Required default emissions explorer series is absent from source")
    _write(root / "overview.json", {"schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "emissions", "greenhouseGases": {"label": "Gas serra nazionali", "coverage": "Italia · 1990–2024", "unit": "kt CO2 equivalenti", "seriesLabel": "Totale emissioni nette ufficiale", "series": total["values"], "metrics": ["CO2 equivalente", "CO2", "CH4", "N2O", "gas fluorurati"]}, "airPollutantsNfr": {"label": "Inquinanti atmosferici nazionali", "coverage": "Italia · 1990–2024", "metrics": int(nfr["metric_id"].nunique()), "sourceDimensions": ["settore NFR", "inquinante", "unità fonte"]}, "provincialDisaggregation": {"label": "Disaggregazione provinciale", "coverage": "Province · 2019 e 2023", "metrics": int(provincial["metric_id"].nunique()), "sourceDimensions": ["provincia", "attività SNAP", "inquinante"]}, "map": {"metricId": default["metricId"], "snapCode": default["snapCode"], "label": f"{default['pollutantLabel']} · {default['snapLabel']}", "detail": "Osservazione ISPRA per una singola combinazione inquinante e attività SNAP. Non è il totale del traffico né la concentrazione dell'aria.", "coverage": "Province · 2019 e 2023", "periods": [int(year) for year in default["mapPaths"]], "territoryLevel": "province"}, "provenanceRef": "delivery/emissions/provenance.json"})
    _write(index_path, {"schemaVersion": DELIVERY_SCHEMA_VERSION, "releaseId": release_id, "theme": "emissions", "algorithmVersion": DELIVERY_ALGORITHM_VERSION, "overview": "delivery/emissions/overview.json", "provenance": "delivery/emissions/provenance.json", "national": {"greenhouseGases": ghg_path, "airPollutantsNfr": nfr_path}, "provincialCatalog": provincial_catalog_path, "maps": map_paths, "geometry": [f"delivery/emissions/geometry/{province_geometry_paths[year].name}" for year in MAP_REFERENCE_YEARS]})
    files = sorted(path for path in root.rglob("*.json"))
    return {"changed": True, "files": files, "bytes": sum(path.stat().st_size for path in files)}
