from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from .bigbang_raster_poc import METRIC_SPECS
from .registry import load_source
from .tiles import build_pmtiles, is_readable_pmtiles
from .territory_insights_delivery import comparison_for_series

DELIVERY_ALGORITHM_VERSION = "water-delivery-v4"
_PROVINCE_GEOMETRY_REFERENCE = re.compile(
    r"^canonical/territories/reference_year=(?P<year>\d{4})/province\.parquet$"
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def _geometry_reference(value: object) -> tuple[str, int]:
    reference = str(value).split("#", 1)[0]
    match = _PROVINCE_GEOMETRY_REFERENCE.fullmatch(reference)
    if match is None:
        raise ValueError(f"Unexpected BIGBANG provincial geometry reference: {reference}")
    return reference, int(match["year"])


def _province_geometry_paths(
    canonical_root: Path, destination: Path, references: set[str], *, force: bool,
) -> dict[str, str]:
    paths: dict[str, str] = {}
    logical_references: dict[str, str] = {}
    for reference in sorted(references):
        _, year = _geometry_reference(reference)
        source = canonical_root.parent / reference
        if not source.is_file():
            raise ValueError(f"BIGBANG derived map geometry is missing: {reference}")
        logical = f"delivery/water/geometry/istat-province-{year}.pmtiles"
        if logical in logical_references and logical_references[logical] != reference:
            raise ValueError(f"Ambiguous BIGBANG derived geometry output: {logical}")
        logical_references[logical] = reference
        target = destination / logical.removeprefix("delivery/")
        if force or not is_readable_pmtiles(target):
            build_pmtiles(source, target)
        paths[reference] = logical
    return paths


def _official_maps(table: pd.DataFrame, destination: Path, release_id: str) -> tuple[list[str], dict[str, str]]:
    maps: list[str] = []
    map_geometry: dict[str, str] = {}
    geometry = "delivery/soil/geometry/istat-region-2025.pmtiles"
    for (metric, year, level), rows in table[table.territory_level == "region"].groupby(
        ["metric_id", "reference_year", "territory_level"]
    ):
        reference_dates = rows["territory_version_id"].str.rsplit("@", n=1).str[-1].unique().tolist()
        if reference_dates != ["2025-01-01"]:
            raise ValueError(f"Unexpected BIGBANG territory reference for {metric}/{year}: {reference_dates}")
        logical = f"delivery/water/maps/{metric}/{year}/{level}.json"
        _write(destination / logical.removeprefix("delivery/"), {
            "schemaVersion": 1, "releaseId": release_id, "theme": "water", "kind": "official_model_map_values",
            "metricId": metric, "unit": "mm", "periodStart": f"{year}-01-01", "periodEnd": f"{year}-12-31",
            "territoryLevel": level, "territoryReferenceDate": reference_dates[0],
            "columns": ["territoryId", "value"],
            "values": [[row.territory_id, float(row.value_decimal)] for row in rows.itertuples()],
            "provenanceRef": "delivery/water/provenance.json",
        })
        maps.append(logical)
        map_geometry[logical] = geometry
    return maps, map_geometry


def _derived_maps(
    table: pd.DataFrame, destination: Path, release_id: str, geometry_paths: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    maps: list[str] = []
    map_geometry: dict[str, str] = {}
    required = {
        "derived_metric_id", "reference_year", "territory_id", "territory_version_id", "territory_level",
        "value_decimal", "unit_ucum", "territory_geometry_reference", "algorithm_version", "official_status",
    }
    if missing := required - set(table.columns):
        raise ValueError(f"BIGBANG historical derived delivery lacks fields: {sorted(missing)}")
    if set(table["territory_level"].astype(str)) != {"province"}:
        raise ValueError("BIGBANG historical derived delivery mixes non-provincial territories")
    if set(table["official_status"].astype(str)) != {"derived_by_stato_italia"}:
        raise ValueError("BIGBANG historical derived delivery mixes official observations")
    expected_metrics = {spec.derived_metric_id for spec in METRIC_SPECS.values()}
    if set(table["derived_metric_id"].astype(str)) != expected_metrics:
        raise ValueError("BIGBANG historical derived delivery lacks an expected metric")
    for (metric, year, level), rows in table.groupby(["derived_metric_id", "reference_year", "territory_level"]):
        references = {_geometry_reference(value)[0] for value in rows["territory_geometry_reference"]}
        if len(references) != 1:
            raise ValueError(f"Ambiguous BIGBANG derived map geometry for {metric}/{year}")
        reference = references.pop()
        geometry = geometry_paths.get(reference)
        if geometry is None:
            raise ValueError(f"Missing BIGBANG derived PMTiles geometry for {metric}/{year}")
        geometry_year = _geometry_reference(reference)[1]
        versions = rows["algorithm_version"].astype(str).unique().tolist()
        if len(versions) != 1:
            raise ValueError(f"Ambiguous BIGBANG derived algorithm for {metric}/{year}")
        units = rows["unit_ucum"].astype(str).unique().tolist()
        if units != ["mm"]:
            raise ValueError(f"Unexpected BIGBANG derived unit for {metric}/{year}: {units}")
        logical = f"delivery/water/maps/{metric}/{year}/{level}.json"
        _write(destination / logical.removeprefix("delivery/"), {
            "schemaVersion": 1, "releaseId": release_id, "theme": "water", "kind": "derived_metric_map_values",
            "metricId": metric, "derivedMetricId": metric, "officialStatus": "derived_by_stato_italia",
            "algorithmVersion": versions[0], "unit": units[0], "periodStart": f"{year}-01-01", "periodEnd": f"{year}-12-31",
            "territoryLevel": level, "territoryReferenceDate": f"{geometry_year}-01-01",
            "territoryGeometryReference": reference, "columns": ["territoryId", "value"],
            "values": [[row.territory_id, float(row.value_decimal)] for row in rows.itertuples()],
            "provenanceRef": "delivery/water/provenance.json",
        })
        maps.append(logical)
        map_geometry[logical] = geometry
    return maps, map_geometry


def _profiles(table: pd.DataFrame, destination: Path, release_id: str, *, derived: bool) -> list[str]:
    profiles: list[str] = []
    metric_column = "derived_metric_id" if derived else "metric_id"
    for territory_id, rows in table.groupby("territory_id"):
        latest = rows.sort_values("reference_year").groupby(metric_column).tail(1)
        territory = latest.iloc[0]
        level = str(territory.territory_level)
        logical = f"delivery/water/profiles/{level}/{territory_id.rsplit(':', 1)[-1]}.json"
        historical_series = []
        for metric, series in rows.groupby(metric_column):
            sorted_series = series.sort_values("reference_year")
            points = []
            comparison_points = []
            for row in sorted_series.itertuples():
                year = int(row.reference_year)
                geometry_reference = _geometry_reference(row.territory_geometry_reference)[0] if derived else f"canonical/territories/reference_year={str(row.territory_version_id).rsplit('@', 1)[-1][:4]}/{row.territory_level}.parquet"
                methodology = "|".join(
                    str(value) for value in (
                        getattr(row, "methodology_version", None), getattr(row, "algorithm_version", None),
                    ) if value is not None and str(value) != "nan"
                ) or None
                points.append({
                    "referenceYear": year, "value": float(row.value_decimal),
                    "territoryGeometryReference": geometry_reference,
                    "territoryVersionId": row.territory_version_id,
                    **({"methodologyReference": methodology} if methodology else {}),
                })
                comparison_points.append({
                    "metricId": getattr(row, metric_column), "periodStart": f"{year}-01-01", "periodEnd": f"{year}-12-31",
                    "value": float(row.value_decimal), "unit": row.unit_ucum,
                    "geometryReference": geometry_reference,
                    **({"methodologyReference": methodology} if methodology else {}),
                })
            historical_series.append({
                "metricId": metric,
                "values": [[int(row.reference_year), float(row.value_decimal)] for row in sorted_series.itertuples()],
                "points": points,
                "comparison": comparison_for_series(comparison_points, "context_only", "same_metric_unit_method_geometry"),
            })
        payload = {
            "schemaVersion": 1, "releaseId": release_id, "theme": "water",
            "territory": {"territoryId": territory_id, "territoryVersionId": territory.territory_version_id, "level": level},
            "latestObservations": [{"metricId": getattr(row, metric_column), "periodEnd": f"{row.reference_year}-12-31" if derived else row.period_end, "value": float(row.value_decimal), "unit": row.unit_ucum} for row in latest.itertuples()],
            "historicalSeries": historical_series,
            "provenanceRef": "delivery/water/provenance.json",
        }
        if derived:
            references = {_geometry_reference(value)[0] for value in rows["territory_geometry_reference"]}
            if not references:
                raise ValueError(f"Missing BIGBANG derived profile geometry for {territory_id}")
            payload |= {
                "kind": "derived_metric_profile", "officialStatus": "derived_by_stato_italia",
                "territoryGeometryReferences": sorted(references),
            }
        _write(destination / logical.removeprefix("delivery/"), payload)
        profiles.append(logical)
    return profiles


def generate_water_delivery(
    canonical_path: Path, derived_path: Path, canonical_root: Path, destination: Path, release_id: str,
    force: bool = False,
) -> dict:
    index_path = destination / "water" / "index.json"
    if index_path.exists() and not force:
        previous = json.loads(index_path.read_text())
        if previous.get("algorithmVersion") == DELIVERY_ALGORITHM_VERSION:
            files = sorted(path for path in (destination / "water").rglob("*.json"))
            files.extend(sorted((destination / "water" / "geometry").glob("*.pmtiles")))
            return {"changed": False, "files": files}
    for generated in (destination / "water").rglob("*.json"):
        generated.unlink()
    official = pd.read_parquet(canonical_path)
    derived = pd.read_parquet(derived_path)
    source = load_source("ispra-bigbang")
    root = destination / "water"
    _write(root / "provenance.json", {
        "schemaVersion": 1, "releaseId": release_id, "theme": "water", "dataset": source,
        "officialVsDerived": {
            "official_observation": "Stima modello BIGBANG pubblicata da ISPRA; non misura diretta.",
            "derived_metric": "Elaborazione Stato d'Italia su raster ISPRA BIGBANG 10.0; media zonale pesata per area.",
        },
    })
    official_maps, official_geometry = _official_maps(official, destination, release_id)
    references = {_geometry_reference(value)[0] for value in derived["territory_geometry_reference"]}
    province_geometry = _province_geometry_paths(canonical_root, destination, references, force=force)
    derived_maps, derived_geometry = _derived_maps(derived, destination, release_id, province_geometry)
    profiles = _profiles(official, destination, release_id, derived=False)
    profiles.extend(_profiles(derived, destination, release_id, derived=True))
    maps = official_maps + derived_maps
    map_geometry = official_geometry | derived_geometry
    _write(index_path, {
        "schemaVersion": 1, "releaseId": release_id, "theme": "water", "algorithmVersion": DELIVERY_ALGORITHM_VERSION,
        "provenance": "delivery/water/provenance.json", "maps": maps, "profiles": profiles,
        "geometry": sorted(set(map_geometry.values())), "mapGeometry": map_geometry,
    })
    files = sorted(root.rglob("*.json")) + sorted((root / "geometry").glob("*.pmtiles"))
    return {"changed": True, "files": files, "maps": len(maps), "profiles": len(profiles), "bytes": sum(path.stat().st_size for path in files)}
