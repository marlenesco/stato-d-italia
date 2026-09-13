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
    monkeypatch.delenv("CLMS_SERVICE_KEY_JSON", raising=False)
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


def completed(url="https://example.org/data?secret=123", **extra):
    return task_response("Finished_ok", DownloadURL=url, **extra)


def task_response(status, **extra):
    product = legacy.LEGACY["assets"][0]["products"][2012]
    return Response({"Status": status,
                     "Datasets": [{"DatasetID": product["DatasetID"], "FileID": product["FileID"]}],
                     "FileSize": len(zip_bytes(legacy.LEGACY["assets"][0])), **extra})


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


@pytest.mark.parametrize("token_uri", ["https://land.copernicus.eu/@@oauth2-token", "https://auth.example.org:8443/token?realm=clms"])
@pytest.mark.parametrize("token_type", ["Bearer", "bearer", "BEARER"])
def test_service_key_rs256_exchange_cache_and_expiry(monkeypatch, service_key, token_uri, token_type):
    original_key, public_key = service_key
    key = original_key | {"token_uri": token_uri, "ignored_extra": {"arbitrary": True}}
    assert legacy.LEGACY["service_key_environment"] == "CLMS_SERVICE_KEY_JSON"
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(key))
    now = [1000]
    responses = [token_response(), token_response("renewed-bearer")]
    for response in responses:
        response.payload["token_type"] = token_type
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


def test_expired_bearer_retries_original_request_once(monkeypatch, service_key, tmp_path):
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(service_key[0]))
    responses = [token_response(), Response(status=401), token_response("new-bearer"), submitted(), completed()]
    client = Client(*responses)
    provider = legacy.ClmsTokenProvider(client)
    assert legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=client, token_provider=provider)[0] == "65267487597"
    assert client.calls[1][0] == client.calls[3][0]
    assert client.calls[1][1]["json"] == client.calls[3][1]["json"]
    assert client.calls[3][1]["headers"]["Authorization"] == "Bearer new-bearer"
    assert "Authorization" not in client.calls[2][1]["headers"]
    assert all(response.closed for response in responses)


def test_repeated_unauthorized_is_bounded(monkeypatch, service_key, tmp_path):
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(service_key[0]))
    responses = [token_response(), Response(status=401), token_response(), Response(status=401)]
    client = Client(*responses)
    with pytest.raises(ValueError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=client, token_provider=legacy.ClmsTokenProvider(client))
    assert len(client.calls) == 4 and all(response.closed for response in responses)


def test_acquisition_uses_service_key_without_persisting_auth(tmp_path, monkeypatch, service_key):
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(service_key[0]))
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
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(key))
    if invalid == "missing":
        monkeypatch.delenv("CLMS_SERVICE_KEY_JSON")
    if invalid == "json":
        monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", "secret-private-value")
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
    visible = str(error.value) + caplog.text
    assert service_key[0]["private_key"] not in visible
    assert "fake-bearer" not in visible
    for _, request in client.calls:
        assert request["data"]["assertion"] not in visible
    assert "PRIVATE KEY" not in visible
    assert error.value.__suppress_context__
    if invalid in {"token_uri", "private_key", "json", "missing"}:
        assert not client.calls
    else:
        assert response.closed



@pytest.mark.parametrize("token_uri", [
    "http://auth.example.org/token", "https:///token",
    "https://user:password@auth.example.org/token", "https://@auth.example.org/token",
    "https://auth.example.org/token#fragment", "https://auth.example.org/token#",
    "https://auth.example.org:invalid/token", "https://auth.example.org:99999/token",
    "https://auth.example.org/token\n",
])
def test_service_key_rejects_invalid_token_uri(monkeypatch, service_key, token_uri):
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(service_key[0] | {"token_uri": token_uri}))
    client = Client()
    with pytest.raises(ValueError, match="authentication unavailable or rejected"):
        legacy.ClmsTokenProvider(client)()
    assert not client.calls


@pytest.mark.parametrize("field", ["client_id", "user_id", "private_key", "token_uri"])
@pytest.mark.parametrize("value", [None, "", 123])
def test_service_key_required_fields_fail_closed(monkeypatch, service_key, field, value):
    key = service_key[0] | {field: value}
    if value is None:
        del key[field]
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(key))
    client = Client()
    with pytest.raises(ValueError, match="authentication unavailable or rejected"):
        legacy.ClmsTokenProvider(client)()
    assert not client.calls


@pytest.mark.parametrize("token_type", [None, 123, "Basic", " Bearer"])
def test_service_key_rejects_wrong_token_type(monkeypatch, service_key, token_type):
    monkeypatch.setenv("CLMS_SERVICE_KEY_JSON", json.dumps(service_key[0]))
    response = token_response()
    response.payload["token_type"] = token_type
    client = Client(response)
    with pytest.raises(ValueError, match="authentication unavailable or rejected"):
        legacy.ClmsTokenProvider(client)()
    assert len(client.calls) == 1 and response.closed


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


def test_pending_persisted_before_poll_and_resume_without_post(tmp_path):
    asset = legacy.LEGACY["assets"][0]
    path = legacy.pending_task_path(tmp_path, asset, 2012)
    class InspectingClient(Client):
        def request(self, method, url, **kwargs):
            if method == "GET":
                state = json.loads(path.read_text())
                assert state == legacy._pending_identity(asset, 2012, "65267487597")
                assert not list(tmp_path.rglob("*.metadata.json"))
            return super().request(method, url, **kwargs)
    first = InspectingClient(submitted(), task_response("Queued"))
    with pytest.raises(TimeoutError, match="pending timeout"):
        legacy.request_download_url(asset, 2012, pending_path=path, client=first,
                                    token_provider=lambda: "fake", max_polls=1)
    assert path.exists()
    second = InspectingClient(task_response("In_progress"), completed())
    assert legacy.request_download_url(asset, 2012, pending_path=path, client=second,
                                       token_provider=lambda: "fake", sleep=lambda _: None)[0] == "65267487597"
    assert all(call[0][0] == "GET" for call in second.calls)
    assert path.exists()  # Resolution alone is not a validated acquisition.
    assert all(secret not in path.read_text() for secret in
               ("DownloadURL", "secret=", "fake", "Authorization", "assertion", "private_key", "bearer"))


@pytest.mark.parametrize("status", ["Finished_err", "Cancelled", "unknown secret=123", "", None])
def test_terminal_status_preserves_task_and_blocks_resubmit(tmp_path, status):
    asset = legacy.LEGACY["assets"][0]
    path = legacy.pending_task_path(tmp_path, asset, 2012)
    for responses in ([submitted(), task_response(status)], [task_response(status)]):
        client = Client(*responses)
        with pytest.raises(ValueError) as error:
            legacy.acquire_product(tmp_path, asset, 2012, client=client, token_provider=lambda: "fake")
        assert "secret=123" not in str(error.value)
        assert path.exists()
        assert sum(call[0][0] == "POST" for call in client.calls) == len(responses) - 1


@pytest.mark.parametrize("invalid", ["json", "schemaVersion", "TaskID", "asset_id", "year",
                                    "DatasetID", "FileID", "contract_signature", "extra"])
def test_invalid_pending_blocks_all_network(tmp_path, invalid):
    asset = legacy.LEGACY["assets"][0]
    path = legacy.pending_task_path(tmp_path, asset, 2012)
    path.parent.mkdir(parents=True)
    state = legacy._pending_identity(asset, 2012, "65267487597")
    state[invalid] = "secret-invalid"
    if invalid == "TaskID":
        state[invalid] = "invalid task id"
    path.write_text("invalid json" if invalid == "json" else json.dumps(state))
    client = Client()
    with pytest.raises(ValueError, match="pending-task state"):
        legacy.acquire_product(tmp_path, asset, 2012, client=client, token_provider=lambda: "fake")
    assert not client.calls
    assert path.exists()


@pytest.mark.parametrize("changes", [
    {"DatasetID": "wrong"}, {"FileID": "wrong"}, {"TaskID": "wrong"},
    {"DatasetID": None}, {"FileID": None},
    *[{"DownloadURL": url} for url in (None, "", "http://example.org/file",
       "https://user:pass@example.org/file", "https://example.org/file#secret",
       "https://example.org:bad/file")],
])
def test_finished_task_identity_and_url_fail_closed(tmp_path, changes):
    response = completed()
    if any(key in changes for key in ("DatasetID", "FileID")):
        response.payload["Datasets"][0].update(changes)
    else:
        response.payload.update(changes)
    client = Client(submitted(), response)
    with pytest.raises(ValueError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012,
            pending_path=tmp_path / "task.pending-task.json", client=client, token_provider=lambda: "fake")


@pytest.mark.parametrize("status", ["Queued", "In_progress", "Finished_ok"])
def test_adoption_validates_without_submit(tmp_path, status):
    asset = legacy.LEGACY["assets"][0]
    client = Client(task_response(status, DownloadURL="https://example.org/?secret=123"))
    legacy.adopt_pending_task(tmp_path, asset, 2012, "65267487597", client=client, token_provider=lambda: "fake")
    assert [call[0][0] for call in client.calls] == ["GET"]
    path = legacy.pending_task_path(tmp_path, asset, 2012)
    assert json.loads(path.read_text()) == legacy._pending_identity(asset, 2012, "65267487597")
    assert "secret=123" not in path.read_text()


@pytest.mark.parametrize("changes", [{"DatasetID": "wrong"}, {"FileID": "wrong"},
                                    {"TaskID": "wrong"}, {"Status": "Failed"}, {"Status": None}])
def test_adoption_rejects_invalid_remote_task(tmp_path, changes):
    response = task_response("Queued")
    if any(key in changes for key in ("DatasetID", "FileID")):
        response.payload["Datasets"][0].update(changes)
    else:
        response.payload.update(changes)
    asset = legacy.LEGACY["assets"][0]
    with pytest.raises(ValueError):
        legacy.adopt_pending_task(tmp_path, asset, 2012, "65267487597",
                                  client=Client(response), token_provider=lambda: "fake")
    assert not legacy.pending_task_path(tmp_path, asset, 2012).exists()


@pytest.mark.parametrize("datasets", ["missing", None, {}, [], [None], [[]], [{}], [{}, {}]])
def test_adoption_rejects_missing_malformed_or_multiple_datasets(tmp_path, datasets):
    response = task_response("Queued")
    valid_dataset = response.payload.pop("Datasets")[0]
    # Valid top-level IDs must not substitute for the real nested contract.
    response.payload.update(valid_dataset)
    if datasets != "missing":
        response.payload["Datasets"] = [valid_dataset, valid_dataset] if datasets == [{}, {}] else datasets
    asset = legacy.LEGACY["assets"][0]
    client = Client(response)
    with pytest.raises(ValueError, match="task identity missing or mismatched"):
        legacy.adopt_pending_task(tmp_path, asset, 2012, "65267487597",
                                  client=client, token_provider=lambda: "fake")
    assert [call[0][0] for call in client.calls] == ["GET"]
    assert not legacy.pending_task_path(tmp_path, asset, 2012).exists()


def test_task_status_accepts_matching_optional_task_id():
    response = task_response("Queued", TaskID="65267487597")
    assert legacy._task_status(legacy.LEGACY["assets"][0], 2012, "65267487597",
                               client=Client(response), token_provider=lambda: "fake") == ("Queued", None, None)


@pytest.mark.parametrize("failure", ["download", "raster/ZIP validation", "final metadata"])
def test_acquisition_failure_keeps_pending_and_sanitizes(tmp_path, monkeypatch, failure):
    asset = legacy.LEGACY["assets"][0]
    response = Response(data=zip_bytes(asset))
    if failure == "download":
        response.status_code = 500
    if failure == "raster/ZIP validation":
        response.data = b"invalid ZIP secret=123"
    if failure == "final metadata":
        def fail(*args):
            raise RuntimeError("private-key bearer secret=123")
        monkeypatch.setattr(legacy, "json_dump", fail)
    with pytest.raises(ValueError) as error:
        legacy.acquire_product(tmp_path, asset, 2012,
            client=Client(submitted(), completed(FileSize=len(response.data)), response), token_provider=lambda: "fake")
    assert failure in str(error.value)
    assert all(secret not in str(error.value) for secret in ("private-key", "bearer", "secret=123"))
    assert legacy.pending_task_path(tmp_path, asset, 2012).exists()
    assert not legacy.raw_path(tmp_path, asset, 2012).exists()
    assert not list(tmp_path.rglob("*.partial"))


def test_acquire_timeout_remains_distinguishable(tmp_path, monkeypatch):
    monkeypatch.setitem(legacy.LEGACY, "polling_timeout_seconds", 0.001)
    with pytest.raises(TimeoutError, match="pending timeout"):
        legacy.acquire_product(tmp_path, legacy.LEGACY["assets"][0], 2012,
            client=Client(submitted(), task_response("Queued")), token_provider=lambda: "fake")
    assert legacy.pending_task_path(tmp_path, legacy.LEGACY["assets"][0], 2012).exists()


def test_poll_matches_completed_task_and_closes_responses(tmp_path):
    responses = [submitted(), task_response("Queued"), task_response("In_progress"),
                 completed("https://example.org/right?secret=opaque")]
    client = Client(*responses)
    task, url, size = legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=client,
                                            token_provider=lambda: "fake-bearer", sleep=lambda _: None)
    assert task == "65267487597" and url.endswith("right?secret=opaque")
    assert size == responses[-1].payload["FileSize"]
    assert all(call[1]["headers"] == {"Authorization": "Bearer fake-bearer", "Accept": "application/json"} for call in client.calls)
    assert client.calls[0][1]["json"] == {"Datasets": [{"DatasetID": "b903be8a861d48d9af41266ce63cc287", "FileID": "266be23f-29a1-41f8-899d-a57c35d572fc"}]}
    assert all(call[0] == ("GET", legacy.LEGACY["status_url"]) and call[1]["params"] == {"TaskID": task} for call in client.calls[1:])
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("payload", [None, [], {"65267487597": None}, {"65267487597": []},
    {"65267487597": {}},
    {"65267487597": {"Status": "In_progress", "DownloadURL": "https://example.org/?secret=x"}},
    {"65267487597": {"Status": "Finished_err", "DownloadURL": "https://example.org/?secret=x"}},
    *[{"65267487597": {"Status": "Finished_ok", "DownloadURL": url}} for url in
      (None, [], "", "http://bad", "https://user:password@example.org/", "https://example.org/\nsecret")],
    {"65267487597": {"Status": "Finished_ok"}}])
def test_malformed_or_ambiguous_poll_fails(payload, tmp_path):
    with pytest.raises(ValueError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=Client(submitted(), Response(payload)), token_provider=lambda: "fake")


@pytest.mark.parametrize("payload", [None, {}, [],
    {"ErrorTaskIds": ["error"], "TaskIds": [{"TaskID": "65267487597"}]},
    {"ErrorTaskIds": None, "TaskIds": [{"TaskID": "65267487597"}]},
    {"TaskIds": [{"TaskID": "65267487597"}]},
    *[{"ErrorTaskIds": [], "TaskIds": tasks} for tasks in
      (None, {}, [], [{"TaskID": "a"}, {"TaskID": "b"}], [None], [{}],
       [{"TaskID": 1}], [{"TaskID": ""}], [{"TaskID": "with space"}])]])
def test_malformed_submission_fails(payload, tmp_path):
    with pytest.raises(ValueError, match="TaskID"):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=Client(Response(payload, status=201)), token_provider=lambda: "fake")


def test_poll_bound_and_redaction(caplog, tmp_path):
    client = Client(submitted(), task_response("Queued"), task_response("In_progress"))
    with pytest.raises(TimeoutError):
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=client,
                                    token_provider=lambda: "fake", max_polls=2, sleep=lambda _: None)
    def failing_token():
        raise RuntimeError("secret-token private-key https://example.org/?secret=1")
    with pytest.raises(ValueError) as error:
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=Client(), token_provider=failing_token)
    assert "secret-token" not in str(error.value) + caplog.text
    assert "private-key" not in str(error.value) + caplog.text
    assert error.value.__suppress_context__


@pytest.mark.parametrize("method,status", [("POST", 200), ("POST", 400), ("GET", 201), ("GET", 403), ("GET", 500)])
def test_clms_expected_http_status_and_redaction(method, status, caplog, tmp_path):
    response = submitted() if method == "POST" else completed()
    response.status_code = status
    response.payload = {"server_error": "secret-token https://example.org/?secret=123"}
    client = Client(response) if method == "POST" else Client(submitted(), response)
    with pytest.raises(ValueError) as error:
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json", client=client, token_provider=lambda: "secret-token")
    assert "secret-token" not in str(error.value) + caplog.text
    assert "secret=123" not in str(error.value) + caplog.text
    assert response.closed


@pytest.mark.parametrize("asset", legacy.LEGACY["assets"])
def test_zip_accepts_unknown_internal_name(tmp_path, asset):
    archive = tmp_path / "product.zip"
    archive.write_bytes(zip_bytes(asset))
    assert len(legacy.extract_validated_raster(archive, tmp_path / "raster.tif", asset)) == 64


@pytest.mark.parametrize("case", ["valid", "unsafe_paths", "zero_tiffs", "multiple_tiffs",
                                 "zero_zips", "multiple_zips", "corrupt_inner", "corrupt_outer",
                                 "invalid_raster", "multiple_outer_tiffs"])
def test_nested_zip_validation_and_cleanup(tmp_path, monkeypatch, case):
    asset = legacy.LEGACY["assets"][0]
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(legacy.tempfile, "tempdir", str(scratch))
    def forbidden(*args, **kwargs):
        pytest.fail("Archive paths must never be extracted directly")
    monkeypatch.setattr(zipfile.ZipFile, "extract", forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden)
    with zipfile.ZipFile(io.BytesIO(zip_bytes(asset, values=[101] if case == "invalid_raster" else None))) as source:
        raster_bytes = source.read("unknown/internal-name.tif")
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as bundle:
        bundle.writestr("TCD_2012_020m_eu_03035_d03_Full/full.tfw", "sidecar")
        bundle.writestr("metadata.xml", "<metadata/>")
        if case != "zero_tiffs":
            name = "../escaped.tif" if case == "unsafe_paths" else "TCD_2012_020m_eu_03035_d03_Full/full.tif"
            bundle.writestr(name, raster_bytes)
        if case == "multiple_tiffs":
            bundle.writestr("second.tiff", raster_bytes)
    archive = tmp_path / "outer.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("readme.xml", "<metadata/>")
        if case != "zero_zips":
            name = "../escaped.zip" if case == "unsafe_paths" else "Results/TCD_2012_020m_eu_03035_d03_Full.zip"
            bundle.writestr(name, b"not a zip" if case == "corrupt_inner" else inner.getvalue())
        if case == "multiple_zips":
            bundle.writestr("second.zip", inner.getvalue())
        if case == "multiple_outer_tiffs":
            bundle.writestr("one.tif", raster_bytes)
            bundle.writestr("two.tif", raster_bytes)
    if case == "corrupt_outer":
        archive.write_bytes(b"not a zip")
    destination = tmp_path / "raster.tif"
    if case in {"valid", "unsafe_paths"}:
        assert legacy.extract_validated_raster(archive, destination, asset) == legacy.sha256(raster_bytes).hexdigest()
        assert destination.read_bytes() == raster_bytes
    else:
        reasons = {
            "zero_tiffs": "nested_tiffs_zero", "multiple_tiffs": "nested_tiffs_multiple",
            "zero_zips": "direct_tiffs_zero_nested_zips_zero", "multiple_zips": "nested_zips_multiple",
            "corrupt_inner": "nested_zip_invalid", "corrupt_outer": "outer_zip_invalid",
            "invalid_raster": "unexpected_values", "multiple_outer_tiffs": "direct_tiffs_multiple",
        }
        with pytest.raises(legacy.RasterValidationError, match=f"^{reasons[case]}$"):
            legacy.extract_validated_raster(archive, destination, asset)
        assert not destination.exists()
    assert not list(scratch.iterdir())
    assert set(tmp_path.iterdir()) == {scratch, archive} | ({destination} if destination.exists() else set())


@pytest.mark.parametrize("overrides", [{"crs": "EPSG:4326"}, {"resolution": 10}, {"extra": True}, {"count": 2}, {"nodata": 0}, {"values": [101]}, {"values": [253]}])
def test_validator_rejects_incompatible_raster(tmp_path, overrides):
    asset = legacy.LEGACY["assets"][0]
    archive = tmp_path / "product.zip"
    archive.write_bytes(zip_bytes(asset, **overrides))
    raster = tmp_path / "raster.tif"
    with pytest.raises(ValueError):
        legacy.extract_validated_raster(archive, raster, asset)
    assert not raster.exists()


@pytest.mark.parametrize("reason", ["raster_open", "crs", "band_count", "rotation",
                                  "resolution_x", "resolution_y", "nodata", "scale",
                                  "offset", "dtype", "unexpected_values"])
def test_raster_diagnostic_rules(tmp_path, reason):
    asset = legacy.LEGACY["assets"][0]
    path = tmp_path / "raster.tif"
    if reason == "raster_open":
        path.write_bytes(b"fake signed URL https://example.org/?secret=token")
    else:
        transform = from_origin(4500000, 2500000, 20, 20)
        if reason == "rotation":
            transform = rasterio.Affine(20, 1, 4500000, 0, -20, 2500000)
        if reason == "resolution_x":
            transform = from_origin(4500000, 2500000, 100, 20)
        if reason == "resolution_y":
            transform = from_origin(4500000, 2500000, 20, 100)
        with rasterio.open(path, "w", driver="GTiff", width=1, height=1,
                           count=2 if reason == "band_count" else 1,
                           dtype="float32" if reason == "dtype" else "uint8",
                           crs="EPSG:4326" if reason == "crs" else "EPSG:3035",
                           transform=transform, nodata=0 if reason == "nodata" else 255) as dataset:
            dataset.write(np.array([[101 if reason == "unexpected_values" else 1]], dtype="uint8"), 1)
            if reason == "scale":
                dataset.scales = (2.0,)
            if reason == "offset":
                dataset.offsets = (1.0,)
    with pytest.raises(legacy.RasterValidationError) as error:
        legacy.validate_raster(path, asset)
    assert str(error.value) == reason
    assert "secret" not in str(error.value)


LEGACY_OBSERVED_WKT = """PROJCS["ETRS89-extended / LAEA Europe",
GEOGCS["ETRS89",DATUM["IRENET95",SPHEROID["GRS 1980",6378137,298.257222101]],
PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],
PROJECTION["Lambert_Azimuthal_Equal_Area"],
PARAMETER["latitude_of_center",52],PARAMETER["longitude_of_center",10],
PARAMETER["false_easting",4321000],PARAMETER["false_northing",3210000],
UNIT["metre",1],AXIS["Easting",EAST],AXIS["Northing",NORTH]]"""


@pytest.mark.parametrize("wkt", [None, LEGACY_OBSERVED_WKT])
def test_legacy_crs_equivalence_accepts_known_definitions(tmp_path, wkt):
    crs = rasterio.crs.CRS.from_epsg(3035) if wkt is None else rasterio.crs.CRS.from_wkt(wkt)
    if wkt is not None:
        assert crs.to_epsg() is None
    assert legacy._legacy_crs_is_epsg3035_equivalent(crs)
    if wkt is not None:
        # GeoTIFF encoding can rewrite datum names; test the observed CRS in memory.
        return
    asset = legacy.LEGACY["assets"][0]
    archive = tmp_path / "synthetic.zip"
    archive.write_bytes(zip_bytes(asset, crs=crs))
    assert len(legacy.extract_validated_raster(archive, tmp_path / "raster.tif", asset)) == 64


@pytest.mark.parametrize("old,new", [
    ("ETRS89-extended / LAEA Europe", "Unrelated projected CRS"),
    ('GEOGCS["ETRS89"', 'GEOGCS["Unrelated geographic CRS"'),
    ("IRENET95", "Unrelated datum"), ("GRS 1980", "Unrelated ellipsoid"),
    ("6378137", "6378138"), ("298.257222101", "298.257223563"),
    ("Lambert_Azimuthal_Equal_Area", "Azimuthal_Equidistant"),
    ('"latitude_of_center",52', '"latitude_of_center",51'),
    ('"longitude_of_center",10', '"longitude_of_center",11'),
    ('"false_easting",4321000', '"false_easting",4321001'),
    ('"false_northing",3210000', '"false_northing",3210001'),
    ('UNIT["metre",1]', 'UNIT["foot",0.3048]'),
    ('PRIMEM["Greenwich",0]', 'PRIMEM["Greenwich",1]'),
])
def test_legacy_crs_equivalence_rejects_material_deviations(old, new):
    crs = rasterio.crs.CRS.from_wkt(LEGACY_OBSERVED_WKT.replace(old, new))
    assert not legacy._legacy_crs_is_epsg3035_equivalent(crs)


def test_legacy_crs_equivalence_rejects_unidentified_crs(tmp_path):
    crs = rasterio.crs.CRS.from_string("+proj=aeqd +lat_0=13 +lon_0=27 +datum=WGS84 +units=m")
    assert crs.to_epsg() is None
    assert not legacy._legacy_crs_is_epsg3035_equivalent(crs)
    assert not legacy._legacy_crs_is_epsg3035_equivalent(None)
    asset = legacy.LEGACY["assets"][0]
    archive = tmp_path / "synthetic.zip"
    archive.write_bytes(zip_bytes(asset, crs=crs))
    with pytest.raises(legacy.RasterValidationError, match="^crs$"):
        legacy.extract_validated_raster(archive, tmp_path / "raster.tif", asset)


def test_raster_open_exception_text_is_redacted(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("https://example.org/?signed=secret bearer private-key")
    monkeypatch.setattr(legacy.rasterio, "open", fail)
    with pytest.raises(legacy.RasterValidationError, match="^raster_open$"):
        legacy.validate_raster(tmp_path / "fixed.tif", legacy.LEGACY["assets"][0])


def test_failed_archive_retained_reused_and_promoted(tmp_path):
    asset = legacy.LEGACY["assets"][0]
    invalid = zip_bytes(asset, resolution=100)
    client = Client(submitted(), completed("https://example.org/?signed=secret", FileSize=len(invalid)), Response(data=invalid))
    path = legacy.raw_path(tmp_path, asset, 2012)
    failed = path.with_suffix(".zip.validation-failed")
    pending = legacy.pending_task_path(tmp_path, asset, 2012)
    for attempt in range(2):
        active_client = client if attempt == 0 else Client()
        with pytest.raises(ValueError) as error:
            legacy.acquire_product(tmp_path, asset, 2012, client=active_client, token_provider=lambda: "fake-bearer")
        assert str(error.value) == "CLMS legacy raster/ZIP validation failure (resolution_x); pending TaskID retained"
        assert failed.read_bytes() == invalid
        assert pending.exists()
        assert not path.exists()
        assert not path.with_suffix(".zip.metadata.json").exists()
        assert not list(tmp_path.rglob("*.partial"))
        if attempt:
            assert not active_client.calls
    failed.write_bytes(zip_bytes(asset))
    no_network = Client()
    result = legacy.acquire_product(tmp_path, asset, 2012, client=no_network)
    assert not no_network.calls
    assert result["changed"] and result["TaskID"] == "65267487597"
    assert result["sha256"] == legacy.sha256_file(path)
    assert path.with_suffix(".zip.metadata.json").exists()
    assert not failed.exists() and not pending.exists()


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
    assert not legacy.pending_task_path(tmp_path, asset, 2012).exists()
    assert result["changed"]
    assert "headers" not in client.calls[-1][1]
    assert client.calls[-1][1] == {"timeout": (30, 300), "stream": True, "allow_redirects": False}
    assert "secret=123" not in json.dumps(result)
    assert "fake-bearer" not in json.dumps(result)
    assert all(r.closed for r in responses)
    assert not legacy.acquire_product(tmp_path, asset, 2012, offline=True)["changed"]
    Path(result["local_path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="provenance"):
        legacy.acquire_product(tmp_path, asset, 2012, offline=True)


@pytest.mark.parametrize("during_request", [False, True])
@pytest.mark.parametrize("exception_type", [legacy.requests.exceptions.ReadTimeout, ValueError])
def test_download_interruption_reports_only_class_and_written_bytes(tmp_path, caplog, during_request, exception_type):
    secret = "fake failure https://example.org/download?signature=secret fake-bearer"
    class InterruptedResponse(Response):
        def iter_content(self, **kwargs):
            yield b"first"
            yield b"chunk"
            raise exception_type(secret)
    response = InterruptedResponse()
    class DownloadClient(Client):
        def request(self, *args, **kwargs):
            if during_request and kwargs.get("stream"):
                raise exception_type(secret)
            return super().request(*args, **kwargs)
    asset = legacy.LEGACY["assets"][0]
    attempts = 3 if exception_type is legacy.requests.exceptions.ReadTimeout else 1
    replies = [submitted()]
    for _ in range(attempts):
        replies.append(completed())
        if not during_request:
            replies.append(response)
    client = DownloadClient(*replies)
    with pytest.raises(ValueError) as error:
        legacy.acquire_product(tmp_path, asset, 2012, client=client, token_provider=lambda: "fake-bearer")
    count = 0 if during_request else 10
    assert str(error.value) == (
        f"CLMS legacy download failure ({exception_type.__name__}, attempt {attempts}/3, {count}/{len(zip_bytes(asset))} bytes); pending TaskID retained")
    assert error.value.__suppress_context__
    assert all(value not in str(error.value) + caplog.text for value in
               ("fake failure", "https://", "signature=secret", "fake-bearer"))
    assert legacy.pending_task_path(tmp_path, asset, 2012).exists()
    assert not legacy.raw_path(tmp_path, asset, 2012).exists()
    assert not list(tmp_path.rglob("*.partial"))
    if not during_request:
        assert response.closed


@pytest.mark.parametrize("size", ["missing", None, False, True, 0, -1, 1.5, "123", [], {}])
def test_finished_task_requires_positive_integer_filesize(size):
    response = completed(FileSize=size)
    if size == "missing":
        del response.payload["FileSize"]
    with pytest.raises(ValueError, match="valid FileSize"):
        legacy._task_status(legacy.LEGACY["assets"][0], 2012, "65267487597",
                            client=Client(response), token_provider=lambda: "fake")


@pytest.mark.parametrize("failure", ["chunked", "read_timeout", "connection", "size_mismatch", "oversize"])
@pytest.mark.parametrize("recover", [False, True])
def test_full_download_retries_same_task_with_fresh_url(tmp_path, failure, recover):
    asset = legacy.LEGACY["assets"][0]
    data = zip_bytes(asset)
    pending = legacy.pending_task_path(tmp_path, asset, 2012)
    legacy._write_pending(pending, asset, 2012, "65267487597")
    classes = {"chunked": legacy.requests.exceptions.ChunkedEncodingError,
               "read_timeout": legacy.requests.exceptions.ReadTimeout,
               "connection": legacy.requests.exceptions.ConnectionError}
    class FailedStream(Response):
        def iter_content(self, **kwargs):
            yield b"short"
            raise classes[failure]("fake upstream https://example.org/?signed=secret bearer-token")
    attempts = 2 if recover else 3
    responses, streams = [], []
    for attempt in range(attempts):
        responses.append(completed(f"https://example.org/file?signature=secret-{attempt}", FileSize=len(data)))
        if recover and attempt == 1:
            response = Response(data=data)
        elif failure in classes:
            response = FailedStream()
        else:
            response = Response(data=b"short" if failure == "size_mismatch" else data + b"x")
        responses.append(response)
        streams.append(response)
    class InspectingClient(Client):
        def request(self, *args, **kwargs):
            if kwargs.get("params"):
                assert not list(tmp_path.rglob("*.partial"))
                assert all(stream.closed for stream in streams[:len(self.calls) // 2])
            return super().request(*args, **kwargs)
    client = InspectingClient(*responses)
    if recover:
        result = legacy.acquire_product(tmp_path, asset, 2012, client=client, token_provider=lambda: "fake")
        assert result["changed"] and result["bytes"] == len(data)
        assert not pending.exists()
    else:
        reason = classes[failure].__name__ if failure in classes else "size_mismatch"
        count = len(data) + 1 if failure == "oversize" else 5
        with pytest.raises(ValueError) as error:
            legacy.acquire_product(tmp_path, asset, 2012, client=client, token_provider=lambda: "fake")
        assert str(error.value) == (
            f"CLMS legacy download failure ({reason}, attempt 3/3, {count}/{len(data)} bytes); pending TaskID retained")
        assert pending.exists()
        assert not legacy.raw_path(tmp_path, asset, 2012).exists()
    assert len(client.calls) == attempts * 2
    assert all(call[0][0] == "GET" for call in client.calls)
    for index in range(attempts):
        assert client.calls[2 * index][0][1] == legacy.LEGACY["status_url"]
        assert client.calls[2 * index][1]["params"] == {"TaskID": "65267487597"}
        args, kwargs = client.calls[2 * index + 1]
        assert args[1] == f"https://example.org/file?signature=secret-{index}"
        assert kwargs == {"timeout": (30, 300), "stream": True, "allow_redirects": False}
    assert all(response.closed for response in responses)
    assert not list(tmp_path.rglob("*.partial"))
    assert not list(tmp_path.rglob("*.validation-failed"))


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
    # Even a remaining local pending file cannot become declared raw/source metadata.
    pending = legacy.pending_task_path(tmp_path, asset, 2012)
    legacy._write_pending(pending, asset, 2012, "65267487597")
    paths = _declared_raw_paths({"legacy": [result]})
    assert set(paths) == {Path(result["local_path"]), Path(result["metadata_path"])}
    assert pending not in paths
    assert list(tmp_path.rglob("*.metadata.json")) == [Path(result["metadata_path"])]
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
        legacy.request_download_url(legacy.LEGACY["assets"][0], 2012, pending_path=tmp_path / "task.pending-task.json",
            client=Client(submitted(), task_response("Queued")),
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
    monkeypatch.setattr(legacy.ClmsTokenProvider, "__call__", lambda self: pytest.fail("Retained ZIP requires no token"))
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
