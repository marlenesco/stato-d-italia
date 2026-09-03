from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import rasterio
from pyproj import CRS, Transformer
from rasterio.features import geometry_window
from rasterio.windows import Window
from shapely import wkb
from shapely.geometry import box, mapping
from shapely.ops import transform

from .common import json_dump, sha256_file, stable_id
from .registry import load_source

SOURCE = load_source("ispra-bigbang")
DEFAULT_CONTRACT = SOURCE["raster_poc"]
ALGORITHM_VERSION = "bigbang-tp-zonal-area-weighted-v1"
DERIVED_METRIC_ID = "water_total_precipitation_mm_zonal_mean"
OFFICIAL_METRIC_ID = "water_total_precipitation_mm"
REFERENCE_YEAR = 2025


@dataclass(frozen=True)
class RasterMetadata:
    archive_sha256: str
    archive_bytes: int
    archive_member_count: int
    archive_years: tuple[int, int]
    raster_sha256: str
    raster_bytes: int
    raster_member: str
    projection_member: str
    driver: str
    crs: str
    width: int
    height: int
    cell_size_x_m: float
    cell_size_y_m: float
    nodata: float
    unit_ucum: str
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class ZonalResult:
    value_decimal: float | None
    coverage_ratio: float
    valid_intersection_area_m2: float
    intersecting_cell_count: int
    valid_cell_count: int
    quality_flags: tuple[str, ...]


def _expected_members(contract: dict) -> set[str]:
    first = int(contract["archive_first_year"])
    last = int(contract["archive_last_year"])
    return {
        f"tp_{year}_yyc.{suffix}"
        for year in range(first, last + 1)
        for suffix in ("asc", "prj")
    }


def validate_archive_structure(archive: Path, contract: dict = DEFAULT_CONTRACT) -> None:
    if sha256_file(archive) != contract["archive_sha256"]:
        raise ValueError("Unexpected BIGBANG TP archive SHA-256")
    if archive.stat().st_size != int(contract["archive_bytes"]):
        raise ValueError("Unexpected BIGBANG TP archive byte size")
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError("BIGBANG TP archive contains duplicate member names")
        expected = _expected_members(contract)
        if set(names) != expected:
            raise ValueError(
                "Unexpected BIGBANG TP archive structure: "
                f"missing={sorted(expected - set(names))}, unexpected={sorted(set(names) - expected)}"
            )
        raster_member = contract["raster_member"]
        projection_member = contract["projection_member"]
        if names.count(raster_member) != 1 or names.count(projection_member) != 1:
            raise ValueError("BIGBANG TP 2025 raster or projection is not unique")
        raster_info = source.getinfo(raster_member)
        if raster_info.file_size != int(contract["raster_bytes"]):
            raise ValueError("Unexpected BIGBANG TP 2025 raster byte size")


def extract_raster(archive: Path, destination: Path, contract: dict = DEFAULT_CONTRACT) -> Path:
    validate_archive_structure(archive, contract)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for member in (contract["raster_member"], contract["projection_member"]):
            target = destination / Path(member).name
            with source.open(member) as incoming, target.open("wb") as output:
                shutil.copyfileobj(incoming, output)
    raster = destination / Path(contract["raster_member"]).name
    if sha256_file(raster) != contract["raster_sha256"]:
        raise ValueError("Unexpected BIGBANG TP 2025 raster SHA-256")
    return raster


def inspect_raster(
    raster: Path,
    archive: Path,
    contract: dict = DEFAULT_CONTRACT,
) -> RasterMetadata:
    with rasterio.open(raster) as dataset:
        if dataset.crs is None:
            raise ValueError("BIGBANG TP raster lacks CRS")
        if dataset.transform.b != 0 or dataset.transform.d != 0:
            raise ValueError("Rotated BIGBANG TP grids are not supported")
        actual = {
            "driver": dataset.driver,
            "crs": dataset.crs.to_string(),
            "width": dataset.width,
            "height": dataset.height,
            "cell_size_m": abs(float(dataset.transform.a)),
            "cell_size_y_m": abs(float(dataset.transform.e)),
            "nodata": dataset.nodata,
            "bounds": tuple(float(value) for value in dataset.bounds),
            "count": dataset.count,
        }
    expected_bounds = tuple(float(value) for value in contract["bounds"])
    failures = []
    expected_fields = {
        "driver": contract["format"],
        "crs": contract["crs"],
        "width": contract["width"],
        "height": contract["height"],
        "nodata": contract["nodata"],
    }
    for field, expected in expected_fields.items():
        if actual[field] != expected:
            failures.append(f"{field}={actual[field]!r}")
    if actual["cell_size_m"] != float(contract["cell_size_m"]) or actual["cell_size_y_m"] != float(contract["cell_size_m"]):
        failures.append(f"cell_size=({actual['cell_size_m']}, {actual['cell_size_y_m']})")
    if actual["bounds"] != expected_bounds:
        failures.append(f"bounds={actual['bounds']!r}")
    if actual["count"] != 1:
        failures.append(f"count={actual['count']!r}")
    if failures:
        raise ValueError(f"Unexpected BIGBANG TP raster contract: {', '.join(failures)}")
    with zipfile.ZipFile(archive) as source:
        archive_member_count = len(source.namelist())
    return RasterMetadata(
        archive_sha256=sha256_file(archive),
        archive_bytes=archive.stat().st_size,
        archive_member_count=archive_member_count,
        archive_years=(int(contract["archive_first_year"]), int(contract["archive_last_year"])),
        raster_sha256=sha256_file(raster),
        raster_bytes=raster.stat().st_size,
        raster_member=contract["raster_member"],
        projection_member=contract["projection_member"],
        driver=actual["driver"],
        crs=actual["crs"],
        width=actual["width"],
        height=actual["height"],
        cell_size_x_m=actual["cell_size_m"],
        cell_size_y_m=actual["cell_size_y_m"],
        nodata=float(actual["nodata"]),
        unit_ucum=contract["unit_ucum"],
        bounds=actual["bounds"],
    )


def area_weighted_zonal_mean(
    dataset: rasterio.io.DatasetReader,
    geometry,
) -> ZonalResult:
    if dataset.crs is None or not dataset.crs.is_projected:
        raise ValueError("Area-weighted zonal statistics require a projected raster CRS")
    if not CRS.from_user_input(dataset.crs).is_projected:
        raise ValueError("Area-weighted zonal statistics require projected metre units")
    if geometry.is_empty:
        return ZonalResult(None, 0.0, 0.0, 0, 0, ("empty_intersection",))
    if not geometry.is_valid:
        raise ValueError("Territory geometry is invalid")
    if geometry.area <= 0:
        raise ValueError("Territory geometry has non-positive area")
    raster_extent = box(*dataset.bounds)
    if not geometry.intersects(raster_extent) or geometry.intersection(raster_extent).area <= 0:
        return ZonalResult(None, 0.0, 0.0, 0, 0, ("empty_intersection",))
    try:
        window = geometry_window(dataset, [mapping(geometry)])
    except Exception as exc:
        raise ValueError("Cannot determine raster window for territory geometry") from exc
    window = window.intersection(Window(0, 0, dataset.width, dataset.height))
    values = dataset.read(1, window=window, masked=False)
    cell_transform = dataset.window_transform(window)
    weighted_sum = 0.0
    valid_area = 0.0
    intersecting = 0
    valid_cells = 0
    nodata = dataset.nodata
    for row in range(values.shape[0]):
        top = cell_transform.f + row * cell_transform.e
        bottom = top + cell_transform.e
        for column in range(values.shape[1]):
            left = cell_transform.c + column * cell_transform.a
            right = left + cell_transform.a
            intersection_area = geometry.intersection(
                box(min(left, right), min(bottom, top), max(left, right), max(bottom, top))
            ).area
            if intersection_area <= 0:
                continue
            intersecting += 1
            value = float(values[row, column])
            if not math.isfinite(value) or (nodata is not None and value == float(nodata)):
                continue
            valid_cells += 1
            valid_area += intersection_area
            weighted_sum += value * intersection_area
    if valid_area <= 0:
        return ZonalResult(None, 0.0, 0.0, intersecting, 0, ("no_valid_cells",))
    coverage = valid_area / geometry.area
    if coverage > 1 and coverage < 1 + 1e-9:
        coverage = 1.0
    flags = ("partial_valid_coverage",) if coverage < 1 - 1e-9 else ()
    return ZonalResult(
        value_decimal=weighted_sum / valid_area,
        coverage_ratio=coverage,
        valid_intersection_area_m2=valid_area,
        intersecting_cell_count=intersecting,
        valid_cell_count=valid_cells,
        quality_flags=flags,
    )


def _geometry_sha256(geometry_wkb: bytes) -> str:
    return hashlib.sha256(geometry_wkb).hexdigest()


def derive_territories(
    raster: Path,
    territories: pd.DataFrame,
    level: str,
    metadata: RasterMetadata,
) -> pd.DataFrame:
    required = {"territory_id", "territory_version_id", "level", "name", "reference_date", "geometry_wkb"}
    missing = required - set(territories.columns)
    if missing:
        raise ValueError(f"Territory canonical lacks fields: {sorted(missing)}")
    if set(territories["level"]) != {level}:
        raise ValueError(f"Territory canonical does not contain only {level}")
    if set(territories["reference_date"]) != {"2025-01-01"}:
        raise ValueError("BIGBANG TP PoC requires ISTAT territory reference 2025-01-01")
    rows = []
    with rasterio.open(raster) as dataset:
        project = Transformer.from_crs("EPSG:4326", dataset.crs, always_xy=True).transform
        for territory in territories.sort_values("territory_id").to_dict("records"):
            projected = transform(project, wkb.loads(territory["geometry_wkb"]))
            zonal = area_weighted_zonal_mean(dataset, projected)
            rows.append({
                "derived_observation_id": stable_id(
                    ALGORITHM_VERSION,
                    metadata.raster_sha256,
                    territory["territory_version_id"],
                ),
                "derived_metric_id": DERIVED_METRIC_ID,
                "territory_id": territory["territory_id"],
                "territory_version_id": territory["territory_version_id"],
                "territory_name": territory["name"],
                "territory_level": level,
                "reference_year": REFERENCE_YEAR,
                "value_decimal": zonal.value_decimal,
                "unit_ucum": metadata.unit_ucum,
                "source_dataset_id": SOURCE["source_id"],
                "source_dataset_version": "bigbang-10-1951-2025",
                "source_asset_sha256": metadata.archive_sha256,
                "source_raster_sha256": metadata.raster_sha256,
                "source_raster_locator": f"{DEFAULT_CONTRACT['archive_name']}!{metadata.raster_member}",
                "territory_geometry_reference": (
                    f"canonical/territories/reference_year=2025/{level}.parquet#"
                    f"{territory['territory_version_id']}"
                ),
                "territory_geometry_sha256": _geometry_sha256(territory["geometry_wkb"]),
                "algorithm_version": ALGORITHM_VERSION,
                "coverage_ratio": zonal.coverage_ratio,
                "valid_intersection_area_m2": zonal.valid_intersection_area_m2,
                "intersecting_cell_count": zonal.intersecting_cell_count,
                "valid_cell_count": zonal.valid_cell_count,
                "quality_flags": list(zonal.quality_flags),
                "official_status": "derived_by_stato_italia",
            })
    result = pd.DataFrame(rows)
    if result["derived_observation_id"].duplicated().any():
        raise ValueError("Duplicate BIGBANG TP derived observations")
    return result


def compare_official_regions(derived: pd.DataFrame, official: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    expected = official[
        (official["metric_id"] == OFFICIAL_METRIC_ID)
        & (official["reference_year"] == REFERENCE_YEAR)
        & (official["territory_level"] == "region")
    ][["territory_id", "value_decimal"]].rename(columns={"value_decimal": "official_value_mm"})
    if len(expected) != 20 or expected["territory_id"].duplicated().any():
        raise ValueError("Unexpected official BIGBANG TP 2025 regional canonical")
    current = derived[["territory_id", "territory_name", "value_decimal", "coverage_ratio"]].rename(
        columns={"value_decimal": "derived_raster_value_mm"}
    )
    comparison = expected.merge(current, on="territory_id", how="outer", validate="one_to_one", indicator=True)
    if len(comparison) != 20 or set(comparison["_merge"]) != {"both"}:
        raise ValueError("Derived and official BIGBANG regional territories differ")
    comparison = comparison.drop(columns="_merge")
    if comparison[["official_value_mm", "derived_raster_value_mm", "coverage_ratio"]].isna().any().any():
        raise ValueError("Regional BIGBANG comparison contains missing values")
    comparison["absolute_difference_mm"] = (
        comparison["derived_raster_value_mm"] - comparison["official_value_mm"]
    ).abs()
    comparison["relative_difference_percent"] = (
        comparison["absolute_difference_mm"] / comparison["official_value_mm"].abs() * 100
    )
    summary = {}
    for field in ("absolute_difference_mm", "relative_difference_percent"):
        summary[field] = {
            "min": float(comparison[field].min()),
            "median": float(comparison[field].median()),
            "mean": float(comparison[field].mean()),
            "max": float(comparison[field].max()),
        }
    return comparison.sort_values("territory_id"), summary


def municipality_area_feasibility(
    municipalities: pd.DataFrame,
    threshold_km2: float,
) -> dict:
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    areas = municipalities["geometry_wkb"].map(lambda value: transform(project, wkb.loads(value)).area / 1_000_000)
    at_or_above = int((areas >= threshold_km2).sum())
    below = int((areas < threshold_km2).sum())
    return {
        "threshold_km2": threshold_km2,
        "official_operator": DEFAULT_CONTRACT["methodology_min_area_operator"],
        "total_municipalities": int(len(areas)),
        "at_or_above_threshold": at_or_above,
        "strictly_above_threshold": int((areas > threshold_km2).sum()),
        "below_threshold": below,
        "minimum_area_km2": float(areas.min()),
        "median_area_km2": float(areas.median()),
        "maximum_area_km2": float(areas.max()),
        "complete_municipality_support_methodologically_defensible": below == 0,
    }


def _coverage_summary(frame: pd.DataFrame) -> dict:
    coverage = frame["coverage_ratio"].astype(float)
    return {
        "records": int(len(frame)),
        "min": float(coverage.min()),
        "median": float(coverage.median()),
        "mean": float(coverage.mean()),
        "max": float(coverage.max()),
        "missing_values": int(frame["value_decimal"].isna().sum()),
    }


def _area_threshold_summary(territories: pd.DataFrame, threshold_km2: float) -> dict:
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    areas = territories["geometry_wkb"].map(lambda value: transform(project, wkb.loads(value)).area / 1_000_000)
    return {
        "threshold_km2": threshold_km2,
        "at_or_above_threshold": int((areas >= threshold_km2).sum()),
        "below_threshold": int((areas < threshold_km2).sum()),
        "minimum_area_km2": float(areas.min()),
    }


def _write_parquet_atomic(frame: pd.DataFrame, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".parquet", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def run_poc(
    archive: Path,
    canonical_root: Path,
    derived_root: Path,
    report_path: Path,
) -> dict:
    with tempfile.TemporaryDirectory(prefix="stato-italia-bigbang-poc-") as workdir:
        raster = extract_raster(archive, Path(workdir))
        metadata = inspect_raster(raster, archive)
        region = pd.read_parquet(canonical_root / "territories/reference_year=2025/region.parquet")
        derived_regions = derive_territories(raster, region, "region", metadata)
        official = pd.read_parquet(
            canonical_root / "water/dataset_version=bigbang-10-1951-2025/observations.parquet"
        )
        comparison, comparison_summary = compare_official_regions(derived_regions, official)
        if (derived_regions["coverage_ratio"] <= 0).any():
            raise ValueError("Regional validation found empty raster coverage")
        province = pd.read_parquet(canonical_root / "territories/reference_year=2025/province.parquet")
        derived_provinces = derive_territories(raster, province, "province", metadata)
        if derived_provinces["value_decimal"].isna().any():
            raise ValueError("Provincial derivation contains empty values")
        output = pd.concat([derived_regions, derived_provinces], ignore_index=True)
        destination = derived_root / f"water/algorithm_version={ALGORITHM_VERSION}/observations.parquet"
        _write_parquet_atomic(output, destination)
    municipalities = pd.read_parquet(canonical_root / "territories/reference_year=2025/municipality.parquet")
    feasibility = municipality_area_feasibility(
        municipalities,
        float(DEFAULT_CONTRACT["methodology_min_area_km2"]),
    )
    report = {
        "schemaVersion": 1,
        "proofOfConcept": "BIGBANG 10.0 TP 2025 area-weighted zonal mean",
        "officialVsDerived": {
            "official": "ISPRA BIGBANG 10.0 regional model estimates",
            "derived": "Stato d'Italia zonal aggregation from the official raster",
        },
        "source": {
            "datasetId": SOURCE["source_id"],
            "version": "BIGBANG 10.0",
            "productPageUrl": DEFAULT_CONTRACT["product_page_url"],
            "downloadUrl": DEFAULT_CONTRACT["download_url"],
            "resolvedDownloadUrl": DEFAULT_CONTRACT["resolved_download_url"],
        },
        "raster": asdict(metadata),
        "algorithmVersion": ALGORITHM_VERSION,
        "derivedArtifact": str(destination),
        "derivedRecords": {
            "region": len(derived_regions),
            "province": len(derived_provinces),
        },
        "coverageSummary": {
            "region": _coverage_summary(derived_regions),
            "province": _coverage_summary(derived_provinces),
        },
        "methodologicalAreaGate": {
            "region": _area_threshold_summary(region, float(DEFAULT_CONTRACT["methodology_min_area_km2"])),
            "province": _area_threshold_summary(province, float(DEFAULT_CONTRACT["methodology_min_area_km2"])),
        },
        "regionalComparison": comparison.to_dict("records"),
        "regionalDifferenceSummary": comparison_summary,
        "municipalityFeasibility": feasibility,
        "methodology": {
            "sourceUrl": DEFAULT_CONTRACT["methodology_scope_url"],
            "sourcePage": DEFAULT_CONTRACT["methodology_scope_page"],
            "statement": "possibility to clip any reference territorial area (> 100 km2)",
            "interpretation": "methodological applicability statement, not a raster format limitation",
        },
    }
    json_dump(report_path, report)
    return report


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="BIGBANG 10.0 TP 2025 raster proof of concept")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, default=Path("data/canonical"))
    parser.add_argument("--derived-root", type=Path, default=Path("data/derived"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/reports/bigbang-tp-2025-poc.json"))
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_poc(args.archive, args.canonical_root, args.derived_root, args.report)
    print(json.dumps({
        "derivedRecords": report["derivedRecords"],
        "regionalDifferenceSummary": report["regionalDifferenceSummary"],
        "municipalityFeasibility": report["municipalityFeasibility"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
