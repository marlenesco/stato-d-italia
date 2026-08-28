from pathlib import Path
import os

import pytest
from shapely.geometry import Polygon

from stato_italia.cli import load_local_env
import stato_italia.forests as forests
from stato_italia.forests import CORINE, HRL, _process_payload, _process_tile_grid, _read_statistical_checkpoint, _reference_years_for_asset, _stats_payload, _write_statistical_checkpoint


def test_corine_and_hrl_keep_separate_forest_cover_metrics() -> None:
    assert CORINE["source_id"] != HRL["source_id"]
    assert "CORINE" in CORINE["known_limitations"][0]
    assert HRL["assets"][0]["kind"] == "tree_cover_density"


def test_change_raster_requires_two_reference_years() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_change")
    assert _reference_years_for_asset(asset, Path("tree-cover-change-2018-2021.tif")) == (2018, 2021)
    with pytest.raises(ValueError, match="start and end year"):
        _reference_years_for_asset(asset, Path("tree-cover-change-2021.tif"))


def test_statistical_payload_uses_cdse_byoc_and_equal_area_crs() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density")
    territory = {"geometry_wkb": Polygon([(12, 41), (12.1, 41), (12.1, 41.1), (12, 41.1)]).wkb}
    payload = _stats_payload(asset, territory, 2023, 2023)
    assert payload["input"]["data"][0]["type"] == f"byoc-{asset['byoc_collection_id']}"
    assert payload["input"]["bounds"]["properties"]["crs"].endswith("/3035")
    assert payload["calculations"]["default"]["statistics"]["default"]["percentiles"]["k"] == [25, 50, 75]


def test_statistical_mode_contract_declares_real_and_future_modes() -> None:
    assert HRL["processing_modes"] == ["statistical-api", "raster"]
    assert HRL["development_slice"]["region_istat_codes"] == ["03", "09", "12", "19"]
    forest_type = next(item for item in HRL["assets"] if item["kind"] == "forest_type")
    assert forest_type["class_codes"]["mixed"] == 3


def test_process_raster_grid_is_epsg3035_aligned_and_bounded() -> None:
    geometry = Polygon([(12, 41), (12.8, 41), (12.8, 41.7), (12, 41.7)]).wkb
    tiles = _process_tile_grid(geometry, resolution_m=100, max_pixels=256)

    assert len(tiles) > 1
    for bbox, width, height, _, _ in tiles:
        assert width <= 256 and height <= 256
        assert (bbox[2] - bbox[0]) == width * 100
        assert (bbox[3] - bbox[1]) == height * 100
        assert all(value % 100 == 0 for value in bbox)


def test_process_payload_preserves_source_band_and_explicit_nodata() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density")
    payload = _process_payload(asset, (1000, 2000, 3000, 4000), 20, 20, 2023, 2023)

    assert payload["input"]["data"][0]["type"] == f"byoc-{asset['byoc_collection_id']}"
    assert payload["input"]["bounds"]["properties"]["crs"].endswith("/3035")
    assert payload["output"]["responses"][0]["format"]["type"] == "image/tiff"
    assert asset["band"] in payload["evalscript"]
    assert str(asset["process_no_data"]) in payload["evalscript"]


def test_local_env_is_optional_and_never_overrides_shell_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CDSE_CLIENT_ID=local-id\nCDSE_CLIENT_SECRET='local-secret'\n", encoding="utf-8")
    monkeypatch.setenv("CDSE_CLIENT_ID", "shell-id")
    monkeypatch.delenv("CDSE_CLIENT_SECRET", raising=False)
    load_local_env(env_file)
    assert os.environ["CDSE_CLIENT_ID"] == "shell-id"
    assert os.environ["CDSE_CLIENT_SECRET"] == "local-secret"


def test_statistical_response_is_closed_after_each_territory_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            self.closed = True

    response = Response()
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density") | {"years": [2023]}
    territory = {"territory_id": "it:municipality:000001", "territory_version_id": "it:municipality:000001@2023-01-01", "level": "municipality", "geometry_wkb": Polygon([(12, 41), (12.1, 41), (12.1, 41.1), (12, 41.1)]).wkb}
    monkeypatch.setattr(forests, "_post_statistics", lambda *_: response)
    monkeypatch.setattr(forests, "_statistical_response", lambda *_: [{"mean": 20, "percentiles": {"25.0": 10, "50.0": 20, "75.0": 30}}])

    records = forests._statistical_records(asset, territory, "fake-token", "source-hash")

    assert response.closed
    assert [record["metric_id"] for record in records] == ["tree_cover_mean", "tree_cover_p25", "tree_cover_p50", "tree_cover_p75"]


def test_statistical_checkpoint_reuses_only_complete_matching_records(tmp_path: Path) -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density") | {"years": [2023]}
    territory = {"territory_id": "it:municipality:000001", "territory_version_id": "it:municipality:000001@2023-01-01"}
    source_hash = "a" * 64
    records = [{"territory_version_id": territory["territory_version_id"], "source_asset_sha256": source_hash, "metric_id": metric} for metric in ("tree_cover_mean", "tree_cover_p25", "tree_cover_p50", "tree_cover_p75")]

    _write_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, source_hash, records)

    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, source_hash, force=False) == records
    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, "b" * 64, force=False) is None
    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, source_hash, force=True) is None
