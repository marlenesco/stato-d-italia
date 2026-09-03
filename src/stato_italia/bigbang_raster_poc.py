from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import tempfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

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
REFERENCE_YEAR = 2025
# The Task 1 identifier is retained because the area-weighted algorithm is unchanged.
ALGORITHM_VERSION = "bigbang-tp-zonal-area-weighted-v1"
EXPECTED_METRIC_BINDINGS = {
    "TP": ("water_total_precipitation_mm", "water_total_precipitation_mm_zonal_mean"),
    "AE": (
        "water_actual_evapotranspiration_mm",
        "water_actual_evapotranspiration_mm_zonal_mean",
    ),
    "IF": ("water_internal_flow_mm", "water_internal_flow_mm_zonal_mean"),
    "GR": ("water_aquifer_recharge_mm", "water_aquifer_recharge_mm_zonal_mean"),
    "RF": ("water_surface_runoff_mm", "water_surface_runoff_mm_zonal_mean"),
}


@dataclass(frozen=True)
class RasterMetricSpec:
    source_symbol: str
    official_metric_id: str
    derived_metric_id: str
    unit_ucum: str
    reference_year: int
    contract: Mapping[str, object]


@dataclass(frozen=True)
class RasterMetadata:
    archive_name: str
    archive_sha256: str
    archive_bytes: int
    archive_member_count: int
    available_annual_years: tuple[int, ...]
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


def build_metric_specs(source: Mapping[str, object]) -> dict[str, RasterMetricSpec]:
    products = source.get("raster_products")
    if not isinstance(products, Mapping) or set(products) != set(EXPECTED_METRIC_BINDINGS):
        raise ValueError("BIGBANG raster products must define exactly TP, AE, IF, GR and RF")
    evidence = source.get("raster_unit_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("verified_unit_ucum") != "mm":
        raise ValueError("BIGBANG raster unit evidence must verify millimetres")

    specs: dict[str, RasterMetricSpec] = {}
    for symbol, (official_metric_id, derived_metric_id) in EXPECTED_METRIC_BINDINGS.items():
        raw = products[symbol]
        if not isinstance(raw, Mapping):
            raise ValueError(f"BIGBANG {symbol} raster contract is not a mapping")
        actual_binding = (
            raw.get("official_metric_id"),
            raw.get("derived_metric_id"),
        )
        if raw.get("source_symbol") != symbol or actual_binding != (official_metric_id, derived_metric_id):
            raise ValueError(f"Unexpected BIGBANG {symbol} metric binding")
        if int(raw.get("reference_year", 0)) != REFERENCE_YEAR:
            raise ValueError(f"BIGBANG {symbol} PoC must remain limited to 2025")
        if raw.get("unit_ucum") != evidence["verified_unit_ucum"]:
            raise ValueError(f"BIGBANG {symbol} unit conflicts with GRID_UNITS")
        specs[symbol] = RasterMetricSpec(
            source_symbol=symbol,
            official_metric_id=official_metric_id,
            derived_metric_id=derived_metric_id,
            unit_ucum=str(raw["unit_ucum"]),
            reference_year=int(raw["reference_year"]),
            contract=raw,
        )
    if len({spec.official_metric_id for spec in specs.values()}) != len(specs):
        raise ValueError("BIGBANG official metric IDs must be unique")
    if len({spec.derived_metric_id for spec in specs.values()}) != len(specs):
        raise ValueError("BIGBANG derived metric IDs must be unique")
    return specs


METRIC_SPECS = build_metric_specs(SOURCE)
DEFAULT_SPEC = METRIC_SPECS["TP"]
# Compatibility names for callers of the accepted Task 1 PoC.
DEFAULT_CONTRACT = DEFAULT_SPEC.contract
DERIVED_METRIC_ID = DEFAULT_SPEC.derived_metric_id
OFFICIAL_METRIC_ID = DEFAULT_SPEC.official_metric_id


def _expected_members(spec: RasterMetricSpec) -> set[str]:
    contract = spec.contract
    first = int(contract["archive_first_year"])
    last = int(contract["archive_last_year"])
    prefix = str(contract["member_prefix"])
    return {
        f"{prefix}_{year}_yyc.{suffix}"
        for year in range(first, last + 1)
        for suffix in ("asc", "prj")
    }


def validate_archive_structure(archive: Path, spec: RasterMetricSpec = DEFAULT_SPEC) -> None:
    contract = spec.contract
    context = f"BIGBANG {spec.source_symbol}"
    if archive.name != contract["archive_name"]:
        raise ValueError(f"Unexpected {context} archive name")
    if sha256_file(archive) != contract["archive_sha256"]:
        raise ValueError(f"Unexpected {context} archive SHA-256")
    if archive.stat().st_size != int(contract["archive_bytes"]):
        raise ValueError(f"Unexpected {context} archive byte size")
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError(f"{context} archive contains duplicate member names")
        if len(names) != int(contract["archive_member_count"]):
            raise ValueError(f"Unexpected {context} archive member count")
        expected = _expected_members(spec)
        if set(names) != expected:
            raise ValueError(
                f"Unexpected {context} archive structure: "
                f"missing={sorted(expected - set(names))}, unexpected={sorted(set(names) - expected)}"
            )
        raster_member = str(contract["raster_member"])
        projection_member = str(contract["projection_member"])
        if names.count(raster_member) != 1 or names.count(projection_member) != 1:
            raise ValueError(f"{context} 2025 raster or projection is not unique")
        raster_info = source.getinfo(raster_member)
        if raster_info.file_size != int(contract["raster_bytes"]):
            raise ValueError(f"Unexpected {context} 2025 raster byte size")


def extract_raster(
    archive: Path,
    destination: Path,
    spec: RasterMetricSpec = DEFAULT_SPEC,
) -> Path:
    contract = spec.contract
    validate_archive_structure(archive, spec)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for member in (str(contract["raster_member"]), str(contract["projection_member"])):
            target = destination / Path(member).name
            with source.open(member) as incoming, target.open("wb") as output:
                shutil.copyfileobj(incoming, output)
    raster = destination / Path(str(contract["raster_member"])).name
    if sha256_file(raster) != contract["raster_sha256"]:
        raise ValueError(f"Unexpected BIGBANG {spec.source_symbol} 2025 raster SHA-256")
    return raster


def inspect_raster(
    raster: Path,
    archive: Path,
    spec: RasterMetricSpec = DEFAULT_SPEC,
) -> RasterMetadata:
    contract = spec.contract
    context = f"BIGBANG {spec.source_symbol}"
    with rasterio.open(raster) as dataset:
        if dataset.crs is None:
            raise ValueError(f"{context} raster lacks CRS")
        if dataset.transform.b != 0 or dataset.transform.d != 0:
            raise ValueError(f"Rotated {context} grids are not supported")
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
    if (
        actual["cell_size_m"] != float(contract["cell_size_m"])
        or actual["cell_size_y_m"] != float(contract["cell_size_m"])
    ):
        failures.append(f"cell_size=({actual['cell_size_m']}, {actual['cell_size_y_m']})")
    if actual["bounds"] != expected_bounds:
        failures.append(f"bounds={actual['bounds']!r}")
    if actual["count"] != 1:
        failures.append(f"count={actual['count']!r}")
    if spec.unit_ucum != "mm":
        failures.append(f"unit_ucum={spec.unit_ucum!r}")
    if failures:
        raise ValueError(f"Unexpected {context} raster contract: {', '.join(failures)}")
    first = int(contract["archive_first_year"])
    last = int(contract["archive_last_year"])
    return RasterMetadata(
        archive_name=archive.name,
        archive_sha256=sha256_file(archive),
        archive_bytes=archive.stat().st_size,
        archive_member_count=int(contract["archive_member_count"]),
        available_annual_years=tuple(range(first, last + 1)),
        raster_sha256=sha256_file(raster),
        raster_bytes=raster.stat().st_size,
        raster_member=str(contract["raster_member"]),
        projection_member=str(contract["projection_member"]),
        driver=str(actual["driver"]),
        crs=str(actual["crs"]),
        width=int(actual["width"]),
        height=int(actual["height"]),
        cell_size_x_m=float(actual["cell_size_m"]),
        cell_size_y_m=float(actual["cell_size_y_m"]),
        nodata=float(actual["nodata"]),
        unit_ucum=spec.unit_ucum,
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
    spec: RasterMetricSpec = DEFAULT_SPEC,
) -> pd.DataFrame:
    required = {
        "territory_id",
        "territory_version_id",
        "level",
        "name",
        "reference_date",
        "geometry_wkb",
    }
    missing = required - set(territories.columns)
    if missing:
        raise ValueError(f"Territory canonical lacks fields: {sorted(missing)}")
    if set(territories["level"]) != {level}:
        raise ValueError(f"Territory canonical does not contain only {level}")
    reference_date = f"{spec.reference_year}-01-01"
    if set(territories["reference_date"]) != {reference_date}:
        raise ValueError(f"BIGBANG {spec.source_symbol} PoC requires ISTAT territory reference {reference_date}")
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
                "derived_metric_id": spec.derived_metric_id,
                "territory_id": territory["territory_id"],
                "territory_version_id": territory["territory_version_id"],
                "territory_name": territory["name"],
                "territory_level": level,
                "reference_year": spec.reference_year,
                "value_decimal": zonal.value_decimal,
                "unit_ucum": metadata.unit_ucum,
                "source_dataset_id": SOURCE["source_id"],
                "source_dataset_version": SOURCE["dataset_version"],
                "source_asset_sha256": metadata.archive_sha256,
                "source_raster_sha256": metadata.raster_sha256,
                "source_raster_locator": f"{metadata.archive_name}!{metadata.raster_member}",
                "territory_geometry_reference": (
                    f"canonical/territories/reference_year={spec.reference_year}/{level}.parquet#"
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
        raise ValueError(f"Duplicate BIGBANG {spec.source_symbol} derived observations")
    return result


def compare_official_regions(
    derived: pd.DataFrame,
    official: pd.DataFrame,
    spec: RasterMetricSpec = DEFAULT_SPEC,
) -> tuple[pd.DataFrame, dict]:
    expected = official[
        (official["metric_id"] == spec.official_metric_id)
        & (official["reference_year"] == spec.reference_year)
        & (official["territory_level"] == "region")
    ][["territory_id", "value_decimal", "unit_ucum"]].rename(
        columns={"value_decimal": "official_value_mm"}
    )
    if len(expected) != 20 or expected["territory_id"].duplicated().any():
        raise ValueError(f"Unexpected official BIGBANG {spec.source_symbol} 2025 regional canonical")
    if set(expected["unit_ucum"]) != {spec.unit_ucum}:
        raise ValueError(f"Official BIGBANG {spec.source_symbol} unit conflicts with raster contract")
    expected = expected.drop(columns="unit_ucum")
    current = derived[["territory_id", "territory_name", "value_decimal", "coverage_ratio"]].rename(
        columns={"value_decimal": "derived_raster_value_mm"}
    )
    comparison = expected.merge(current, on="territory_id", how="outer", validate="one_to_one", indicator=True)
    if len(comparison) != 20 or set(comparison["_merge"]) != {"both"}:
        raise ValueError(f"Derived and official BIGBANG {spec.source_symbol} regional territories differ")
    comparison = comparison.drop(columns="_merge")
    numeric = comparison[["official_value_mm", "derived_raster_value_mm", "coverage_ratio"]]
    if numeric.isna().any().any():
        raise ValueError(f"Regional BIGBANG {spec.source_symbol} comparison contains missing values")
    if (comparison["official_value_mm"] == 0).any():
        raise ValueError(f"Regional BIGBANG {spec.source_symbol} comparison has undefined relative differences")
    comparison["absolute_difference_mm"] = (
        comparison["derived_raster_value_mm"] - comparison["official_value_mm"]
    ).abs()
    comparison["relative_difference_percent"] = (
        comparison["absolute_difference_mm"] / comparison["official_value_mm"].abs() * 100
    )
    summary = {}
    for field in ("absolute_difference_mm", "relative_difference_percent", "coverage_ratio"):
        output_name = "coverage" if field == "coverage_ratio" else field
        summary[output_name] = {
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
    areas = municipalities["geometry_wkb"].map(
        lambda value: transform(project, wkb.loads(value)).area / 1_000_000
    )
    at_or_above = int((areas >= threshold_km2).sum())
    below = int((areas < threshold_km2).sum())
    return {
        "threshold_km2": threshold_km2,
        "official_operator": SOURCE["raster_methodology"]["methodology_min_area_operator"],
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
        "missing_values": int(frame["value_decimal"].isna().sum()),
        "min": float(coverage.min()),
        "median": float(coverage.median()),
        "mean": float(coverage.mean()),
        "max": float(coverage.max()),
    }


def _area_threshold_summary(territories: pd.DataFrame, threshold_km2: float) -> dict:
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    areas = territories["geometry_wkb"].map(
        lambda value: transform(project, wkb.loads(value)).area / 1_000_000
    )
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


def _validate_derived_output(
    output: pd.DataFrame,
    region_count: int,
    province_count: int,
    approved_province_symbols: set[str],
) -> None:
    if output["derived_observation_id"].duplicated().any():
        raise ValueError("Derived BIGBANG observation IDs collide across metrics")
    if set(output["reference_year"]) != {REFERENCE_YEAR}:
        raise ValueError("Derived BIGBANG artifact contains a year other than 2025")
    if set(output["official_status"]) != {"derived_by_stato_italia"}:
        raise ValueError("Derived BIGBANG artifact has an unexpected official status")
    for symbol, spec in METRIC_SPECS.items():
        metric = output[output["derived_metric_id"] == spec.derived_metric_id]
        if len(metric[metric["territory_level"] == "region"]) != region_count:
            raise ValueError(f"Derived BIGBANG {symbol} regional record count is incomplete")
        expected_provinces = province_count if symbol in approved_province_symbols else 0
        if len(metric[metric["territory_level"] == "province"]) != expected_provinces:
            raise ValueError(f"Derived BIGBANG {symbol} provincial record count is incomplete")


def run_poc(
    archive_dir: Path,
    canonical_root: Path,
    derived_root: Path,
    report_path: Path,
    approved_province_symbols: Sequence[str] = (),
) -> dict:
    approved = set(approved_province_symbols)
    unknown = approved - set(METRIC_SPECS)
    if unknown:
        raise ValueError(f"Unknown BIGBANG province approvals: {sorted(unknown)}")

    territory_root = canonical_root / f"territories/reference_year={REFERENCE_YEAR}"
    regions = pd.read_parquet(territory_root / "region.parquet")
    provinces = pd.read_parquet(territory_root / "province.parquet")
    official_path = canonical_root / f"water/dataset_version={SOURCE['dataset_version']}/observations.parquet"
    official_sha256_before = sha256_file(official_path)
    official = pd.read_parquet(official_path)
    derived_frames = []
    metric_reports = {}

    with tempfile.TemporaryDirectory(prefix="stato-italia-bigbang-poc-") as workdir:
        for symbol, spec in METRIC_SPECS.items():
            contract = spec.contract
            archive = archive_dir / str(contract["archive_name"])
            raster = extract_raster(archive, Path(workdir) / symbol.lower(), spec)
            metadata = inspect_raster(raster, archive, spec)
            derived_regions = derive_territories(raster, regions, "region", metadata, spec)
            comparison, comparison_summary = compare_official_regions(derived_regions, official, spec)
            if (derived_regions["coverage_ratio"] <= 0).any():
                raise ValueError(f"Regional validation found empty {symbol} raster coverage")
            derived_frames.append(derived_regions)

            province_summary = None
            if symbol in approved:
                derived_provinces = derive_territories(raster, provinces, "province", metadata, spec)
                if derived_provinces["value_decimal"].isna().any():
                    raise ValueError(f"Provincial {symbol} derivation contains empty values")
                derived_frames.append(derived_provinces)
                province_summary = _coverage_summary(derived_provinces)

            metric_reports[symbol] = {
                "sourceSymbol": symbol,
                "officialMetricId": spec.official_metric_id,
                "derivedMetricId": spec.derived_metric_id,
                "referenceYear": spec.reference_year,
                "unitUcum": spec.unit_ucum,
                "source": {
                    "productPageUrl": contract["product_page_url"],
                    "downloadUrl": contract["download_url"],
                    "resolvedDownloadUrl": contract["resolved_download_url"],
                },
                "raster": asdict(metadata),
                "regionalComparison": comparison.to_dict("records"),
                "regionalDifferenceSummary": comparison_summary,
                "provinceComputation": {
                    "status": (
                        "approved_after_manual_regional_review"
                        if symbol in approved
                        else "not_run_pending_manual_regional_review"
                    ),
                    "coverageSummary": province_summary,
                },
            }

    output = pd.concat(derived_frames, ignore_index=True)
    _validate_derived_output(output, len(regions), len(provinces), approved)
    destination = derived_root / f"water/algorithm_version={ALGORITHM_VERSION}/observations.parquet"
    _write_parquet_atomic(output, destination)
    if sha256_file(official_path) != official_sha256_before:
        raise ValueError("Official BIGBANG canonical changed during derived processing")

    municipalities = pd.read_parquet(territory_root / "municipality.parquet")
    methodology = SOURCE["raster_methodology"]
    threshold = float(methodology["methodology_min_area_km2"])
    report = {
        "schemaVersion": 2,
        "proofOfConcept": "BIGBANG 10.0 five-metric 2025 area-weighted zonal mean",
        "referenceYear": REFERENCE_YEAR,
        "officialVsDerived": {
            "official": "ISPRA BIGBANG 10.0 country and regional model estimates",
            "derived": "Stato d'Italia zonal aggregation from official rasters",
            "officialCanonicalSha256": official_sha256_before,
            "officialCanonicalUnchanged": True,
        },
        "source": {
            "datasetId": SOURCE["source_id"],
            "datasetVersion": SOURCE["dataset_version"],
            "version": "BIGBANG 10.0",
            "unitEvidence": SOURCE["raster_unit_evidence"],
        },
        "algorithmVersion": ALGORITHM_VERSION,
        "algorithmCompatibility": (
            "Task 1 identifier retained; TP algorithm and derived observation identity are unchanged"
        ),
        "derivedArtifact": str(destination),
        "derivedRecords": {
            "total": int(len(output)),
            "region": int((output["territory_level"] == "region").sum()),
            "province": int((output["territory_level"] == "province").sum()),
        },
        "provinceApprovals": sorted(approved),
        "metrics": metric_reports,
        "methodologicalAreaGate": {
            "region": _area_threshold_summary(regions, threshold),
            "province": _area_threshold_summary(provinces, threshold),
        },
        "municipalityFeasibility": municipality_area_feasibility(municipalities, threshold),
        "methodology": {
            "currentSourceUrl": methodology["scope_url"],
            "supportingPresentationUrl": methodology["supporting_presentation_url"],
            "supportingPresentationPage": methodology["supporting_presentation_page"],
            "statement": "possibility to clip any reference territorial area (> 100 km2)",
            "interpretation": "methodological applicability statement, not a raster format limitation",
        },
    }
    json_dump(report_path, report)
    return report


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="BIGBANG 10.0 five-metric 2025 raster proof of concept")
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, default=Path("data/canonical"))
    parser.add_argument("--derived-root", type=Path, default=Path("data/derived"))
    parser.add_argument("--report", type=Path, default=Path("artifacts/reports/bigbang-2025-poc.json"))
    parser.add_argument(
        "--approve-provinces",
        nargs="*",
        choices=tuple(METRIC_SPECS),
        default=(),
        help="Metrics manually approved after reviewing the complete regional comparisons",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = run_poc(
        args.archive_dir,
        args.canonical_root,
        args.derived_root,
        args.report,
        args.approve_provinces,
    )
    print(json.dumps({
        "derivedRecords": report["derivedRecords"],
        "provinceApprovals": report["provinceApprovals"],
        "regionalDifferenceSummary": {
            symbol: details["regionalDifferenceSummary"]
            for symbol, details in report["metrics"].items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
