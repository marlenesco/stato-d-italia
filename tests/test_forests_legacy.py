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
    monkeypatch.delenv("CLMS_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("CLMS_SERVICE_KEY", raising=False)
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "0")
    monkeypatch.setenv("FORESTS_RAW_RETENTION", "retain")
    monkeypatch.setenv("FOREST_COVERAGE_MODE", "national")
    monkeypatch.setattr(legacy.requests.Session, "request", lambda *a, **k: pytest.fail("Live network forbidden"))


class Response:
    status_code = 200

    def __init__(self, payload=None, data=b"", status=200):
        self.payload, self.data, self.closed = payload, data, False
        self.status_code = status

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


def submitted():
    return Response({"ErrorTaskIds": [], "TaskIds": [{"TaskID": "65267487597"}]}, status=201)


def completed(url="https://example.org/data?secret=123"):
    return Response({"65267487597": {"Status": "Finished_ok", "DownloadURL": url}})


@pytest.fixture(scope="module")
def service_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {"client_id": "fake-client", "user_id": "fake-user",
            "token_uri": "https://land.copernicus.eu/@@oauth2-token",
            "private_key": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption()).decode()}, key.public_key()


def token_response(token="fake-bearer", lifetime=3600):
    return Response({"access_token": token, "expires_in": lifetime, "token_type": "Bearer"})


def test_service_key_rs256_exchange_cache_and_expiry(monkeypatch, service_key):
    key, public_key = service_key
    monkeypatch.setenv("CLMS_SERVICE_KEY", json.dumps(key))
    now = [1000]
    responses = [token_response(), token_response("renewed-bearer")]
    client = Client(*responses)
    provider = legacy.ClmsTokenProvider(client, clock=lambda: now[0], monotonic=lambda: now[0])
    assert provider() == provider() == "fake-bearer"
    assert len(client.calls) == 1
    args, request = client.calls[0]
    assert args == ("POST", key["token_uri"])
    assert "Authorization" not in request["headers"]
    assert request["verify"] is True and request["allow_redirects"] is False and request["timeout"] == 30
    assert request["data"]["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    claims = legacy.jwt.decode(request["data"]["assertion"], public_key, algorithms=["RS256"],
                               audience=key["token_uri"], options={"verify_exp": False})
    assert claims == {"iss": "fake-client", "sub": "fake-user", "aud": key["token_uri"], "iat": 1000, "exp": 4600}
    now[0] = 4600
    assert provider() == "renewed-bearer"
    assert all(response.closed for response in responses)


def test_expired_bearer_retries_original_request_once(monkeypatch, service_key):
    monkeypatch.setenv("CLMS_SERVICE_KEY", json.dumps(service_key[0]))
    responses = [token_response(), Response(status=401), token_response("new-bearer"), submitted(), completed()]
    client = Client(*responses)
    provider = legacy.ClmsTokenProvider(client)
    assert legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=client, token_provider=provider)[0] == "65267487597"
    assert client.calls[1][0] == client.calls[3][0]
    assert client.calls[1][1]["json"] == client.calls[3][1]["json"]
    assert client.calls[3][1]["headers"]["Authorization"] == "Bearer new-bearer"
    assert "Authorization" not in client.calls[2][1]["headers"]
    assert all(response.closed for response in responses)


def test_repeated_unauthorized_is_bounded(monkeypatch, service_key):
    monkeypatch.setenv("CLMS_SERVICE_KEY", json.dumps(service_key[0]))
    responses = [token_response(), Response(status=401), token_response(), Response(status=401)]
    client = Client(*responses)
    with pytest.raises(ValueError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=client, token_provider=legacy.ClmsTokenProvider(client))
    assert len(client.calls) == 4 and all(response.closed for response in responses)


def test_manual_bearer_override_never_uses_service_key_exchange(monkeypatch):
    monkeypatch.setenv("CLMS_ACCESS_TOKEN", "manual-bearer")
    monkeypatch.setenv("CLMS_SERVICE_KEY", "invalid")
    client = Client(Response(status=401))
    provider = legacy.ClmsTokenProvider(client)
    assert provider() == "manual-bearer"
    with pytest.raises(ValueError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=client, token_provider=provider)
    assert len(client.calls) == 1


def test_acquisition_uses_service_key_without_persisting_auth(tmp_path, monkeypatch, service_key):
    monkeypatch.setenv("CLMS_SERVICE_KEY", json.dumps(service_key[0]))
    asset = legacy.LEGACY["assets"][0]
    client = Client(token_response(), submitted(), completed(), Response(data=zip_bytes(asset)))
    result = legacy.acquire_product(tmp_path, asset, 2012, client=client)
    assert result["changed"] is True
    assert len(client.calls) == 4
    assert "Authorization" not in client.calls[0][1]["headers"]
    assert "headers" not in client.calls[3][1]
    metadata = Path(result["metadata_path"]).read_text()
    assert all(secret not in metadata for secret in ("fake-bearer", "PRIVATE KEY", "secret=123", "assertion"))


def test_bootstrap_asset_failure_stops_remaining_acquisition(tmp_path, monkeypatch):
    calls = []
    def acquire(_root, asset, year, **_kwargs):
        calls.append((asset["id"], year))
        if len(calls) == 3:
            raise ValueError("Invalid third legacy asset")
        return {"changed": True}
    monkeypatch.setattr(legacy, "acquire_product", acquire)
    with pytest.raises(ValueError, match="third legacy asset"):
        legacy.fetch_legacy_forests(tmp_path)
    assert len(calls) == 3


@pytest.mark.parametrize("invalid", ["missing", "json", "private_key", "token_uri", "response", "http", "expiry", "type"])
def test_service_key_failures_are_secret_free(monkeypatch, service_key, invalid, caplog):
    key = dict(service_key[0])
    response = token_response()
    if invalid in {"private_key", "token_uri"}:
        key[invalid] = "secret-private-value"
    monkeypatch.setenv("CLMS_SERVICE_KEY", json.dumps(key))
    if invalid == "missing":
        monkeypatch.delenv("CLMS_SERVICE_KEY")
    if invalid == "json":
        monkeypatch.setenv("CLMS_SERVICE_KEY", "secret-private-value")
    if invalid == "response":
        response.payload = {"error": "secret-private-value"}
    if invalid == "http":
        response.status_code = 403
    if invalid == "expiry":
        response.payload["expires_in"] = -1
    if invalid == "type":
        response.payload["token_type"] = "not-bearer"
    client = Client(response)
    with pytest.raises(ValueError) as error:
        legacy.ClmsTokenProvider(client)()
    assert "secret-private-value" not in str(error.value) + caplog.text
    assert "PRIVATE KEY" not in str(error.value) + caplog.text
    assert error.value.__suppress_context__
    if invalid in {"token_uri", "private_key", "json", "missing"}:
        assert not client.calls
    else:
        assert response.closed


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
    responses = [submitted(), Response({"other-task": {"Status": "Finished_ok", "DownloadURL": "https://example.org/wrong"}}),
                 completed("https://example.org/right?secret=opaque")]
    client = Client(*responses)
    task, url = legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=client,
                                            token_provider=lambda: "fake-bearer", sleep=lambda _: None)
    assert task == "65267487597" and url.endswith("right?secret=opaque")
    assert client.calls[0][1]["json"] == {"Datasets": [{"DatasetID": "b903be8a861d48d9af41266ce63cc287", "FileID": "266be23f-29a1-41f8-899d-a57c35d572fc"}]}
    assert all(call[1]["params"] == {"status": "Finished_ok"} for call in client.calls[1:])
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("payload", [None, [], {"65267487597": None}, {"65267487597": []},
    {"65267487597": {}},
    {"65267487597": {"Status": "In_progress", "DownloadURL": "https://example.org/?secret=x"}},
    {"65267487597": {"Status": "Finished_err", "DownloadURL": "https://example.org/?secret=x"}},
    *[{"65267487597": {"Status": "Finished_ok", "DownloadURL": url}} for url in
      (None, [], "", "http://bad", "https://user:password@example.org/", "https://example.org/\nsecret")],
    {"65267487597": {"Status": "Finished_ok"}}])
def test_malformed_or_ambiguous_poll_fails(payload):
    with pytest.raises(ValueError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=Client(submitted(), Response(payload)), token_provider=lambda: "fake")


@pytest.mark.parametrize("payload", [None, {}, [],
    {"ErrorTaskIds": ["error"], "TaskIds": [{"TaskID": "65267487597"}]},
    {"ErrorTaskIds": None, "TaskIds": [{"TaskID": "65267487597"}]},
    {"TaskIds": [{"TaskID": "65267487597"}]},
    *[{"ErrorTaskIds": [], "TaskIds": tasks} for tasks in
      (None, {}, [], [{"TaskID": "a"}, {"TaskID": "b"}], [None], [{}],
       [{"TaskID": 1}], [{"TaskID": ""}], [{"TaskID": "with space"}])]])
def test_malformed_submission_fails(payload):
    with pytest.raises(ValueError, match="TaskID"):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=Client(Response(payload, status=201)), token_provider=lambda: "fake")


def test_poll_bound_and_redaction(caplog):
    client = Client(submitted(), Response({}), Response({}))
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


@pytest.mark.parametrize("method,status", [("POST", 200), ("POST", 400), ("GET", 201), ("GET", 403), ("GET", 500)])
def test_clms_expected_http_status_and_redaction(method, status, caplog):
    response = submitted() if method == "POST" else completed()
    response.status_code = status
    response.payload = {"server_error": "secret-token https://example.org/?secret=123"}
    client = Client(response) if method == "POST" else Client(submitted(), response)
    with pytest.raises(ValueError) as error:
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, client=client, token_provider=lambda: "secret-token")
    assert "secret-token" not in str(error.value) + caplog.text
    assert "secret=123" not in str(error.value) + caplog.text
    assert response.closed


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
        "source_id": legacy.LEGACY["source_id"], "source_signature": legacy.contract_signature(asset, year),
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
    responses = [submitted(), completed(), Response(data=zip_bytes(asset))]
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
        submitted(), completed("https://example.org/data?secret=x"),
        Response(data=zip_bytes(asset))), token_provider=lambda: "fake")
    paths = _declared_raw_paths({"legacy": [result]})
    assert set(paths) == {Path(result["local_path"]), Path(result["metadata_path"])}
    state = build_source_state_from_metadata_paths(tmp_path / "raw", [Path(result["metadata_path"])])
    assert len(state["sources"]) == 1
    assert state["sources"][0]["source_id"] == legacy.LEGACY["source_id"]
    assert state["sources"][0]["source_signature"] == legacy.contract_signature(asset, 2012)
    assert "secret=x" not in json.dumps(state)


@pytest.mark.parametrize("invalid", [None, "state", "modern", "coverage", "contract", "geometry", "break"])
def test_legacy_delivery_preserves_methodology(tmp_path, monkeypatch, invalid):
    from stato_italia.forests_delivery import generate_forests_delivery
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    canonical = tmp_path / "canonical"
    for asset in legacy.LEGACY["assets"]:
        for year in asset["years"]:
            retain(tmp_path, asset, year)
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", lambda _, year: population(year, 100))
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

    # Add an unchanged synthetic H1H baseline to the actual legacy canonical and delivery.
    monkeypatch.setattr(forests, "_slice_territories", lambda _, year: population(year, 100))
    legacy_table = pd.read_parquet(zonal)
    report_path = forests.forest_coverage_report_path(zonal)
    report = json.loads(report_path.read_text())
    modern_rows = []
    for asset in forests.HRL["assets"]:
        if not asset.get("statistical_api_enabled", True):
            continue
        for start, end in forests._asset_periods(asset):
            for territory in population(end).to_dict("records"):
                for metric in forests._FOREST_METRICS[asset["kind"]]:
                    modern_rows.append(forests._record(asset | {"source_id": forests.HRL["source_id"]}, "active-manifest", "a" * 64,
                        territory, metric, float(end), start, end))
            for level in forests.MAPPABLE_LEVELS:
                expected = list(population(end).query("level == @level").territory_id)
                report["entries"].append({"assetId": asset["id"], "period": f"{start}-{end}", "territoryLevel": level,
                    "territoryReferenceYear": end, "territoryGeometryReference": f"istat-{level}-{end}.pmtiles",
                    "expectedTerritoryIds": expected, "numericTerritoryIds": expected, "validNoDataTerritoryIds": []})
                territory_path = canonical / "territories" / f"reference_year={end}" / f"{level}.parquet"
                territory_path.parent.mkdir(parents=True, exist_ok=True)
                population(end).query("level == @level").assign(name="Synthetic").to_parquet(territory_path)
                geometry = tmp_path / f"istat-{level}-{end}.pmtiles"
                geometry.touch()
                geometries[f"{level}_{end}"] = geometry
    baseline = pd.DataFrame(modern_rows)
    combined = pd.concat([legacy_table, baseline], ignore_index=True)
    combined.to_parquet(zonal)
    report = forests._coverage_report(combined, report["entries"], {year: {"01"} for year in (2012, 2015, *range(2018, 2025))})
    report_path.write_text(json.dumps(report))
    generate_forests_delivery(zonal, infc, canonical, tmp_path / "delivery", "test", geometries, force=True)
    from stato_italia.cli import build_source_state_from_metadata_paths
    sidecars = [legacy.raw_path(tmp_path, asset, year).with_suffix(".zip.metadata.json")
                for asset in legacy.LEGACY["assets"] for year in asset["years"]]
    state = build_source_state_from_metadata_paths(tmp_path / "raw", sidecars)
    if invalid == "state":
        state["sources"][0]["sha256"] = "b" * 64
    elif invalid == "modern":
        combined.loc[combined.dataset_id == forests.HRL["source_id"], "value_decimal"] = -1
    elif invalid == "contract":
        combined.loc[combined.dataset_id == legacy.LEGACY["source_id"], "source_product_json"] = "{}"
    elif invalid == "geometry":
        combined.loc[combined.dataset_id == legacy.LEGACY["source_id"], "territory_version_id"] = "wrong@2025-01-01"
    elif invalid == "coverage":
        report["coverageMode"] = "development_slice"
    elif invalid == "break":
        report["snapshotDiagnostics"].append({"period": "2018-2018", "comparisonWithPrevious": {"period": "2015-2015"}})
    combined.to_parquet(zonal)
    report_path.write_text(json.dumps(report))
    if invalid:
        with pytest.raises(ValueError, match="Legacy bootstrap"):
            legacy.validate_bootstrap_candidate(tmp_path, state, baseline)
    else:
        assert set(zip(legacy_table.methodology_version, legacy_table.reference_year)) == {
            (asset["id"], year) for asset, year in legacy.expected_legacy_assets().values()
        }
        evidence = legacy.validate_bootstrap_candidate(tmp_path, state, baseline)
        assert len(evidence["assets"]) == 4
        assert evidence["legacyRows"] == 60
        assert evidence["legacyDeliveryMaps"] == 60
        assert evidence["modernRowsUnchanged"] == len(baseline)
        assert all(item["zipBytes"] > 0 for item in evidence["assets"])
        assert all(item["numericCount"] + item["validNoDataCount"] == item["expectedCount"] for item in evidence["coverage"])
        from stato_italia.source_state import check_persisted_sources
        preflight = check_persisted_sources(state, scope="geospatial", families={"copernicus"})
        assert preflight["sourcesUnchanged"] == 4 and preflight["sourceChecks"] == 0
        assert preflight["changed"] is False
        assert all(result["changed"] is False for result in legacy.fetch_legacy_forests(tmp_path))


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
            client=Client(submitted(), Response({})),
            token_provider=lambda: "fake", clock=lambda: next(moments), timeout=1)
    class FailingDownload(Client):
        def request(self, *args, **kwargs):
            if len(self.calls) == 2:
                raise RuntimeError("https://example.org/?secret=123 fake-bearer")
            return super().request(*args, **kwargs)
    with pytest.raises(ValueError) as error:
        legacy.acquire_product(tmp_path, legacy.LEGACY["assets"][0], 2012,
            client=FailingDownload(submitted(), completed()),
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
    args = Namespace(publish="local", domain="forests", scope=None, plan="modern-plan.json",
                     workdir=str(tmp_path / "data"), output=str(tmp_path / "artifacts"), release_id="test")
    monkeypatch.setattr(cli, "LocalObjectStore", lambda *_: object())
    monkeypatch.setattr(cli, "_active_source_state_with_legacy_bootstrap", lambda *_: None)
    monkeypatch.setattr(cli, "load_ingestion_plan", lambda *_a, **_k: pytest.fail("Plan I/O before bootstrap"))
    with pytest.raises(ValueError, match="without --plan"):
        cli.run(args)


def legacy_state():
    return {"schemaVersion": 1, "sources": [
        {"source_id": legacy.LEGACY["source_id"], "asset_path": path, "sha256": "a" * 64,
         "bytes": 123, "source_signature": legacy.contract_signature(asset, year),
         "resolved_url": "https://example.org/must-not-be-requested?secret=x"}
        for path, (asset, year) in legacy.expected_legacy_assets().items()
    ]}


@pytest.mark.parametrize("complete", [False, True])
def test_planned_run_requires_complete_active_legacy_state(tmp_path, monkeypatch, complete):
    from argparse import Namespace
    from stato_italia import cli
    monkeypatch.setenv("FOREST_LEGACY_ENABLED", "1")
    state = legacy_state()
    if not complete:
        state["sources"].pop()
    monkeypatch.setattr(cli, "LocalObjectStore", lambda *_: object())
    monkeypatch.setattr(cli, "_active_source_state_with_legacy_bootstrap", lambda *_: state)
    monkeypatch.setattr(cli, "active_release", lambda *_: {"releaseId": "active"})
    monkeypatch.setattr(cli, "load_ingestion_plan", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_validate_domain_plan", lambda *_: None)
    monkeypatch.setattr(cli, "active_ingestion_plan", lambda: {"changed": False})
    monkeypatch.setattr(cli, "_planned_noop_report", lambda *_a, **_k: 0)
    monkeypatch.setattr(cli, "_run_geospatial", lambda *_a, **_k: pytest.fail("No-op must not ingest"))
    args = Namespace(publish="local", domain="forests", scope=None, plan="plan.json", force=False,
                     workdir=str(tmp_path / "data"), output=str(tmp_path / "artifacts"), release_id="test")
    if complete:
        assert cli.run(args) == 0
    else:
        with pytest.raises(ValueError, match="without --plan"):
            cli.run(args)


@pytest.mark.parametrize("invalid", ["wrong_source", "duplicate", "unknown_path"])
def test_active_legacy_completeness_rejects_invalid_entries(invalid):
    state = legacy_state()
    if invalid == "wrong_source":
        state["sources"][0]["source_id"] = "copernicus-hrl-forests"
    elif invalid == "duplicate":
        state["sources"].append(state["sources"][0])
    else:
        state["sources"][0]["asset_path"] = "unknown/product.zip"
    assert not legacy.legacy_state_complete(state)


@pytest.mark.parametrize("changed", [False, True])
def test_legacy_preflight_pins_contract_without_http(monkeypatch, changed):
    from stato_italia import source_state
    state = legacy_state()
    if changed:
        asset = legacy.LEGACY["assets"][0]
        monkeypatch.setitem(asset, "native_resolution_m", 99)
    monkeypatch.setattr(source_state.requests, "get", lambda *_a, **_k: pytest.fail("Pinned contract attempted GET"))
    result = source_state.check_persisted_sources(state, scope="geospatial")
    assert result["sourceChecks"] == 0
    assert result["sourcesChanged"] == (2 if changed else 0)
    assert result["sourcesUnchanged"] == (2 if changed else 4)
    assert result["changed"] == changed
    assert all(item["checked"] is False and item["method"] == "legacy_pinned_contract" for item in result["sources"])
    assert "secret=x" not in json.dumps(result)


@pytest.mark.parametrize("invalid", ["missing_signature", "invalid_signature", "unknown_path", "missing_path", "non_string_path"])
def test_legacy_preflight_fails_closed_for_invalid_contract(monkeypatch, invalid):
    from stato_italia import source_state
    state = legacy_state()
    entry = state["sources"][0]
    if invalid == "missing_signature":
        entry.pop("source_signature")
    elif invalid == "invalid_signature":
        entry["source_signature"] = "z" * 64
    elif invalid == "unknown_path":
        entry["asset_path"] = "copernicus-hrl-forests-legacy/unconfigured/2012/product.zip"
    elif invalid == "missing_path":
        entry.pop("asset_path")
    else:
        entry["asset_path"] = []
    monkeypatch.setattr(source_state.requests, "get", lambda *_a, **_k: pytest.fail("Invalid legacy entry attempted GET"))
    result = source_state.check_persisted_sources(state, scope="geospatial")
    assert result["sourcesUnverifiable"] == 1
    assert result["sources"][0]["status"] == "unverifiable"
    assert result["sources"][0]["checked"] is False
    assert result["sourceChecks"] == 0


def test_contract_signature_is_stable_under_mapping_order():
    asset = legacy.LEGACY["assets"][0]
    reordered = dict(reversed(list(asset.items())))
    assert legacy.contract_signature(asset, 2012) == legacy.contract_signature(reordered, 2012)
    assert legacy.contract_signature(asset, 2012) != legacy.contract_signature(asset, 2015)


def test_unchanged_legacy_raw_hydration_reuses_zip_without_clms(tmp_path, monkeypatch):
    import shutil
    from stato_italia import cli
    published = tmp_path / "published"
    clean = tmp_path / "clean"
    for asset in legacy.LEGACY["assets"]:
        for year in asset["years"]:
            retain(published, asset, year)
    entries = [entry | {"status": "unchanged"} for entry in legacy_state()["sources"]]
    entries.append({"source_id": "copernicus-hrl-forests", "asset_path": "modern/tile.tif", "status": "changed"})
    monkeypatch.setattr(cli, "planned_entries", lambda: entries)
    def hydrate(_store, root, paths):
        for path in paths:
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(published / path, destination)
    monkeypatch.setattr(cli, "_hydrate", hydrate)
    cli._hydrate_planned_raw_dependencies(object(), clean, {"copernicus"}, source_ids={legacy.LEGACY["source_id"]})
    monkeypatch.setattr(legacy, "environment_token", lambda: pytest.fail("Retained ZIP requires no token"))
    results = legacy.fetch_legacy_forests(clean)
    assert len(results) == 4 and all(result["changed"] is False for result in results)
    assert all(result["source_signature"] == legacy.contract_signature(asset, year)
               for result, (asset, year) in zip(results, legacy.expected_legacy_assets().values(), strict=True))


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
