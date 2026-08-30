from pathlib import Path
import json
import os

import pandas as pd
import pytest
from shapely.geometry import Polygon

from stato_italia.cli import load_local_env
import stato_italia.forests as forests
from stato_italia.forests import CORINE, HRL, _check_catalog, _persist_catalog, _process_payload, _process_tile_grid, _read_statistical_checkpoint, _reference_years_for_asset, _stats_payload, _write_statistical_checkpoint


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


def test_statistical_api_refreshes_expired_token_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.headers: dict[str, str] = {}
            self.closed = False

        def close(self) -> None:
            self.closed = True

    issued = iter(["expired", "fresh"])
    monkeypatch.setattr(forests, "_cdse_token", lambda _source: next(issued))
    tokens = forests._CdseTokenProvider(HRL)
    responses = [Response(401), Response(200)]
    authorizations: list[str] = []

    def post(*_args: object, **kwargs: object) -> Response:
        authorizations.append(kwargs["headers"]["Authorization"])  # type: ignore[index]
        return responses.pop(0)

    monkeypatch.setattr(forests.requests, "post", post)

    response = forests._post_statistics({"request": "payload"}, tokens)

    assert response.status_code == 200
    assert authorizations == ["Bearer expired", "Bearer fresh"]


def test_statistical_checkpoint_reuses_only_complete_matching_records(tmp_path: Path) -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density") | {"years": [2023]}
    territory = {"territory_id": "it:municipality:000001", "territory_version_id": "it:municipality:000001@2023-01-01"}
    source_hash = "a" * 64
    records = [{"territory_version_id": territory["territory_version_id"], "source_asset_sha256": source_hash, "metric_id": metric} for metric in ("tree_cover_mean", "tree_cover_p25", "tree_cover_p50", "tree_cover_p75")]

    _write_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, source_hash, records)

    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, source_hash, force=False) == records
    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, "b" * 64, force=False) is None
    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, source_hash, force=True) is None


def test_catalog_preflight_is_read_only_and_run_regenerates_canonical_from_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path = tmp_path / "raw" / HRL["source_id"] / "catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps({
        "source_id": HRL["source_id"], "signature": "1" * 64,
        "products": [{"Id": "v1", "Name": "V1"}], "checked_at": "2026-01-01T00:00:00Z",
    }))
    cached = tmp_path / "canonical" / "forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    cached.parent.mkdir(parents=True)
    pd.DataFrame({
        "derived_metric_id": ["v1"], "territory_level": ["region"], "reference_year": [2023],
        "source_asset_sha256": ["1" * 64],
    }).to_parquet(cached)
    products_v2 = [{
        "Id": "v2", "Name": "V2", "ContentDate": None, "Checksum": None,
        "S3Path": None, "OriginDate": None,
    }]
    monkeypatch.setattr(forests, "_catalog_products", lambda _source, _token: products_v2)

    remote = _check_catalog(HRL, "token")

    assert json.loads(catalog_path.read_text())["signature"] == "1" * 64
    persisted = _persist_catalog(tmp_path, remote)
    assert persisted["changed"] is True
    monkeypatch.setattr(forests, "_cdse_token", lambda _source: "token")
    monkeypatch.setattr(forests, "_slice_territories", lambda *_: pd.DataFrame([{
        "territory_id": "it:region:01", "territory_version_id": "it:region:01@2023-01-01",
        "level": "region",
    }]))
    monkeypatch.setattr(forests, "_read_statistical_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(forests, "_write_statistical_checkpoint", lambda *_args, **_kwargs: None)

    def records(asset: dict, territory: dict, _token: str, source_hash: str) -> list[dict]:
        return [{
            "derived_metric_id": asset["id"], "territory_id": territory["territory_id"],
            "territory_version_id": territory["territory_version_id"], "territory_level": territory["level"],
            "reference_year": 2023, "source_asset_sha256": source_hash,
        }]

    monkeypatch.setattr(forests, "_statistical_records", records)
    result = forests.ingest_forests(
        tmp_path, tmp_path / "canonical", force=False, mode="statistical-api",
    )

    regenerated = pd.read_parquet(cached)
    assert result["changed"] is True
    assert set(regenerated["source_asset_sha256"]) == {remote["signature"]}
