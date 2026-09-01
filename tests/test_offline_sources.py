from pathlib import Path
from io import BytesIO

import pytest

from stato_italia.download import download
import stato_italia.download as downloader
from stato_italia.infc_transport import InfcTransportError


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
