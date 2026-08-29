import json
from pathlib import Path

import pytest

from stato_italia.source_state import (
    build_source_state,
    check_persisted_sources,
    declared_raw_paths,
    merge_source_states,
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
