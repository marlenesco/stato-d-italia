import json
from pathlib import Path

import pytest

from stato_italia.source_state import (
    build_source_state,
    check_persisted_sources,
    declared_raw_paths,
    source_state_changed,
)


def _asset(root: Path, name: str, *, checksum: str = "a" * 64) -> Path:
    asset = root / "ispra" / name
    asset.parent.mkdir(parents=True)
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
