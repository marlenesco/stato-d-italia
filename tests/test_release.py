from pathlib import Path

import pytest

from stato_italia.release import LocalObjectStore, ReleaseArtifact, publish_release, rollback


def test_release_and_rollback_are_pointer_only(tmp_path: Path) -> None:
    artifact = tmp_path / "source.parquet"
    artifact.write_bytes(b"canonical")
    store = LocalObjectStore(tmp_path / "store")
    first = publish_release(store, "r1", [artifact])
    second = publish_release(store, "r2", [artifact])
    assert first["releaseId"] == "r1"
    assert second["releaseId"] == "r2"
    assert rollback(store, "r1")["releaseId"] == "r1"
    assert store.read_json("manifest.json")["releaseId"] == "r1"


def test_reused_object_does_not_add_storage(tmp_path: Path) -> None:
    artifact = tmp_path / "source.parquet"
    artifact.write_bytes(b"canonical")
    store = LocalObjectStore(tmp_path / "store")
    first = publish_release(store, "r1", [ReleaseArtifact(artifact, "canonical/source.parquet")])
    second = publish_release(store, "r2", [ReleaseArtifact(artifact, "canonical/source.parquet")])
    assert first["publishMetrics"]["objectsUploaded"] == 1
    assert second["publishMetrics"] == {
        "objectsUploaded": 0, "objectsReused": 1, "bytesUploaded": 0,
        "releaseReferencedBytes": len(b"canonical"),
    }


def test_failure_never_advances_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    store = LocalObjectStore(tmp_path / "store")
    publish_release(store, "r1", [first])
    original = store.put_file

    def fail_second(key: str, source: Path, immutable: bool) -> bool:
        if source == second:
            raise RuntimeError("simulated upload failure")
        return original(key, source, immutable)

    monkeypatch.setattr(store, "put_file", fail_second)
    with pytest.raises(RuntimeError, match="simulated upload failure"):
        publish_release(store, "r2", [first, second])
    assert store.read_json("manifest.json")["releaseId"] == "r1"
