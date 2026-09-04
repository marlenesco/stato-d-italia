from __future__ import annotations

import hashlib
import zipfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
import yaml
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, box
from shapely.ops import transform

from stato_italia.bigbang_raster_poc import (
    ALGORITHM_VERSION,
    EXPECTED_METRIC_BINDINGS,
    METRIC_SPECS,
    SOURCE,
    RasterMetadata,
    RasterMetricSpec,
    _write_parquet_atomic,
    area_weighted_zonal_mean,
    area_weighted_zonal_mean_prepared,
    build_metric_specs,
    derive_territories,
    extract_raster,
    inspect_raster,
    municipality_area_feasibility,
    prepare_area_weighted_zonal_geometry,
    resolve_raster_members,
    validate_archive_structure,
)
from stato_italia.bigbang_historical_territory_policy import (
    TerritoryGeometryVersion,
    resolve_bigbang_territory_policy,
)

SOURCE_SYMBOLS = tuple(EXPECTED_METRIC_BINDINGS)


def _write_raster(
    path: Path,
    values: np.ndarray,
    *,
    origin_x: float = 0,
    origin_y: float | None = None,
    cell_size: float = 1,
    nodata: float = -9999,
) -> Path:
    origin_y = float(values.shape[0]) if origin_y is None else origin_y
    with rasterio.open(
        path,
        "w",
        driver="AAIGrid",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:3035",
        transform=from_origin(origin_x, origin_y, cell_size, cell_size),
        nodata=nodata,
    ) as destination:
        destination.write(values.astype("float32"), 1)
    return path


def _contract_for(symbol: str, archive: Path, raster: Path, **overrides) -> dict:
    with rasterio.open(raster) as dataset:
        contract = {
            "source_symbol": symbol,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "archive_bytes": archive.stat().st_size,
            "archive_member_count": 2,
            "archive_first_year": 2025,
            "archive_last_year": 2025,
            "archive_name": archive.name,
            "member_prefix": symbol.lower(),
            "raster_member": f"{symbol.lower()}_2025_yyc.asc",
            "projection_member": f"{symbol.lower()}_2025_yyc.prj",
            "raster_sha256": hashlib.sha256(raster.read_bytes()).hexdigest(),
            "raster_bytes": raster.stat().st_size,
            "format": "AAIGrid",
            "crs": "EPSG:3035",
            "width": dataset.width,
            "height": dataset.height,
            "cell_size_m": abs(dataset.transform.a),
            "nodata": dataset.nodata,
            "bounds": list(dataset.bounds),
        }
    contract.update(overrides)
    return contract


def _archive(
    tmp_path: Path,
    symbol: str,
    values: np.ndarray | None = None,
) -> tuple[Path, Path, RasterMetricSpec]:
    source = tmp_path / f"source-{symbol.lower()}"
    source.mkdir()
    raster = _write_raster(
        source / f"{symbol.lower()}_2025_yyc.asc",
        values if values is not None else np.array([[10, 20], [30, 40]]),
    )
    projection = raster.with_suffix(".prj")
    archive = tmp_path / f"{symbol}_ANNUAL_2025-2025.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.write(raster, raster.name)
        output.write(projection, projection.name)
    source_spec = METRIC_SPECS[symbol]
    spec = replace(source_spec, contract=_contract_for(symbol, archive, raster))
    return archive, raster, spec


def _metadata(raster: Path, symbol: str, archive_sha: str, raster_sha: str) -> RasterMetadata:
    return RasterMetadata(
        archive_name=f"{symbol}_ANNUAL_2025-2025.zip",
        archive_sha256=archive_sha,
        archive_bytes=100,
        archive_member_count=2,
        available_annual_years=(2025,),
        raster_sha256=raster_sha,
        raster_bytes=raster.stat().st_size,
        raster_member=f"{symbol.lower()}_2025_yyc.asc",
        projection_member=f"{symbol.lower()}_2025_yyc.prj",
        driver="AAIGrid",
        crs="EPSG:3035",
        width=1,
        height=1,
        cell_size_x_m=1,
        cell_size_y_m=1,
        nodata=-9999,
        unit_ucum="mm",
        bounds=(0, 0, 1, 1),
    )


def test_metric_specs_bind_all_five_source_symbols() -> None:
    assert set(METRIC_SPECS) == set(SOURCE_SYMBOLS)
    assert {
        symbol: (spec.official_metric_id, spec.derived_metric_id)
        for symbol, spec in METRIC_SPECS.items()
    } == EXPECTED_METRIC_BINDINGS
    assert {spec.reference_year for spec in METRIC_SPECS.values()} == {2025}
    assert {spec.unit_ucum for spec in METRIC_SPECS.values()} == {"mm"}


def test_metric_dictionary_marks_all_raster_aggregations_as_derived() -> None:
    path = Path(__file__).resolve().parents[1] / "config/metrics/water.yaml"
    metrics = {metric["id"]: metric for metric in yaml.safe_load(path.read_text())["metrics"]}
    for spec in METRIC_SPECS.values():
        assert metrics[spec.official_metric_id]["source_kind"] == "official_observation"
        assert metrics[spec.derived_metric_id]["source_kind"] == "derived_metric"


def test_metric_specs_fail_closed_on_grid_units_conflict() -> None:
    source = deepcopy(SOURCE)
    source["raster_products"]["AE"]["unit_ucum"] = "m"
    with pytest.raises(ValueError, match="conflicts with GRID_UNITS"):
        build_metric_specs(source)


@pytest.mark.parametrize("symbol", SOURCE_SYMBOLS)
def test_raster_contract_validates_header_unit_and_unique_2025(tmp_path: Path, symbol: str) -> None:
    archive, _, spec = _archive(tmp_path, symbol, np.array([[10, -9999], [30, 40]]))
    extracted = extract_raster(archive, tmp_path / "extracted", spec)
    metadata = inspect_raster(extracted, archive, spec)
    assert metadata.driver == "AAIGrid"
    assert metadata.crs == "EPSG:3035"
    assert metadata.nodata == -9999
    assert metadata.unit_ucum == "mm"
    assert metadata.available_annual_years == (2025,)
    with zipfile.ZipFile(archive) as source:
        assert source.namelist().count(spec.contract["raster_member"]) == 1
        assert source.namelist().count(spec.contract["projection_member"]) == 1
    with rasterio.open(extracted) as dataset:
        assert dataset.read(1, masked=True).mask.tolist() == [[False, True], [False, False]]


@pytest.mark.parametrize("symbol", SOURCE_SYMBOLS)
def test_raster_contract_fails_closed_on_unexpected_structure(tmp_path: Path, symbol: str) -> None:
    archive, raster, spec = _archive(tmp_path, symbol)
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr("unexpected.txt", "no")
    contract = _contract_for(symbol, archive, raster, archive_member_count=3)
    with pytest.raises(ValueError, match=f"Unexpected BIGBANG {symbol} archive structure"):
        validate_archive_structure(archive, replace(spec, contract=contract))


@pytest.mark.parametrize("symbol", SOURCE_SYMBOLS)
def test_raster_contract_fails_closed_on_unexpected_header(tmp_path: Path, symbol: str) -> None:
    archive, _, spec = _archive(tmp_path, symbol)
    extracted = extract_raster(archive, tmp_path / "extracted", spec)
    contract = dict(spec.contract, width=99)
    with pytest.raises(ValueError, match=f"Unexpected BIGBANG {symbol} raster contract"):
        inspect_raster(extracted, archive, replace(spec, contract=contract))


def test_raster_contract_rejects_duplicate_2025_member(tmp_path: Path) -> None:
    archive, raster, spec = _archive(tmp_path, "TP")
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(archive, "a") as output:
            output.write(raster, raster.name)
    contract = _contract_for("TP", archive, raster, archive_member_count=3)
    with pytest.raises(ValueError, match="duplicate member"):
        validate_archive_structure(archive, replace(spec, contract=contract))


@pytest.fixture
def zonal_raster(tmp_path: Path) -> Path:
    return _write_raster(tmp_path / "grid.asc", np.array([[10, 20], [30, -9999]]))


def test_zonal_full_and_partial_cell(zonal_raster: Path) -> None:
    with rasterio.open(zonal_raster) as dataset:
        full = area_weighted_zonal_mean(dataset, box(0, 1, 1, 2))
        partial = area_weighted_zonal_mean(dataset, box(0, 1, 0.25, 2))
    assert full.value_decimal == pytest.approx(10)
    assert full.valid_intersection_area_m2 == pytest.approx(1)
    assert full.coverage_ratio == pytest.approx(1)
    assert partial.value_decimal == pytest.approx(10)
    assert partial.valid_intersection_area_m2 == pytest.approx(0.25)
    assert partial.coverage_ratio == pytest.approx(1)


def test_zonal_uses_intersection_area_weighting(zonal_raster: Path) -> None:
    territory = box(0, 1, 1.25, 2)
    with rasterio.open(zonal_raster) as dataset:
        result = area_weighted_zonal_mean(dataset, territory)
    assert result.value_decimal == pytest.approx((10 * 1 + 20 * 0.25) / 1.25)
    assert result.intersecting_cell_count == 2
    assert result.valid_cell_count == 2


def test_zonal_excludes_nodata_and_reports_coverage(zonal_raster: Path) -> None:
    with rasterio.open(zonal_raster) as dataset:
        result = area_weighted_zonal_mean(dataset, box(0, 0, 2, 1))
    assert result.value_decimal == pytest.approx(30)
    assert result.coverage_ratio == pytest.approx(0.5)
    assert result.valid_intersection_area_m2 == pytest.approx(1)
    assert result.intersecting_cell_count == 2
    assert result.valid_cell_count == 1
    assert result.quality_flags == ("partial_valid_coverage",)


def test_zonal_supports_multipolygon(zonal_raster: Path) -> None:
    territory = MultiPolygon([box(0, 1.1, 1, 2), box(0, 0, 1, 0.9)])
    with rasterio.open(zonal_raster) as dataset:
        result = area_weighted_zonal_mean(dataset, territory)
    assert result.value_decimal == pytest.approx(20)
    assert result.coverage_ratio == pytest.approx(1)
    assert result.valid_cell_count == 2


def test_zonal_handles_empty_intersection(zonal_raster: Path) -> None:
    with rasterio.open(zonal_raster) as dataset:
        result = area_weighted_zonal_mean(dataset, box(10, 10, 11, 11))
    assert result.value_decimal is None
    assert result.coverage_ratio == 0
    assert result.intersecting_cell_count == 0
    assert result.valid_cell_count == 0
    assert result.quality_flags == ("empty_intersection",)


def test_prepared_zonal_geometry_preserves_the_validated_algorithm(zonal_raster: Path) -> None:
    territory = box(0, 0, 1.25, 2)
    with rasterio.open(zonal_raster) as dataset:
        direct = area_weighted_zonal_mean(dataset, territory)
        prepared = prepare_area_weighted_zonal_geometry(dataset, territory)
        reused = area_weighted_zonal_mean_prepared(dataset.read(1, masked=False), dataset.nodata, prepared)
    assert reused == direct


@pytest.mark.parametrize(("symbol", "year", "expected"), [
    ("TP", 2006, ("tp_2006_yyc.asc", "tp_2006_yyc.prj")),
    ("AE", 2018, ("ae_2018_yyc.asc", "ae_2018_yyc.prj")),
    ("RF", 2024, ("rf_2024_yyc.asc", "rf_2024_yyc.prj")),
])
def test_historical_member_resolution_is_exact(symbol: str, year: int, expected: tuple[str, str]) -> None:
    assert resolve_raster_members(METRIC_SPECS[symbol], year) == expected


def test_historical_member_resolution_rejects_out_of_range_year() -> None:
    with pytest.raises(ValueError, match="1951-2025"):
        resolve_raster_members(METRIC_SPECS["TP"], 1950)


def test_derived_ids_include_metric_and_provenance_remain_derived(tmp_path: Path) -> None:
    geometry_wgs84 = box(10, 45, 10.005, 45.005)
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    projected = transform(project, geometry_wgs84)
    raster = _write_raster(
        tmp_path / "derived-grid.asc",
        np.array([[123.4]]),
        origin_x=projected.bounds[0] - 10,
        origin_y=projected.bounds[3] + 10,
        cell_size=max(projected.bounds[2] - projected.bounds[0], projected.bounds[3] - projected.bounds[1]) + 20,
    )
    territories = pd.DataFrame([{
        "territory_id": "it:region:99",
        "territory_version_id": "it:region:99@2025-01-01",
        "level": "region",
        "name": "Test",
        "reference_date": "2025-01-01",
        "geometry_wkb": geometry_wgs84.wkb,
    }])
    tp = derive_territories(raster, territories, "region", _metadata(raster, "TP", "a" * 64, "b" * 64), METRIC_SPECS["TP"])
    ae = derive_territories(raster, territories, "region", _metadata(raster, "AE", "c" * 64, "b" * 64), METRIC_SPECS["AE"])
    output = pd.concat([tp, ae], ignore_index=True)

    assert set(output["derived_metric_id"]) == {
        "water_total_precipitation_mm_zonal_mean",
        "water_actual_evapotranspiration_mm_zonal_mean",
    }
    assert output["derived_observation_id"].is_unique
    assert tp.iloc[0]["derived_observation_id"] != ae.iloc[0]["derived_observation_id"]
    assert set(output["source_asset_sha256"]) == {"a" * 64, "c" * 64}
    assert set(output["source_raster_sha256"]) == {"b" * 64}
    assert set(output["source_raster_locator"]) == {
        "TP_ANNUAL_2025-2025.zip!tp_2025_yyc.asc",
        "AE_ANNUAL_2025-2025.zip!ae_2025_yyc.asc",
    }
    assert set(output["algorithm_version"]) == {ALGORITHM_VERSION}
    assert set(output["official_status"]) == {"derived_by_stato_italia"}
    assert all(value.startswith("canonical/territories/reference_year=2025/") for value in output["territory_geometry_reference"])
    assert all(len(value) == 64 for value in output["territory_geometry_sha256"])

    official = tmp_path / "canonical/water/observations.parquet"
    official.parent.mkdir(parents=True)
    official.write_bytes(b"official-unchanged")
    destination = tmp_path / f"derived/water/algorithm_version={ALGORITHM_VERSION}/observations.parquet"
    _write_parquet_atomic(output, destination)
    assert destination.exists()
    assert official.read_bytes() == b"official-unchanged"


def test_derived_ids_include_reference_year_for_documented_geometry_interval(tmp_path: Path) -> None:
    geometry_wgs84 = box(10, 45, 10.005, 45.005)
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True).transform
    projected = transform(project, geometry_wgs84)
    raster = _write_raster(
        tmp_path / "interval-grid.asc",
        np.array([[123.4]]),
        origin_x=projected.bounds[0] - 10,
        origin_y=projected.bounds[3] + 10,
        cell_size=max(projected.bounds[2] - projected.bounds[0], projected.bounds[3] - projected.bounds[1]) + 20,
    )
    interval = TerritoryGeometryVersion(
        territory_level="province",
        reference_year=1989,
        territory_reference_date="1989-01-01",
        territory_source="ISTAT SITUAS",
        geometry_reference="canonical/territories/reference_year=1989/province.parquet",
        documented_valid_from=1990,
        documented_valid_to=1991,
        documented_interval_source="ISTAT SITUAS official validity record",
    )
    decisions = [
        resolve_bigbang_territory_policy(year, "province", [interval])
        for year in (1990, 1991)
    ]
    assert all(decision.support_status == "derived_supported" for decision in decisions)
    assert {decision.territory_reference_date for decision in decisions} == {"1989-01-01"}
    territories = pd.DataFrame([{
        "territory_id": "it:province:001",
        "territory_version_id": "it:province:001@1989-01-01",
        "level": "province",
        "name": "Test",
        "reference_date": "1989-01-01",
        "geometry_wkb": geometry_wgs84.wkb,
    }])
    metadata = _metadata(raster, "TP", "a" * 64, "b" * 64)
    observations = [
        derive_territories(
            raster,
            territories,
            "province",
            metadata,
            replace(METRIC_SPECS["TP"], reference_year=year),
            territory_reference_date="1989-01-01",
            territory_geometry_reference=interval.geometry_reference,
        )
        for year in (1990, 1991)
    ]
    assert observations[0].iloc[0]["derived_metric_id"] == observations[1].iloc[0]["derived_metric_id"]
    assert observations[0].iloc[0]["source_raster_sha256"] == observations[1].iloc[0]["source_raster_sha256"]
    assert observations[0].iloc[0]["territory_version_id"] == observations[1].iloc[0]["territory_version_id"]
    assert observations[0].iloc[0]["derived_observation_id"] != observations[1].iloc[0]["derived_observation_id"]


def test_municipality_feasibility_applies_documented_area_threshold() -> None:
    unproject = Transformer.from_crs("EPSG:3035", "EPSG:4326", always_xy=True).transform
    municipalities = pd.DataFrame({
        "geometry_wkb": [
            transform(unproject, box(0, 0, 11_000, 11_000)).wkb,
            transform(unproject, box(0, 0, 5_000, 5_000)).wkb,
        ]
    })
    result = municipality_area_feasibility(municipalities, 100)
    assert result["at_or_above_threshold"] == 1
    assert result["below_threshold"] == 1
    assert result["complete_municipality_support_methodologically_defensible"] is False
