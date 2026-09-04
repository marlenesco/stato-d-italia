from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import boto3

from .common import json_dump, now_iso, sha256_file


class ObjectStore:
    def put_file(self, key: str, source: Path, immutable: bool) -> bool: ...
    def put_json(self, key: str, payload: dict, immutable: bool) -> None: ...
    def read_json(self, key: str) -> dict: ...
    def exists(self, key: str) -> bool: ...
    def get_file(self, key: str, destination: Path) -> None: ...
    def verify_object(self, key: str, expected_sha256: str, expected_bytes: int) -> None: ...


def _is_not_found(error: Exception) -> bool:
    response = getattr(error, "response", {})
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    if code:
        return code in {"404", "NoSuchKey", "NotFound"}
    return status == 404


def active_release(store: ObjectStore) -> dict | None:
    """Read immutable active release through sole mutable manifest pointer."""
    if not store.exists("manifest.json"):
        return None
    manifest = store.read_json("manifest.json")
    release_key = str(manifest["releaseKey"])
    release = store.read_json(release_key)
    release_id = str(manifest["releaseId"])
    if release_key != f"releases/{release_id}/release.json" or release.get("releaseId") != release_id:
        raise ValueError("Active manifest and immutable release descriptor disagree")
    return release


def active_source_state(store: ObjectStore, logical_path: str) -> dict | None:
    release = active_release(store)
    if release is None:
        return None
    matches = [item for item in release.get("objects", []) if item.get("logicalPath") == logical_path]
    if len(matches) > 1:
        raise ValueError(f"Active release has duplicate source-state artifact: {logical_path}")
    if not matches:
        return None
    _verify_object_record(store, matches[0], logical_path)
    return store.read_json(str(matches[0]["key"]))


@dataclass
class LocalObjectStore(ObjectStore):
    root: Path

    def _path(self, key: str) -> Path:
        return self.root / key

    def put_file(self, key: str, source: Path, immutable: bool) -> bool:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if sha256_file(target) != sha256_file(source):
                raise ValueError(f"Immutable object collision at {key}")
            return False
        shutil.copy2(source, target)
        if sha256_file(target) != sha256_file(source):
            raise ValueError(f"Checksum verification failed for {key}")
        return True

    def put_json(self, key: str, payload: dict, immutable: bool) -> None:
        target = self._path(key)
        if immutable and target.exists() and target.read_text() != __import__("json").dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n":
            raise ValueError(f"Immutable object collision at {key}")
        json_dump(target, payload)

    def read_json(self, key: str) -> dict:
        import json
        return json.loads(self._path(key).read_text())

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def get_file(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self._path(key), destination)

    def verify_object(self, key: str, expected_sha256: str, expected_bytes: int) -> None:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(f"Referenced immutable object is missing: {key}")
        if path.stat().st_size != expected_bytes or sha256_file(path) != expected_sha256:
            raise ValueError(f"Referenced immutable object metadata mismatch: {key}")


@dataclass(frozen=True)
class ReleaseArtifact:
    path: Path
    logical_path: str


@dataclass(frozen=True)
class CarriedArtifact:
    """Immutable object already referenced by active release."""
    key: str
    sha256: str
    bytes: int
    name: str
    logical_path: str


ArtifactScope = Literal["data", "geospatial", "shared"]


def artifact_scope(logical_path: str) -> ArtifactScope:
    """Return explicit release ownership; unknown paths fail closed."""
    if logical_path == "metadata/source-state.json":
        return "shared"
    if logical_path.startswith(("raw/infc-", "raw/copernicus-")):
        return "geospatial"
    if logical_path.startswith("raw/"):
        return "data"
    if logical_path.startswith("canonical/territories/"):
        return "shared"
    if logical_path.startswith("canonical/forests/algorithm_version="):
        return "geospatial"
    if logical_path.startswith("canonical/forests/dataset_version=infc"):
        return "geospatial"
    if logical_path.startswith((
        "canonical/soil/", "canonical/water/", "canonical/dissesto/", "canonical/emissions/",
        "derived/soil/", "derived/water/historical/",
    )):
        return "data"
    if logical_path.startswith("delivery/territory-insights/"):
        return "shared"
    if logical_path.startswith("delivery/foreste/"):
        return "geospatial"
    if logical_path.startswith((
        "delivery/soil/", "delivery/water/", "delivery/dissesto/", "delivery/emissions/",
        # Explicit legacy ownership: a data run removes these old duplicated paths.
        "delivery/delivery/",
    )):
        return "data"
    raise ValueError(f"Release artifact has no explicit scope ownership: {logical_path}")


def artifact_family(logical_path: str) -> str:
    """Return explicit processing family used for selective replacement."""
    artifact_scope(logical_path)
    if logical_path == "metadata/source-state.json":
        return "source_state"
    if logical_path.startswith("delivery/territory-insights/"):
        return "territory_insights"
    if logical_path.startswith("delivery/foreste/geometry/"):
        year = Path(logical_path).stem.rsplit("-", 1)[-1]
        return f"forest_geometry_{year}"
    if logical_path.startswith("delivery/soil/geometry/"):
        return "soil_geometry_2025"
    if logical_path.startswith("delivery/dissesto/geometry/"):
        return "dissesto_geometry_2024"
    if logical_path.startswith("delivery/emissions/geometry/"):
        year = Path(logical_path).stem.rsplit("-", 1)[-1]
        return f"emissions_geometry_{year}"
    if logical_path.startswith(("raw/infc-", "canonical/forests/dataset_version=infc")):
        return "infc"
    if logical_path.startswith(("raw/copernicus-", "canonical/forests/algorithm_version=")):
        return "copernicus"
    if logical_path.startswith("delivery/foreste/"):
        return "forest_delivery"
    if logical_path.startswith("delivery/soil/"):
        return "soil_delivery"
    if logical_path.startswith("delivery/water/"):
        return "water_delivery"
    if logical_path.startswith("delivery/dissesto/"):
        return "dissesto_delivery"
    if logical_path.startswith("delivery/emissions/"):
        return "emissions_delivery"
    if logical_path.startswith(("raw/istat-administrative-boundaries/", "canonical/territories/")):
        return "boundaries"
    if logical_path.startswith(("raw/ispra-soil-", "canonical/soil/", "derived/soil/")):
        return "soil"
    if logical_path.startswith("derived/water/historical/"):
        return "water_historical"
    if logical_path.startswith(("raw/ispra-bigbang-", "canonical/water/")):
        return "water"
    if logical_path.startswith(("raw/ispra-idrogeo-", "canonical/dissesto/")):
        return "dissesto"
    if logical_path.startswith(("raw/ispra-emissions-", "canonical/emissions/")):
        return "emissions"
    if logical_path.startswith("delivery/delivery/"):
        return "legacy_delivery"
    raise ValueError(f"Release artifact has no explicit processing family: {logical_path}")


class R2ObjectStore(ObjectStore):
    def __init__(self) -> None:
        required = ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET")
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError(f"R2 publish requires: {', '.join(missing)}")
        self.bucket = os.environ["R2_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=os.environ["R2_ENDPOINT"],
            aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

    def put_file(self, key: str, source: Path, immutable: bool) -> bool:
        checksum = sha256_file(source)
        if immutable:
            try:
                existing = self.client.head_object(Bucket=self.bucket, Key=key)
                if (
                    existing["Metadata"].get("sha256") != checksum
                    or existing.get("ContentLength") != source.stat().st_size
                ):
                    raise ValueError(f"Immutable object collision at {key}")
                return False
            except self.client.exceptions.ClientError as error:
                if not _is_not_found(error):
                    raise
        self.client.upload_file(
            str(source), self.bucket, key,
            ExtraArgs={"CacheControl": "public, max-age=31536000, immutable" if immutable else "public, max-age=300", "Metadata": {"sha256": checksum}},
        )
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        if (
            response["Metadata"].get("sha256") != checksum
            or response.get("ContentLength") != source.stat().st_size
        ):
            raise ValueError(f"R2 checksum verification failed for {key}")
        return True

    def put_json(self, key: str, payload: dict, immutable: bool) -> None:
        import json
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
        if immutable:
            try:
                existing = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
                if existing != body:
                    raise ValueError(f"Immutable object collision at {key}")
                return
            except self.client.exceptions.ClientError as error:
                if not _is_not_found(error):
                    raise
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json",
            CacheControl="public, max-age=31536000, immutable" if immutable else "public, max-age=300",
        )

    def read_json(self, key: str) -> dict:
        import json
        return json.loads(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except self.client.exceptions.ClientError as error:
            if _is_not_found(error):
                return False
            raise

    def get_file(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(destination))

    def verify_object(self, key: str, expected_sha256: str, expected_bytes: int) -> None:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.ClientError as error:
            if _is_not_found(error):
                raise FileNotFoundError(f"Referenced immutable object is missing: {key}") from error
            raise
        actual_sha256 = response.get("Metadata", {}).get("sha256")
        actual_bytes = response.get("ContentLength")
        if actual_sha256 != expected_sha256 or actual_bytes != expected_bytes:
            raise ValueError(f"Referenced immutable object metadata mismatch: {key}")


def _verify_object_record(store: ObjectStore, record: dict, logical_path: str) -> None:
    key = str(record["key"])
    checksum = str(record["sha256"])
    size = int(record["bytes"])
    name = str(record["name"])
    parts = key.split("/")
    if (
        len(parts) < 4
        or parts[0:2] != ["objects", "sha256"]
        or parts[2] != checksum
        or parts[-1] != name
    ):
        raise ValueError(f"Invalid immutable object descriptor: {logical_path}")
    store.verify_object(key, checksum, size)


def _verify_carried_artifact(store: ObjectStore, artifact: CarriedArtifact) -> None:
    _verify_object_record(store, {
        "key": artifact.key, "sha256": artifact.sha256,
        "bytes": artifact.bytes, "name": artifact.name,
    }, artifact.logical_path)


def publish_release(store: ObjectStore, release_id: str, artifacts: list[Path | ReleaseArtifact | CarriedArtifact]) -> dict:
    """Upload immutable content first, then atomically advance sole mutable pointer."""
    declared_logical_paths = [
        artifact.logical_path if isinstance(artifact, (ReleaseArtifact, CarriedArtifact)) else artifact.name
        for artifact in artifacts
    ]
    if len(declared_logical_paths) != len(set(declared_logical_paths)):
        raise ValueError("Release has duplicate logical paths")
    for artifact in artifacts:
        if isinstance(artifact, CarriedArtifact):
            _verify_carried_artifact(store, artifact)
    objects = []
    uploaded_objects = 0
    reused_objects = 0
    bytes_uploaded = 0
    for artifact in artifacts:
        if isinstance(artifact, CarriedArtifact):
            reused_objects += 1
            objects.append({"key": artifact.key, "sha256": artifact.sha256, "bytes": artifact.bytes, "name": artifact.name, "logicalPath": artifact.logical_path})
            continue
        record = artifact if isinstance(artifact, ReleaseArtifact) else ReleaseArtifact(artifact, artifact.name)
        checksum = sha256_file(record.path)
        key = f"objects/sha256/{checksum}/{record.path.name}"
        uploaded = store.put_file(key, record.path, immutable=True)
        if uploaded:
            uploaded_objects += 1
            bytes_uploaded += record.path.stat().st_size
        else:
            reused_objects += 1
        objects.append({"key": key, "sha256": checksum, "bytes": record.path.stat().st_size, "name": record.path.name, "logicalPath": record.logical_path})
    release_key = f"releases/{release_id}/release.json"
    release = {"schemaVersion": 2, "releaseId": release_id, "generatedAt": now_iso(), "objects": objects}
    store.put_json(release_key, release, immutable=True)
    if store.read_json(release_key) != release:
        raise ValueError("Release verification failed")
    manifest = {"schemaVersion": 1, "releaseId": release_id, "generatedAt": now_iso(), "releaseKey": release_key}
    store.put_json("manifest.json", manifest, immutable=False)
    return manifest | {"publishMetrics": {
        "objectsUploaded": uploaded_objects,
        "objectsReused": reused_objects,
        "bytesUploaded": bytes_uploaded,
        "releaseReferencedBytes": sum(item["bytes"] for item in objects),
    }}


def carry_forward_active_artifacts(
    store: ObjectStore, replacing_logical_paths: set[str], *, scope: str,
    affected_families: set[str] | None = None,
) -> list[CarriedArtifact]:
    """Carry immutable unaffected objects; drop every object in replaced families."""
    if scope == "all":
        return []
    if scope not in {"data", "geospatial"}:
        raise ValueError(f"Unsupported artifact carry-forward scope: {scope}")
    carried_scope = "geospatial" if scope == "data" else "data"
    release = active_release(store)
    if release is None:
        return []
    carried = []
    for item in release.get("objects", []):
        logical_path = str(item["logicalPath"])
        owner = artifact_scope(logical_path)
        if logical_path in replacing_logical_paths or logical_path == "metadata/source-state.json":
            continue
        if affected_families is None and owner != carried_scope:
            continue
        if affected_families is not None and artifact_family(logical_path) in affected_families:
            continue
        carried.append(CarriedArtifact(
            key=str(item["key"]), sha256=str(item["sha256"]), bytes=int(item["bytes"]),
            name=str(item["name"]), logical_path=logical_path,
        ))
    return carried


def hydrate_active_artifact(store: ObjectStore, logical_path: str, destination: Path) -> None:
    """Make local accelerator match active release bytes before reuse."""
    release = active_release(store)
    if release is None:
        raise FileNotFoundError(f"No active release to hydrate required artifact: {logical_path}")
    matches = [item for item in release.get("objects", []) if item.get("logicalPath") == logical_path]
    if len(matches) != 1:
        raise FileNotFoundError(f"Active release lacks required artifact: {logical_path}")
    expected = str(matches[0]["sha256"])
    expected_bytes = int(matches[0]["bytes"])
    if (
        destination.is_file()
        and destination.stat().st_size == expected_bytes
        and sha256_file(destination) == expected
    ):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".hydrate", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        store.get_file(str(matches[0]["key"]), temporary)
        if temporary.stat().st_size != expected_bytes or sha256_file(temporary) != expected:
            raise ValueError(f"Hydrated artifact checksum mismatch: {logical_path}")
        temporary.replace(destination)
        if destination.stat().st_size != expected_bytes or sha256_file(destination) != expected:
            raise ValueError(f"Hydrated artifact checksum mismatch after replace: {logical_path}")
    finally:
        temporary.unlink(missing_ok=True)


def rollback(store: ObjectStore, release_id: str) -> dict:
    key = f"releases/{release_id}/release.json"
    if not store.exists(key):
        raise ValueError(f"Release does not exist: {release_id}")
    manifest = {"schemaVersion": 1, "releaseId": release_id, "generatedAt": now_iso(), "releaseKey": key, "rollback": True}
    store.put_json("manifest.json", manifest, immutable=False)
    return manifest
