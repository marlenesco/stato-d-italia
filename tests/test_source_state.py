import json
from pathlib import Path

import pytest
import requests

from stato_italia.source_state import (
    build_source_state,
    check_persisted_sources,
    declared_raw_paths,
    merge_source_states,
    scoped_source_state,
    source_scope,
    source_state_changed,
)
from stato_italia.cli import _release_artifacts


def _asset(root: Path, name: str, *, checksum: str = "a" * 64) -> Path:
    asset = root / "ispra" / name
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"official")
    asset.with_suffix(asset.suffix + ".metadata.json").write_text(json.dumps({
        "source_id": "ispra", "resolved_url": "https://official.example/asset",
        "etag": '"v1"', "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        "sha256": checksum, "bytes": 8, "dataset_version": "2024", "checked_at": "2024-01-01T00:00:00Z",
    }))
    return asset


def test_source_state_is_persistent_contract_and_ignores_check_time(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    asset = _asset(raw, "asset.xlsx")
    first = build_source_state(raw)
    metadata_path = asset.with_suffix(asset.suffix + ".metadata.json")
    metadata = json.loads(metadata_path.read_text())
    metadata["checked_at"] = "2024-02-01T00:00:00Z"
    metadata_path.write_text(json.dumps(metadata))
    assert not source_state_changed(first, build_source_state(raw))
    metadata["etag"] = '"v2"'
    metadata_path.write_text(json.dumps(metadata))
    assert source_state_changed(first, build_source_state(raw))


def test_declared_raw_paths_excludes_undeclared_files(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    asset = _asset(raw, "asset.xlsx")
    stale = raw / "old" / "never-used.zip"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"stale")
    assert set(declared_raw_paths(raw)) == {asset, asset.with_suffix(asset.suffix + ".metadata.json")}


def test_persisted_state_uses_conditional_get_not_head(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"schemaVersion": 1, "sources": [{
        "source_id": "ispra", "asset_path": "ispra/asset.xlsx", "resolved_url": "https://official.example/asset",
        "etag": '"v1"', "last_modified": None, "sha256": "a" * 64, "bytes": 1,
        "dataset_version": None, "period": None, "checked_at": "2024-01-01T00:00:00Z",
    }]}

    class Response:
        status_code = 304

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    calls: list[dict] = []

    def fake_get(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("stato_italia.source_state.requests.get", fake_get)
    result = check_persisted_sources(state, scope="data")
    assert result["changed"] is False
    assert calls[0]["headers"]["If-None-Match"] == '"v1"'


def test_infc_preflight_falls_back_to_proxy_and_keeps_tls_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://www.inventarioforestale.org/asset.zip"
    state = {"schemaVersion": 1, "sources": [{
        "source_id": "infc-2015-forests", "asset_path": "infc-2015-forests/asset.zip",
        "resolved_url": url, "etag": '"v1"', "last_modified": None,
        "sha256": "a" * 64, "bytes": 1, "dataset_version": None, "period": None,
        "checked_at": "2024-01-01T00:00:00Z",
    }]}

    class Response:
        status_code = 304

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    calls: list[dict] = []

    def get(_url: str, **kwargs: object) -> Response:
        calls.append(kwargs)
        if "proxies" not in kwargs:
            raise requests.exceptions.ConnectTimeout("direct unavailable")
        return Response()

    import stato_italia.infc_transport as transport

    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("INFC_HTTPS_PROXIES", "http://proxy.example:3128")
    monkeypatch.setattr("stato_italia.source_state.requests.get", get)

    result = check_persisted_sources(state, scope="geospatial")

    assert result["changed"] is False
    assert result["sources"][0]["transport"] == "proxy"
    assert calls[0]["verify"] is True
    assert calls[1]["verify"] is True
    assert calls[1]["proxies"] == {"https": "http://proxy.example:3128"}


def test_infc_is_geospatial_and_data_preflight_never_contacts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"schemaVersion": 1, "sources": [{
        "source_id": "infc-2015-forests", "asset_path": "infc-2015-forests/asset.zip",
        "resolved_url": "https://www.inventarioforestale.org/asset.zip",
        "etag": '"v1"', "last_modified": None, "sha256": "a" * 64, "bytes": 1,
        "dataset_version": "infc2015-published-tables", "period": "2015",
        "checked_at": "2024-01-01T00:00:00Z",
    }]}
    monkeypatch.setattr(
        "stato_italia.source_state.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("data scope contacted INFC")),
    )

    result = check_persisted_sources(state, scope="data")

    assert source_scope("infc-2015-forests") == "geospatial"
    assert result == {
        "scope": "data", "sourceChecks": 0, "sourcesChanged": 0,
        "sourcesUnchanged": 0, "sourcesUnverifiable": 0,
        "changed": True, "reason": "no_persisted_data_state", "sources": [],
    }


def test_persisted_infc_state_is_reusable_after_ownership_migration() -> None:
    infc = {
        "source_id": "infc-2015-forests", "asset_path": "infc-2015-forests/volume.zip",
        "resolved_url": "https://www.inventarioforestale.org/volume.zip",
        "etag": '"v1"', "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT",
        "sha256": "a" * 64, "bytes": 123, "dataset_version": "infc2015-published-tables",
        "period": "2015", "checked_at": "2024-01-01T00:00:00Z",
    }
    persisted = {"schemaVersion": 1, "sources": [infc]}
    current = scoped_source_state(persisted, "geospatial")

    assert current == persisted
    assert merge_source_states(persisted, current, scope="geospatial") == persisted
    assert source_state_changed(persisted, current) is False


def test_scope_state_carry_forward_data_geospatial_data() -> None:
    def entry(source_id: str, asset_path: str, checksum: str) -> dict:
        return {
            "source_id": source_id, "asset_path": asset_path, "resolved_url": "https://official.example/asset",
            "etag": None, "last_modified": None, "sha256": checksum, "bytes": 1,
            "dataset_version": None, "period": None, "checked_at": "2024-01-01T00:00:00Z",
        }

    data_one = {"schemaVersion": 1, "sources": [entry("ispra-soil", "soil.xlsx", "1" * 64)]}
    geo = {"schemaVersion": 1, "sources": [entry("copernicus-forests", "catalog.json", "2" * 64)]}
    data_two = {"schemaVersion": 1, "sources": [entry("ispra-soil", "soil.xlsx", "3" * 64)]}
    after_data = merge_source_states(None, data_one, scope="data")
    after_geo = merge_source_states(after_data, geo, scope="geospatial")
    after_second_data = merge_source_states(after_geo, data_two, scope="data")
    assert {item["source_id"] for item in after_geo["sources"]} == {"ispra-soil", "copernicus-forests"}
    assert {item["source_id"] for item in after_second_data["sources"]} == {"ispra-soil", "copernicus-forests"}
    assert next(item for item in after_second_data["sources"] if item["source_id"] == "copernicus-forests")["sha256"] == "2" * 64


def test_scope_all_replaces_state_and_drops_obsolete_entries() -> None:
    old = {"schemaVersion": 1, "sources": [{
        "source_id": "ispra-old", "asset_path": "ispra/old.xlsx", "resolved_url": "https://example/old",
        "etag": None, "last_modified": None, "sha256": "1" * 64, "bytes": 1,
        "dataset_version": None, "period": None, "checked_at": "2024-01-01T00:00:00Z",
    }]}
    current = {"schemaVersion": 1, "sources": [{
        "source_id": "ispra-new", "asset_path": "ispra/new.xlsx", "resolved_url": "https://example/new",
        "etag": None, "last_modified": None, "sha256": "2" * 64, "bytes": 2,
        "dataset_version": None, "period": None, "checked_at": "2024-01-02T00:00:00Z",
    }]}

    assert merge_source_states(old, current, scope="all") == current


def test_dynamic_landing_url_change_is_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"schemaVersion": 1, "sources": [{
        "source_id": "ispra", "asset_path": "asset.xlsx", "resolved_url": "https://official.example/old.xlsx",
        "landing_url": "https://official.example/landing", "download_link_filename_pattern": r"asset-\\d+\\.xlsx",
        "etag": None, "last_modified": None, "sha256": "a" * 64, "bytes": 1,
        "dataset_version": None, "period": None, "checked_at": "2024-01-01T00:00:00Z",
    }]}
    monkeypatch.setattr("stato_italia.source_state.resolve_download_url", lambda _source: "https://official.example/new.xlsx")
    result = check_persisted_sources(state, scope="data")
    assert result["changed"] is True
    assert result["sources"][0]["reason"] == "resolved_url_changed"


def test_idrogeo_preflight_checks_composite_exports_not_api_base(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"schemaVersion": 1, "sources": [{
        "source_id": "ispra-idrogeo-risk-2024",
        "asset_path": "ispra-idrogeo-risk-2024/idrogeo-risk-api-responses.zip",
        "resolved_url": "https://idrogeo.example/api/pir", "etag": None, "last_modified": None,
        "sha256": "a" * 64, "bytes": 100, "dataset_version": None, "period": None,
        "checked_at": "2024-01-01T00:00:00Z", "preflight_method": "idrogeo_exports_v1",
        "source_signature": "b" * 64,
    }]}
    monkeypatch.setattr(
        "stato_italia.dissesto.check_dissesto_source",
        lambda expected, staged_path=None: {
            "changed": expected != "b" * 64, "signature": "b" * 64,
            "exports": 4, "staged_path": staged_path,
        },
    )
    monkeypatch.setattr(
        "stato_italia.source_state.requests.get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("generic GET must not run")),
    )

    result = check_persisted_sources(state, scope="data")

    assert result["changed"] is False
    assert result["sources"][0]["source_id"] == "ispra-idrogeo-risk-2024"
    assert result["sources"][0]["asset_path"] == "ispra-idrogeo-risk-2024/idrogeo-risk-api-responses.zip"
    assert result["sources"][0]["status"] == "unchanged"
    assert result["sources"][0]["method"] == "idrogeo_exports_v1"
    assert result["sources"][0]["exports"] == 4


def test_idrogeo_preflight_marks_trusted_baseline_unverifiable(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"schemaVersion": 1, "sources": [{
        "source_id": "ispra-idrogeo-risk-2024",
        "asset_path": "ispra-idrogeo-risk-2024/idrogeo-risk-api-responses.zip",
        "resolved_url": "https://idrogeo.example/api/pir", "etag": None, "last_modified": None,
        "sha256": "a" * 64, "bytes": 100, "dataset_version": None, "period": None,
        "checked_at": "2024-01-01T00:00:00Z", "preflight_method": "idrogeo_exports_v1",
        "source_signature": "b" * 64,
    }]}
    monkeypatch.setattr(
        "stato_italia.dissesto.check_dissesto_source",
        lambda _expected, staged_path=None: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    result = check_persisted_sources(state, scope="data")

    assert result["changed"] is False
    assert result["sourcesChanged"] == 0
    assert result["sourcesUnverifiable"] == 1
    assert result["sources"][0]["status"] == "unverifiable"


def test_release_membership_excludes_old_raw_even_with_valid_sidecar(tmp_path: Path) -> None:
    root = tmp_path / "data"
    declared = _asset(root / "raw", "used.xlsx")
    old = _asset(root / "raw", "old.xlsx")
    source_state = tmp_path / "source-state.json"
    source_state.write_text("{}")
    artifacts = _release_artifacts(root, [declared, declared.with_suffix(declared.suffix + ".metadata.json")], source_state)
    logical_paths = {artifact.logical_path for artifact in artifacts}
    assert str(old.relative_to(root)) not in logical_paths
    assert str(old.with_suffix(old.suffix + ".metadata.json").relative_to(root)) not in logical_paths
