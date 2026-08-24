from pathlib import Path

from stato_italia.release import LocalObjectStore, publish_release, rollback


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

