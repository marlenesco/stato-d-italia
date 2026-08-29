from pathlib import Path

import pytest

from io import BytesIO
from types import SimpleNamespace

from botocore.exceptions import ClientError

from stato_italia.release import LocalObjectStore, R2ObjectStore, ReleaseArtifact, carry_forward_active_artifacts, publish_release, rollback


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


def test_carry_forward_references_unchanged_active_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "forest.parquet"
    artifact.write_bytes(b"forest")
    store = LocalObjectStore(tmp_path / "store")
    publish_release(store, "r1", [ReleaseArtifact(artifact, "canonical/forests/observations.parquet")])
    carried = carry_forward_active_artifacts(store, set())
    assert len(carried) == 1
    second = publish_release(store, "r2", carried)
    assert second["publishMetrics"]["objectsUploaded"] == 0
    assert second["publishMetrics"]["objectsReused"] == 1


def test_r2_immutable_json_collision_fails() -> None:
    class Client:
        exceptions = SimpleNamespace(ClientError=ClientError)

        def get_object(self, **_kwargs):
            return {"Body": BytesIO(b'{\n  "value": 1\n}\n')}

        def put_object(self, **_kwargs):
            raise AssertionError("immutable collision must not overwrite")

    store = object.__new__(R2ObjectStore)
    store.bucket = "test"
    store.client = Client()
    with pytest.raises(ValueError, match="Immutable object collision"):
        store.put_json("releases/r1/release.json", {"value": 2}, immutable=True)


def test_r2_immutable_json_identical_is_reused() -> None:
    class Client:
        exceptions = SimpleNamespace(ClientError=ClientError)

        def get_object(self, **_kwargs):
            return {"Body": BytesIO(b'{\n  "value": 1\n}\n')}

        def put_object(self, **_kwargs):
            raise AssertionError("identical immutable JSON must not upload")

    store = object.__new__(R2ObjectStore)
    store.bucket = "test"
    store.client = Client()
    store.put_json("releases/r1/release.json", {"value": 1}, immutable=True)
