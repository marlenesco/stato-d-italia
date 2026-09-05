import json
from pathlib import Path
from io import BytesIO

import pytest

from stato_italia.download import download
import stato_italia.download as downloader
from stato_italia.infc_transport import InfcTransportError


class _DownloadResponse:
    def __init__(self, status_code: int, body: bytes = b"official bytes") -> None:
        self.status_code = status_code
        self.headers = {"Content-Type": "application/zip", "ETag": '"asset-v1"'}
        self.url = "https://official.example/asset.zip"
        self.raw = BytesIO(body)
        self.closed = False

    def __enter__(self) -> "_DownloadResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise downloader.requests.HTTPError(f"HTTP {self.status_code}")


def test_offline_source_registers_local_raw_bytes(tmp_path: Path) -> None:
    asset = tmp_path / "raw" / "source" / "asset.xlsx"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"official bytes")

    first = download("https://example.test/asset.xlsx", asset, "source", offline=True)
    second = download("https://example.test/asset.xlsx", asset, "source", offline=True)

    assert first["acquisition_mode"] == "local_supplied"
    assert first["unchanged"] is False
    assert second["unchanged"] is True
    assert (asset.with_suffix(".xlsx.metadata.json")).exists()


def test_offline_source_fails_when_asset_is_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Offline source asset missing"):
        download("https://example.test/missing.xlsx", tmp_path / "missing.xlsx", "source", offline=True)


def test_online_download_retries_transport_failure_with_tls_verification_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        headers = {"Content-Type": "application/zip"}
        url = "https://official.example/asset.zip"
        raw = BytesIO(b"official bytes")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

    calls: list[dict] = []

    def get(*_args: object, **kwargs: object) -> Response:
        calls.append(kwargs)
        if len(calls) == 1:
            raise downloader.requests.exceptions.SSLError("temporary certificate mismatch")
        return Response()

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", lambda _seconds: None)
    destination = tmp_path / "asset.zip"

    metadata = download("https://official.example/asset.zip", destination, "official-source")

    assert destination.read_bytes() == b"official bytes"
    assert metadata["resolved_url"] == "https://official.example/asset.zip"
    assert len(calls) == 2
    assert all(call["verify"] is True for call in calls)
    assert all("proxies" not in call for call in calls)


def test_online_download_retries_500_then_promotes_only_successful_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = _DownloadResponse(500)
    successful = _DownloadResponse(200, b"new official bytes")
    responses = iter((failed, successful))
    calls: list[dict] = []
    delays: list[int] = []

    def get(*_args: object, **kwargs: object) -> _DownloadResponse:
        calls.append(kwargs)
        return next(responses)

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", delays.append)
    destination = tmp_path / "asset.zip"

    metadata = download("https://official.example/asset.zip", destination, "official-source")

    assert len(calls) == 2
    assert delays == [2]
    assert failed.closed is True
    assert destination.read_bytes() == b"new official bytes"
    assert not destination.with_suffix(".zip.partial").exists()
    assert metadata["sha256"]
    assert metadata["requested_url"] == "https://official.example/asset.zip"
    assert metadata["resolved_url"] == "https://official.example/asset.zip"
    assert (destination.with_suffix(".zip.metadata.json")).exists()


def test_online_download_retries_multiple_server_errors_with_bounded_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter((_DownloadResponse(503), _DownloadResponse(502), _DownloadResponse(200)))
    calls = 0
    delays: list[int] = []

    def get(*_args: object, **_kwargs: object) -> _DownloadResponse:
        nonlocal calls
        calls += 1
        return next(responses)

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", delays.append)

    result = download("https://official.example/asset.zip", tmp_path / "asset.zip", "official-source")

    assert calls == 3
    assert delays == [2, 4]
    assert result["bytes"] == len(b"official bytes")


def test_online_download_raises_after_retryable_server_errors_without_replacing_existing_asset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter((_DownloadResponse(500), _DownloadResponse(500), _DownloadResponse(500), _DownloadResponse(500)))
    calls = 0
    delays: list[int] = []

    def get(*_args: object, **_kwargs: object) -> _DownloadResponse:
        nonlocal calls
        calls += 1
        return next(responses)

    destination = tmp_path / "asset.zip"
    destination.write_bytes(b"trusted old bytes")
    partial = destination.with_suffix(".zip.partial")
    partial.write_bytes(b"stale incomplete bytes")
    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", delays.append)

    with pytest.raises(downloader._RetryableHttpStatusError, match="HTTP 500"):
        download("https://official.example/asset.zip", destination, "official-source")

    assert calls == 4
    assert delays == [2, 4, 8]
    assert destination.read_bytes() == b"trusted old bytes"
    assert not partial.exists()


def test_online_download_fails_fast_for_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    delays: list[int] = []

    def get(*_args: object, **_kwargs: object) -> _DownloadResponse:
        nonlocal calls
        calls += 1
        return _DownloadResponse(404)

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", delays.append)

    with pytest.raises(downloader.requests.HTTPError, match="HTTP 404"):
        download("https://official.example/asset.zip", tmp_path / "asset.zip", "official-source")

    assert calls == 1
    assert delays == []


def test_online_download_retries_connection_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    delays: list[int] = []

    def get(*_args: object, **_kwargs: object) -> _DownloadResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise downloader.requests.Timeout("connection timed out")
        return _DownloadResponse(200)

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", delays.append)

    download("https://official.example/asset.zip", tmp_path / "asset.zip", "official-source")

    assert calls == 2
    assert delays == [2]


def test_online_download_keeps_matching_304_path_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "asset.zip"
    destination.write_bytes(b"cached official bytes")
    metadata_path = destination.with_suffix(".zip.metadata.json")
    metadata_path.write_text(json.dumps({
        "source_id": "official-source", "requested_url": "https://official.example/asset.zip",
        "etag": '"asset-v1"', "last_modified": "Mon, 01 Sep 2026 00:00:00 GMT",
    }))
    calls: list[dict] = []
    delays: list[int] = []

    def get(*_args: object, **kwargs: object) -> _DownloadResponse:
        calls.append(kwargs)
        return _DownloadResponse(304)

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", delays.append)

    result = download("https://official.example/asset.zip", destination, "official-source")

    assert result["unchanged"] is True
    assert destination.read_bytes() == b"cached official bytes"
    assert len(calls) == 1
    assert calls[0]["headers"]["If-None-Match"] == '"asset-v1"'
    assert calls[0]["headers"]["If-Modified-Since"] == "Mon, 01 Sep 2026 00:00:00 GMT"
    assert delays == []


def test_infc_download_uses_prioritised_proxy_fallback_without_disabling_tls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        status_code = 200
        headers = {"Content-Type": "application/zip"}
        url = "https://www.inventarioforestale.org/asset.zip"

        def __init__(self) -> None:
            self.raw = BytesIO(b"official bytes")

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

    proxies = ("http://proxy-one.example:3128", "http://proxy-two.example:8080")
    calls: list[dict] = []

    def get(*_args: object, **kwargs: object) -> Response:
        calls.append(kwargs)
        selected = kwargs.get("proxies")
        if selected is None or selected == {"https": proxies[0]}:
            raise downloader.requests.exceptions.ConnectTimeout("route unavailable")
        return Response()

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", lambda _seconds: None)
    monkeypatch.setattr(downloader, "infc_proxy_candidates", lambda _url: proxies)
    destination = tmp_path / "asset.zip"

    metadata = download(
        "https://www.inventarioforestale.org/asset.zip",
        destination,
        "infc-2015-forests",
    )

    assert destination.read_bytes() == b"official bytes"
    assert metadata["transport"] == "proxy"
    assert [call.get("proxies") for call in calls] == [
        None, None, None, None,
        {"https": proxies[0]},
        {"https": proxies[1]},
    ]
    assert all(call["verify"] is True for call in calls)


def test_infc_proxy_credentials_are_not_exposed_when_every_route_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy = "http://secret-user:secret-password@proxy.example:3128"

    def get(*_args: object, **_kwargs: object) -> None:
        raise downloader.requests.exceptions.ProxyError(f"failed via {proxy}")

    monkeypatch.setattr(downloader.requests, "get", get)
    monkeypatch.setattr(downloader, "sleep", lambda _seconds: None)
    monkeypatch.setattr(downloader, "infc_proxy_candidates", lambda _url: (proxy,))

    with pytest.raises(InfcTransportError) as raised:
        download(
            "https://www.inventarioforestale.org/asset.zip",
            tmp_path / "asset.zip",
            "infc-2015-forests",
        )

    assert "secret-user" not in str(raised.value)
    assert "secret-password" not in str(raised.value)
