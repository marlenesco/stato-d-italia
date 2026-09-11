from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio
from pyproj import Transformer
from rasterio.io import MemoryFile
from rasterio.transform import from_origin
from shapely.geometry import box
from shapely.ops import transform

from stato_italia import forests, forests_legacy as legacy
from stato_italia.territories import territory_reference_date


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "0")
    monkeypatch.setenv("FORESTS_RAW_RETENTION", "retain")
    monkeypatch.setenv("FOREST_COVERAGE_MODE", "national")
    monkeypatch.setattr(legacy.requests.Session, "request", lambda *a, **k: pytest.fail("Live network forbidden"))


class Response:
    status_code = 200

    def __init__(self, payload=None, data=b""):
        self.payload, self.data, self.closed = payload, data, False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True

    def iter_content(self, **kwargs):
        yield self.data


class Client:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.responses.pop(0)


def zip_bytes(asset, values=None, *, crs="EPSG:3035", resolution=None, count=1, nodata=255, extra=False):
    values = values if values is not None else [0, 1, 2, 3, 254, 255]
    array = np.array([values], dtype="uint8")
    with MemoryFile() as memory:
        with memory.open(driver="GTiff", width=len(values), height=1, count=count,
                         crs=crs, transform=from_origin(4500000, 2500000, resolution or asset["resolution_m"], resolution or asset["resolution_m"]),
                         dtype="uint8", nodata=nodata) as dataset:
            for band in range(1, count + 1):
                dataset.write(array, band)
        data = memory.read()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("unknown/internal-name.tif", data)
        if extra:
            bundle.writestr("another.tif", data)
    return output.getvalue()


def test_four_exact_product_mappings_and_distinct_assets():
    expected = [
        ("b903be8a861d48d9af41266ce63cc287", "266be23f-29a1-41f8-899d-a57c35d572fc", "TCD_2012_020m_eu_03035_d03_Full"),
        ("860eee4b9af64f6283e8097f533456f9", "245b8a61-e053-4509-b7c6-b79294d93576", "TCD_2015_020m_eu_03035_d05_Full"),
        ("6606864bf28345438b7fc091ddb0a445", "b29631a1-ae8c-42f9-8206-f10bb752ee52", "FTY_2012_100m_eu_03035_d02_Full"),
        ("c53f82d466354da09de7c7e4ca44b030", "d09e3605-92d8-4e6a-a401-220e2e4581e9", "FTY_2015_100m_eu_03035_d02_Full"),
    ]
    actual = []
    for asset in legacy.LEGACY["assets"]:
        assert asset["years"] == [2012, 2015]
        assert set(asset["products"]) == {2012, 2015}
        assert "byoc_collection_id" not in asset
        for year in asset["years"]:
            contract = legacy.product_contract(asset, year)
            actual.append(tuple(contract["product"][key] for key in ("DatasetID", "FileID", "name")))
            assert contract["territory_reference_year"] == year
            assert contract["series_break_to_modern"] == ["methodology", "spatial_resolution"]
    assert actual == expected
    assert {a["id"] for a in legacy.LEGACY["assets"]}.isdisjoint({a["id"] for a in forests.HRL["assets"]})
    assert legacy.LEGACY["source_id"] != forests.HRL["source_id"]
    assert legacy.LEGACY["methodology_family"] == "copernicus_hrl_forest_legacy_2012_2015"


def test_poll_matches_completed_task_and_closes_responses():
    responses = [Response({"TaskID": "wanted"}), Response({"items": [{"TaskID": "other", "DownloadURL": "https://example.org/wrong"}]}),
                 Response({"items": [{"TaskID": "wanted", "DownloadURL": "https://example.org/right?secret=opaque"}]})]
    client = Client(*responses)
    task, url = legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=client,
                                            token_provider=lambda: "fake-bearer", sleep=lambda _: None)
    assert task == "wanted" and url.endswith("right?secret=opaque")
    assert client.calls[0][1]["json"] == {"Datasets": [{"DatasetID": "b903be8a861d48d9af41266ce63cc287", "FileID": "266be23f-29a1-41f8-899d-a57c35d572fc"}]}
    assert all(call[1]["params"] == {"status": "Finished_ok"} for call in client.calls[1:])
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("payload", [None, {}, {"items": [{}]}, {"items": [{"TaskID": "wanted"}]},
    {"items": [{"TaskID": "wanted", "DownloadURL": "http://bad"}]},
    {"items": [{"TaskID": "wanted"}, {"TaskID": "wanted"}]}])
def test_malformed_or_ambiguous_poll_fails(payload):
    with pytest.raises(ValueError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=Client(Response({"TaskID": "wanted"}), Response(payload)), token_provider=lambda: "fake")


@pytest.mark.parametrize("payload", [None, {}, [], [{"TaskID": "a"}, {"TaskID": "b"}], {"TaskID": 1}])
def test_malformed_submission_fails(payload):
    with pytest.raises(ValueError, match="TaskID"):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=Client(Response(payload)), token_provider=lambda: "fake")


def test_poll_bound_and_redaction(caplog):
    client = Client(Response({"TaskID": "wanted"}), Response([]), Response([]))
    with pytest.raises(TimeoutError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=client,
                                    token_provider=lambda: "fake", max_polls=2, sleep=lambda _: None)
    def failing_token():
        raise RuntimeError("secret-token private-key https://example.org/?secret=1")
    with pytest.raises(ValueError) as error:
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=Client(), token_provider=failing_token)
    assert "secret-token" not in str(error.value) + caplog.text
    assert "private-key" not in str(error.value) + caplog.text
    assert error.value.__suppress_context__


@pytest.mark.parametrize("asset", legacy.LEGACY["assets"])
def test_zip_accepts_unknown_internal_name(tmp_path, asset):
    archive = tmp_path / "product.zip"
    archive.write_bytes(zip_bytes(asset))
    assert len(legacy.extract_validated_raster(archive, tmp_path / "raster.tif", asset)) == 64


@pytest.mark.parametrize("overrides", [{"crs": "EPSG:4326"}, {"resolution": 10}, {"extra": True}, {"count": 2}, {"nodata": 0}, {"values": [101]}, {"values": [253]}])
def test_validator_rejects_incompatible_raster(tmp_path, overrides):
    asset = legacy.LEGACY["assets"][0]
    archive = tmp_path / "product.zip"
    archive.write_bytes(zip_bytes(asset, **overrides))
    raster = tmp_path / "raster.tif"
    with pytest.raises(ValueError):
        legacy.extract_validated_raster(archive, raster, asset)
    assert not raster.exists()


def retain(root, asset, year, values=None):
    archive = legacy.raw_path(root, asset, year)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(zip_bytes(asset, values))
    raster = archive.parent / "temporary.tif"
    raster_hash = legacy.extract_validated_raster(archive, raster, asset)
    raster.unlink()
    archive.with_suffix(".zip.metadata.json").write_text(json.dumps({
        "contract": legacy.product_contract(asset, year), "sha256": legacy.sha256_file(archive),
        "bytes": archive.stat().st_size, "raster_sha256": raster_hash,
    }))
    return archive


def population(year, resolution=100):
    project = Transformer.from_crs(3035, 4326, always_xy=True).transform
    geometry = transform(project, box(4500000, 2500000 - resolution, 4500000 + 6 * resolution, 2500000))
    return pd.DataFrame([{
        "territory_id": f"it:{level}:{code}", "territory_version_id": f"it:{level}:{code}@{territory_reference_date(year)}",
        "level": level, "istat_code": code, "region_istat_code": "01", "geometry_wkb": geometry.wkb,
    } for level, code in (("region", "01"), ("province", "001"), ("municipality", "001001"))])


@pytest.mark.parametrize("kind,expected", [("tree_cover_density", 25.0), ("forest_type", 3.0)])
def test_zonal_zero_valid_invalid_codes_excluded_and_exact_years(tmp_path, monkeypatch, kind, expected):
    asset = next(a for a in legacy.LEGACY["assets"] if a["kind"] == kind)
    monkeypatch.setitem(legacy.LEGACY, "assets", [asset])
    values = [0, 0, 0, 100, 254, 255] if kind == "tree_cover_density" else [0, 1, 2, 3, 254, 255]
    for year in (2012, 2015):
        retain(tmp_path, asset, year, values)
    seen = []
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", lambda _, year: seen.append(year) or population(year, asset["resolution_m"]))
    monkeypatch.setattr(forests, "_expected_region_codes", lambda *_: {"01"})
    rows, coverage, regions = legacy.legacy_zonal_records(tmp_path, tmp_path / "canonical")
    assert seen == [2012, 2015]
    metric = "tree_cover_mean" if kind == "tree_cover_density" else "forest_area_ha"
    assert all(row["value_decimal"] == pytest.approx(expected) for row in rows if row["metric_id"] == metric)
    if kind == "forest_type":
        assert all(row["value_decimal"] == pytest.approx(50) for row in rows if row["metric_id"] == "forest_share_pct")
        assert all(row["value_decimal"] == 1 for row in rows if row["metric_id"] in {"broadleaved_area_hrl_ha", "coniferous_area_hrl_ha", "mixed_forest_area_hrl_ha"})
    assert all(row["dataset_id"] == legacy.LEGACY["source_id"] for row in rows)
    assert all(row["methodology_family"] == legacy.LEGACY["methodology_family"] for row in rows)
    assert all(entry["validNoDataTerritoryIds"] == [] for entry in coverage)
    assert set(regions) == {2012, 2015}


def test_all_nodata_has_coverage_without_numeric_zero(tmp_path, monkeypatch):
    asset = legacy.LEGACY["assets"][0]
    monkeypatch.setitem(legacy.LEGACY, "assets", [asset])
    for year in (2012, 2015):
        retain(tmp_path, asset, year, [254, 255, 254, 255, 254, 255])
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", lambda _, year: population(year, 20))
    monkeypatch.setattr(forests, "_expected_region_codes", lambda *_: {"01"})
    rows, coverage, _ = legacy.legacy_zonal_records(tmp_path, tmp_path)
    assert not rows
    assert all(entry["validNoDataTerritoryIds"] == entry["expectedTerritoryIds"] for entry in coverage)


def test_acquisition_mocked_and_secret_free_provenance(tmp_path):
    asset = legacy.LEGACY["assets"][0]
    responses = [Response({"TaskID": "wanted"}), Response([{"TaskID": "wanted", "DownloadURL": "https://example.org/download?secret=123"}]), Response(data=zip_bytes(asset))]
    client = Client(*responses)
    result = legacy.acquire_product(tmp_path, asset, 2012, client=client, token_provider=lambda: "fake-bearer")
    assert result["changed"]
    assert "headers" not in client.calls[-1][1]
    assert "secret=123" not in json.dumps(result)
    assert "fake-bearer" not in json.dumps(result)
    assert all(r.closed for r in responses)
    assert not legacy.acquire_product(tmp_path, asset, 2012, offline=True)["changed"]
    Path(result["local_path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="provenance"):
        legacy.acquire_product(tmp_path, asset, 2012, offline=True)


def test_enabled_years_include_exact_legacy_years(monkeypatch):
    assert forests.forest_zonal_territory_years() == set(range(2018, 2025))
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    assert forests.forest_zonal_territory_years() == {2012, 2015, *range(2018, 2025)}


def test_combined_canonical_separates_legacy_and_modern_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    for asset in legacy.LEGACY["assets"]:
        for year in asset["years"]:
            retain(tmp_path, asset, year)
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", lambda _, year: population(year, 20))
    monkeypatch.setattr(forests, "_expected_region_codes", lambda *_: {"01"})
    result = forests.ingest_forests(tmp_path, tmp_path / "canonical", mode="raster")
    table = pd.read_parquet(tmp_path / "canonical/forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet")
    report = json.loads(Path(result["coverage_path"]).read_text())
    modern_asset = forests.HRL["assets"][0] | {"source_id": forests.HRL["source_id"]}
    modern = [forests._record(modern_asset, "modern", "b" * 64, row, "tree_cover_mean", 20, 2018, 2018) for row in population(2018).to_dict("records")]
    entries = report["entries"] + [dict(entry, assetId=modern_asset["id"], period="2018-2018", territoryReferenceYear=2018,
        territoryGeometryReference=f"istat-{entry['territoryLevel']}-2018.pmtiles") for entry in report["entries"] if entry["assetId"] == legacy.LEGACY["assets"][0]["id"] and entry["period"] == "2015-2015"]
    _, snapshots = forests._temporal_diagnostics(pd.concat([table, pd.DataFrame(modern)], ignore_index=True), entries)
    assert all("comparisonWithPrevious" not in item for item in snapshots if item["assetId"] == modern_asset["id"])
    assert result["reference_years"] == [2012, 2015]


def test_legacy_raw_paths_feed_existing_source_state(tmp_path):
    from stato_italia.cli import _declared_raw_paths, build_source_state_from_metadata_paths
    asset = legacy.LEGACY["assets"][0]
    result = legacy.acquire_product(tmp_path, asset, 2012, client=Client(
        Response({"TaskID": "wanted"}), Response([{"TaskID": "wanted", "DownloadURL": "https://example.org/data?secret=x"}]),
        Response(data=zip_bytes(asset))), token_provider=lambda: "fake")
    paths = _declared_raw_paths({"legacy": [result]})
    assert set(paths) == {Path(result["local_path"]), Path(result["metadata_path"])}
    state = build_source_state_from_metadata_paths(tmp_path / "raw", [Path(result["metadata_path"])])
    assert len(state["sources"]) == 1
    assert state["sources"][0]["source_id"] == legacy.LEGACY["source_id"]
    assert "secret=x" not in json.dumps(state)


def test_legacy_delivery_preserves_methodology(tmp_path, monkeypatch):
    from stato_italia.forests_delivery import generate_forests_delivery
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    canonical = tmp_path / "canonical"
    for asset in legacy.LEGACY["assets"]:
        for year in asset["years"]:
            retain(tmp_path, asset, year)
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", lambda _, year: population(year, 20))
    monkeypatch.setattr(forests, "_expected_region_codes", lambda *_: {"01"})
    forests.ingest_forests(tmp_path, canonical, mode="raster")
    geometries = {}
    for year in (2012, 2015):
        for level in forests.MAPPABLE_LEVELS:
            path = canonical / "territories" / f"reference_year={year}" / f"{level}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = population(year)
            frame = frame[frame.level == level].assign(name="Synthetic")
            frame.to_parquet(path)
            geometry = tmp_path / f"istat-{level}-{year}.pmtiles"
            geometry.touch()
            geometries[f"{level}_{year}"] = geometry
    infc = canonical / "forests/infc.parquet"
    pd.DataFrame(columns=["metric_id", "territory_id", "territory_version_id", "territory_level", "period_start", "period_end", "value_decimal", "official_status"]).to_parquet(infc)
    zonal = canonical / "forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    generate_forests_delivery(zonal, infc, canonical, tmp_path / "delivery", "test", geometries, force=True)
    payload = json.loads((tmp_path / "delivery/foreste/maps/tree_cover_mean/2012-2012/region.json").read_text())
    assert payload["territoryReferenceYear"] == 2012
    assert legacy.LEGACY["methodology_family"] in json.dumps(payload)


def test_exact_geometry_rejects_missing_and_wrong_year(tmp_path, monkeypatch):
    asset = legacy.LEGACY["assets"][0]
    retain(tmp_path, asset, 2012)
    with pytest.raises(FileNotFoundError):
        legacy.legacy_zonal_records(tmp_path, tmp_path / "canonical")
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", lambda *_: population(2023))
    with pytest.raises(ValueError, match="exact ISTAT"):
        legacy.legacy_zonal_records(tmp_path, tmp_path / "canonical")


def test_fty_rejects_unknown_classes(tmp_path):
    asset = legacy.LEGACY["assets"][1]
    archive = tmp_path / "product.zip"
    archive.write_bytes(zip_bytes(asset, [4]))
    with pytest.raises(ValueError):
        legacy.extract_validated_raster(archive, tmp_path / "raster.tif", asset)


def test_poll_deadline_and_download_error_redaction(tmp_path, caplog):
    moments = iter([0, 0, 0, 2])
    with pytest.raises(TimeoutError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012,
            client=Client(Response({"TaskID": "wanted"}), Response([])),
            token_provider=lambda: "fake", clock=lambda: next(moments), timeout=1)
    class FailingDownload(Client):
        def request(self, *args, **kwargs):
            if len(self.calls) == 2:
                raise RuntimeError("https://example.org/?secret=123 fake-bearer")
            return super().request(*args, **kwargs)
    with pytest.raises(ValueError) as error:
        legacy.acquire_product(tmp_path, legacy.LEGACY["assets"][0], 2012,
            client=FailingDownload(Response({"TaskID": "wanted"}), Response([{"TaskID": "wanted", "DownloadURL": "https://example.org/?secret=123"}])),
            token_provider=lambda: "fake-bearer")
    assert "secret=123" not in str(error.value) + caplog.text
    assert "fake-bearer" not in str(error.value) + caplog.text
    assert not list(tmp_path.rglob("*.partial"))
    assert not list(tmp_path.rglob("product.zip"))


def test_scoped_fetch_defers_legacy_when_geospatial_not_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    monkeypatch.setattr(forests, "fetch_legacy_forests", lambda *_a, **_k: pytest.fail("Legacy acquisition outside geospatial scope"))
    result = forests.fetch_forests(tmp_path, check_geospatial=False, include_infc=False)
    assert result["legacy"] == []


def test_pipeline_refuses_incremental_legacy_bootstrap_before_io(tmp_path, monkeypatch):
    from argparse import Namespace
    from stato_italia import cli
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    args = Namespace(publish="local", domain="forests", scope=None, plan="modern-plan.json")
    with pytest.raises(ValueError, match="without --plan"):
        cli.run(args)


def test_disabling_legacy_cannot_drop_existing_rows(tmp_path):
    destination = tmp_path / "canonical/forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    destination.parent.mkdir(parents=True)
    pd.DataFrame([{"methodology_version": legacy.LEGACY["assets"][0]["id"]}]).to_parquet(destination)
    before = destination.read_bytes()
    with pytest.raises(ValueError, match="Existing legacy Forest output"):
        forests.ingest_forests(tmp_path, tmp_path / "canonical", force=True)
    assert destination.read_bytes() == before


def test_domain_orchestration_processes_retained_legacy_without_network(tmp_path, monkeypatch):
    from argparse import Namespace
    from stato_italia import cli
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    monkeypatch.setenv("FOREST_PROCESSING_MODE", "raster")
    for asset in legacy.LEGACY["assets"]:
        for year in asset["years"]:
            retain(tmp_path, asset, year)
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", lambda _, year: population(year, 20))
    monkeypatch.setattr(forests, "_expected_region_codes", lambda *_: {"01"})
    monkeypatch.setattr(cli, "active_ingestion_plan", lambda: None)
    monkeypatch.setattr(cli, "fetch_forests", lambda root, **options: forests.fetch_forests(
        root, offline=options["offline"], include_infc=False, check_geospatial=options["check_geospatial"]))
    monkeypatch.setattr(cli, "ingest_infc_forests", lambda *_a, **_k: {"changed": False})
    fetched, infc, zonal = cli._process_geospatial_forest_sources(
        Namespace(force=False, offline=True), root=tmp_path, canonical=tmp_path / "canonical", previous_state=None)
    assert len(fetched["legacy"]) == 4
    assert zonal["reference_years"] == [2012, 2015]
    assert infc == {"changed": False}
