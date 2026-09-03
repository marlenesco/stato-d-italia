from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, box
from shapely.ops import transform

from stato_italia.bigbang_raster_poc import (
    ALGORITHM_VERSION,
    DERIVED_METRIC_ID,
    RasterMetadata,
    _write_parquet_atomic,
    area_weighted_zonal_mean,
    derive_territories,
    extract_raster,
    inspect_raster,
    municipality_area_feasibility,
    validate_archive_structure,
)


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


def _contract_for(archive: Path, raster: Path, **overrides) -> dict:
    with rasterio.open(raster) as dataset:
        contract = {
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "archive_bytes": archive.stat().st_size,
            "archive_first_year": 2025,
            "archive_last_year": 2025,
            "archive_name": archive.name,
            "raster_member": "tp_2025_yyc.asc",
            "projection_member": "tp_2025_yyc.prj",
            "raster_sha256": hashlib.sha256(raster.read_bytes()).hexdigest(),
            "raster_bytes": raster.stat().st_size,
            "format": "AAIGrid",
            "crs": "EPSG:3035",
            "width": dataset.width,
            "height": dataset.height,
            "cell_size_m": abs(dataset.transform.a),
            "nodata": dataset.nodata,
            "unit_ucum": "mm",
            "bounds": list(dataset.bounds),
        }
    contract.update(overrides)
    return contract


def _archive(tmp_path: Path, values: np.ndarray | None = None) -> tuple[Path, Path, dict]:
    source = tmp_path / "source"
    source.mkdir()
    raster = _write_raster(source / "tp_2025_yyc.asc", values if values is not None else np.array([[10, 20], [30, 40]]))
    projection = raster.with_suffix(".prj")
    archive = tmp_path / "TP_ANNUAL_2025-2025.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.write(raster, raster.name)
        output.write(projection, projection.name)
    return archive, raster, _contract_for(archive, raster)


def test_raster_contract_validates_header_nodata_and_unique_2025(tmp_path: Path) -> None:
    archive, _, contract = _archive(tmp_path, np.array([[10, -9999], [30, 40]]))
    extracted = extract_raster(archive, tmp_path / "extracted", contract)
    metadata = inspect_raster(extracted, archive, contract)
    assert metadata.driver == "AAIGrid"
    assert metadata.crs == "EPSG:3035"
    assert metadata.nodata == -9999
    with rasterio.open(extracted) as dataset:
        assert dataset.read(1, masked=True).mask.tolist() == [[False, True], [False, False]]


def test_raster_contract_fails_closed_on_unexpected_structure(tmp_path: Path) -> None:
    archive, raster, _ = _archive(tmp_path)
    with zipfile.ZipFile(archive, "a") as output:
        output.writestr("unexpected.txt", "no")
    contract = _contract_for(archive, raster)
    with pytest.raises(ValueError, match="Unexpected BIGBANG TP archive structure"):
        validate_archive_structure(archive, contract)


def test_raster_contract_fails_closed_on_unexpected_header(tmp_path: Path) -> None:
    archive, _, contract = _archive(tmp_path)
    extracted = extract_raster(archive, tmp_path / "extracted", contract)
    contract["width"] = 99
    with pytest.raises(ValueError, match="Unexpected BIGBANG TP raster contract"):
        inspect_raster(extracted, archive, contract)


def test_raster_contract_rejects_duplicate_2025_member(tmp_path: Path) -> None:
    archive, raster, _ = _archive(tmp_path)
    with pytest.warns(UserWarning):
        with zipfile.ZipFile(archive, "a") as output:
            output.write(raster, raster.name)
    contract = _contract_for(archive, raster)
    with pytest.raises(ValueError, match="duplicate member"):
        validate_archive_structure(archive, contract)


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


def test_derived_artifact_keeps_provenance_and_does_not_touch_official_canonical(tmp_path: Path) -> None:
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
    metadata = RasterMetadata(
        archive_sha256="a" * 64,
        archive_bytes=100,
        archive_member_count=2,
        archive_years=(2025, 2025),
        raster_sha256="b" * 64,
        raster_bytes=raster.stat().st_size,
        raster_member="tp_2025_yyc.asc",
        projection_member="tp_2025_yyc.prj",
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
    territories = pd.DataFrame([{
        "territory_id": "it:region:99",
        "territory_version_id": "it:region:99@2025-01-01",
        "level": "region",
        "name": "Test",
        "reference_date": "2025-01-01",
        "geometry_wkb": geometry_wgs84.wkb,
    }])
    result = derive_territories(raster, territories, "region", metadata)
    row = result.iloc[0]
    assert row["derived_metric_id"] == DERIVED_METRIC_ID
    assert row["algorithm_version"] == ALGORITHM_VERSION
    assert row["source_asset_sha256"] == "a" * 64
    assert row["source_raster_sha256"] == "b" * 64
    assert row["territory_version_id"] == "it:region:99@2025-01-01"
    assert row["territory_geometry_reference"].startswith("canonical/territories/reference_year=2025/")
    assert len(row["territory_geometry_sha256"]) == 64
    official = tmp_path / "canonical/water/observations.parquet"
    official.parent.mkdir(parents=True)
    official.write_bytes(b"official-unchanged")
    destination = tmp_path / f"derived/water/algorithm_version={ALGORITHM_VERSION}/observations.parquet"
    _write_parquet_atomic(result, destination)
    assert destination.exists()
    assert official.read_bytes() == b"official-unchanged"


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
