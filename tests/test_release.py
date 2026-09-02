from pathlib import Path

import pytest

from io import BytesIO
from types import SimpleNamespace

from botocore.exceptions import ClientError

from stato_italia.release import (
    CarriedArtifact,
    LocalObjectStore,
    R2ObjectStore,
    ReleaseArtifact,
    active_release,
    artifact_scope,
    artifact_family,
    carry_forward_active_artifacts,
    hydrate_active_artifact,
    publish_release,
    rollback,
)


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


def test_release_json_upload_failure_never_advances_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    store = LocalObjectStore(tmp_path / "store")
    publish_release(store, "r1", [first])
    original = store.put_json

    def fail_release(key: str, payload: dict, immutable: bool) -> None:
        if key == "releases/r2/release.json":
            raise RuntimeError("simulated release upload failure")
        original(key, payload, immutable)

    monkeypatch.setattr(store, "put_json", fail_release)
    with pytest.raises(RuntimeError, match="simulated release upload failure"):
        publish_release(store, "r2", [second])

    assert store.read_json("manifest.json")["releaseId"] == "r1"


def test_carry_forward_references_unchanged_active_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "forest.parquet"
    artifact.write_bytes(b"forest")
    store = LocalObjectStore(tmp_path / "store")
    publish_release(store, "r1", [ReleaseArtifact(artifact, "canonical/forests/algorithm_version=v1/observations.parquet")])
    carried = carry_forward_active_artifacts(store, set(), scope="data")
    assert len(carried) == 1
    second = publish_release(store, "r2", carried)
    assert second["publishMetrics"]["objectsUploaded"] == 0
    assert second["publishMetrics"]["objectsReused"] == 1


def test_artifact_ownership_is_explicit() -> None:
    assert artifact_scope("raw/infc-2015-forests/volume.zip") == "geospatial"
    assert artifact_scope("raw/copernicus-hrl-forests/catalog.json") == "geospatial"
    assert artifact_scope("canonical/forests/algorithm_version=v2/zonal_statistics.parquet") == "geospatial"
    assert artifact_scope("delivery/foreste/index.json") == "geospatial"
    assert artifact_scope("raw/ispra-soil-2025/new.xlsx") == "data"
    assert artifact_scope("canonical/forests/dataset_version=infc2015/observations.parquet") == "geospatial"
    assert artifact_scope("canonical/territories/reference_year=2025/region.parquet") == "shared"
    assert artifact_scope("delivery/territory-insights/index.json") == "shared"
    with pytest.raises(ValueError, match="no explicit scope ownership"):
        artifact_scope("canonical/unknown/data.parquet")


def test_artifact_processing_family_is_explicit() -> None:
    assert artifact_family("raw/ispra-soil-2025/source.xlsx") == "soil"
    assert artifact_family("delivery/soil/index.json") == "soil_delivery"
    assert artifact_family("delivery/soil/geometry/istat-region-2025.pmtiles") == "soil_geometry_2025"
    assert artifact_family("delivery/dissesto/geometry/istat-region-2024.pmtiles") == "dissesto_geometry_2024"
    assert artifact_family("delivery/emissions/geometry/istat-province-2023.pmtiles") == "emissions_geometry_2023"
    assert artifact_family("delivery/foreste/geometry/istat-region-2023.pmtiles") == "forest_geometry_2023"
    assert artifact_family("delivery/territory-insights/index.json") == "territory_insights"


def test_carry_forward_replaces_whole_scope_and_never_carries_all(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    artifacts = []
    for logical_path, body in (
        ("raw/ispra-soil-2025/old.xlsx", b"old-data"),
        ("raw/infc-2015-forests/volume.zip", b"infc"),
        ("canonical/forests/dataset_version=infc2015/observations.parquet", b"infc-canonical"),
        ("raw/copernicus-hrl-forests/catalog.json", b"geo"),
        ("delivery/foreste/index.json", b"forest-delivery"),
        ("canonical/territories/reference_year=2025/region.parquet", b"shared"),
    ):
        path = tmp_path / logical_path.replace("/", "-")
        path.write_bytes(body)
        artifacts.append(ReleaseArtifact(path, logical_path))
    publish_release(store, "r1", artifacts)

    data_run = carry_forward_active_artifacts(store, set(), scope="data")
    geo_run = carry_forward_active_artifacts(store, set(), scope="geospatial")
    all_run = carry_forward_active_artifacts(store, set(), scope="all")

    assert {item.logical_path for item in data_run} == {
        "raw/infc-2015-forests/volume.zip",
        "canonical/forests/dataset_version=infc2015/observations.parquet",
        "raw/copernicus-hrl-forests/catalog.json",
        "delivery/foreste/index.json",
    }
    assert {item.logical_path for item in geo_run} == {"raw/ispra-soil-2025/old.xlsx"}
    assert all_run == []


def test_family_aware_carry_reuses_same_scope_and_shared_but_drops_affected_family(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    artifacts = []
    for logical_path, body in (
        ("raw/ispra-soil-2025/old.xlsx", b"obsolete-soil"),
        ("canonical/soil/dataset_version=v1/observations.parquet", b"obsolete-canonical"),
        ("raw/ispra-bigbang-10/water.xlsx", b"water"),
        ("canonical/water/dataset_version=v1/observations.parquet", b"water-canonical"),
        ("canonical/territories/reference_year=2025/region.parquet", b"territory"),
        ("delivery/territory-insights/index.json", b"insights"),
    ):
        path = tmp_path / logical_path.replace("/", "-")
        path.write_bytes(body)
        artifacts.append(ReleaseArtifact(path, logical_path))
    publish_release(store, "r1", artifacts)

    carried = carry_forward_active_artifacts(
        store, set(), scope="data", affected_families={"soil"},
    )

    assert {item.logical_path for item in carried} == {
        "raw/ispra-bigbang-10/water.xlsx",
        "canonical/water/dataset_version=v1/observations.parquet",
        "canonical/territories/reference_year=2025/region.parquet",
        "delivery/territory-insights/index.json",
    }


def test_changed_shared_output_is_replaced_while_unrelated_shared_survives(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    territory = tmp_path / "territory.parquet"
    insights = tmp_path / "insights.json"
    territory.write_bytes(b"territory")
    insights.write_bytes(b"old-insights")
    publish_release(store, "r1", [
        ReleaseArtifact(territory, "canonical/territories/reference_year=2025/region.parquet"),
        ReleaseArtifact(insights, "delivery/territory-insights/index.json"),
    ])

    carried = carry_forward_active_artifacts(
        store, set(), scope="data", affected_families={"territory_insights"},
    )

    assert {item.logical_path for item in carried} == {
        "canonical/territories/reference_year=2025/region.parquet",
    }


def test_geometry_replacement_is_domain_and_reference_year_specific(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    artifacts = []
    for logical_path in (
        "delivery/emissions/geometry/istat-province-2019.pmtiles",
        "delivery/emissions/geometry/istat-province-2023.pmtiles",
        "delivery/foreste/geometry/istat-region-2015.pmtiles",
        "delivery/foreste/geometry/istat-region-2023.pmtiles",
    ):
        path = tmp_path / logical_path.replace("/", "-")
        path.write_bytes(logical_path.encode())
        artifacts.append(ReleaseArtifact(path, logical_path))
    publish_release(store, "r1", artifacts)

    carried = carry_forward_active_artifacts(
        store, set(), scope="data",
        affected_families={"emissions_geometry_2023"},
    )
    assert {item.logical_path for item in carried} == {
        "delivery/emissions/geometry/istat-province-2019.pmtiles",
        "delivery/foreste/geometry/istat-region-2015.pmtiles",
        "delivery/foreste/geometry/istat-region-2023.pmtiles",
    }

    carried = carry_forward_active_artifacts(
        store, set(), scope="geospatial",
        affected_families={"forest_geometry_2023"},
    )
    assert {item.logical_path for item in carried} == {
        "delivery/emissions/geometry/istat-province-2019.pmtiles",
        "delivery/emissions/geometry/istat-province-2023.pmtiles",
        "delivery/foreste/geometry/istat-region-2015.pmtiles",
    }


def test_hydration_replaces_stale_cache_with_active_release(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    active = tmp_path / "active.parquet"
    active.write_bytes(b"V2")
    publish_release(store, "r2", [ReleaseArtifact(active, "canonical/soil/observations.parquet")])
    destination = tmp_path / "cache" / "observations.parquet"
    destination.parent.mkdir()
    destination.write_bytes(b"V1")

    hydrate_active_artifact(store, "canonical/soil/observations.parquet", destination)

    assert destination.read_bytes() == b"V2"


def test_hydration_downloads_missing_active_release_asset(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    active = tmp_path / "active.parquet"
    active.write_bytes(b"active-V2")
    publish_release(store, "r2", [ReleaseArtifact(active, "canonical/soil/observations.parquet")])
    destination = tmp_path / "empty-cache" / "observations.parquet"

    hydrate_active_artifact(store, "canonical/soil/observations.parquet", destination)

    assert destination.read_bytes() == b"active-V2"


def test_hydration_reuses_valid_local_asset_without_object_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalObjectStore(tmp_path / "store")
    active = tmp_path / "active.parquet"
    active.write_bytes(b"active-V2")
    publish_release(store, "r2", [ReleaseArtifact(active, "canonical/soil/observations.parquet")])
    destination = tmp_path / "cache" / "observations.parquet"
    destination.parent.mkdir()
    destination.write_bytes(b"active-V2")
    monkeypatch.setattr(
        store, "get_file",
        lambda *_args: (_ for _ in ()).throw(AssertionError("active object downloaded")),
    )

    hydrate_active_artifact(store, "canonical/soil/observations.parquet", destination)

    assert destination.read_bytes() == b"active-V2"


def test_failed_hydration_keeps_cache_and_manifest_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = LocalObjectStore(tmp_path / "store")
    active = tmp_path / "active.parquet"
    active.write_bytes(b"V2")
    publish_release(store, "r2", [ReleaseArtifact(active, "canonical/soil/observations.parquet")])
    destination = tmp_path / "cache.parquet"
    destination.write_bytes(b"V1")
    before = store.read_json("manifest.json")

    def corrupt(_key: str, target: Path) -> None:
        target.write_bytes(b"corrupt")

    monkeypatch.setattr(store, "get_file", corrupt)
    with pytest.raises(ValueError, match="checksum mismatch"):
        hydrate_active_artifact(store, "canonical/soil/observations.parquet", destination)

    assert destination.read_bytes() == b"V1"
    assert store.read_json("manifest.json") == before


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


def test_missing_carried_object_fails_before_manifest_update(tmp_path: Path) -> None:
    source = tmp_path / "forest.parquet"
    source.write_bytes(b"forest")
    store = LocalObjectStore(tmp_path / "store")
    publish_release(store, "r1", [ReleaseArtifact(source, "canonical/forests/algorithm_version=v1/data.parquet")])
    before = store.read_json("manifest.json")
    carried = carry_forward_active_artifacts(store, set(), scope="data")
    object_path = store.root / carried[0].key
    object_path.unlink()

    with pytest.raises(FileNotFoundError, match="Referenced immutable object is missing"):
        publish_release(store, "r2", carried)

    assert store.read_json("manifest.json") == before


def test_carried_descriptor_must_match_content_addressed_key(tmp_path: Path) -> None:
    source = tmp_path / "forest.parquet"
    source.write_bytes(b"forest")
    store = LocalObjectStore(tmp_path / "store")
    publish_release(store, "r1", [ReleaseArtifact(source, "canonical/forests/algorithm_version=v1/data.parquet")])
    item = carry_forward_active_artifacts(store, set(), scope="data")[0]
    invalid = CarriedArtifact(
        key=item.key, sha256="0" * 64, bytes=item.bytes, name=item.name,
        logical_path=item.logical_path,
    )

    with pytest.raises(ValueError, match="Invalid immutable object descriptor"):
        publish_release(store, "r2", [invalid])


def test_active_manifest_must_match_release_descriptor(tmp_path: Path) -> None:
    source = tmp_path / "source.parquet"
    source.write_bytes(b"source")
    store = LocalObjectStore(tmp_path / "store")
    publish_release(store, "r1", [source])
    manifest = store.read_json("manifest.json")
    manifest["releaseId"] = "r2"
    store.put_json("manifest.json", manifest, immutable=False)

    with pytest.raises(ValueError, match="manifest and immutable release descriptor disagree"):
        active_release(store)


@pytest.mark.parametrize(
    ("code", "status"),
    (("AccessDenied", 403), ("AccessDenied", 404), ("InternalError", 500)),
)
def test_r2_exists_does_not_hide_auth_or_server_errors(code: str, status: int) -> None:
    error = ClientError(
        {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "HeadObject",
    )

    class Client:
        exceptions = SimpleNamespace(ClientError=ClientError)

        def head_object(self, **_kwargs):
            raise error

    store = object.__new__(R2ObjectStore)
    store.bucket = "test"
    store.client = Client()

    with pytest.raises(ClientError):
        store.exists("manifest.json")


def test_r2_exists_returns_false_only_for_real_not_found() -> None:
    error = ClientError(
        {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        "HeadObject",
    )

    class Client:
        exceptions = SimpleNamespace(ClientError=ClientError)

        def head_object(self, **_kwargs):
            raise error

    store = object.__new__(R2ObjectStore)
    store.bucket = "test"
    store.client = Client()

    assert store.exists("missing") is False
