from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import boto3

from .common import json_dump, now_iso, sha256_file


class ObjectStore:
    def put_file(self, key: str, source: Path, immutable: bool) -> bool: ...
    def put_json(self, key: str, payload: dict, immutable: bool) -> None: ...
    def read_json(self, key: str) -> dict: ...
    def exists(self, key: str) -> bool: ...
    def get_file(self, key: str, destination: Path) -> None: ...


def active_release(store: ObjectStore) -> dict | None:
    """Read immutable active release through sole mutable manifest pointer."""
    if not store.exists("manifest.json"):
        return None
    manifest = store.read_json("manifest.json")
    return store.read_json(str(manifest["releaseKey"]))


def active_source_state(store: ObjectStore, logical_path: str) -> dict | None:
    release = active_release(store)
    if release is None:
        return None
    matches = [item for item in release.get("objects", []) if item.get("logicalPath") == logical_path]
    if len(matches) > 1:
        raise ValueError(f"Active release has duplicate source-state artifact: {logical_path}")
    return store.read_json(matches[0]["key"]) if matches else None


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
                if existing["Metadata"].get("sha256") != checksum:
                    raise ValueError(f"Immutable object collision at {key}")
                return False
            except self.client.exceptions.ClientError as error:
                if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
                    raise
        self.client.upload_file(
            str(source), self.bucket, key,
            ExtraArgs={"CacheControl": "public, max-age=31536000, immutable" if immutable else "public, max-age=300", "Metadata": {"sha256": checksum}},
        )
        response = self.client.head_object(Bucket=self.bucket, Key=key)
        if response["Metadata"].get("sha256") != checksum:
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
                if error.response.get("Error", {}).get("Code") not in {"404", "NoSuchKey", "NotFound"}:
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
        except self.client.exceptions.ClientError:
            return False

    def get_file(self, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(destination))


def publish_release(store: ObjectStore, release_id: str, artifacts: list[Path | ReleaseArtifact | CarriedArtifact]) -> dict:
    """Upload immutable content first, then atomically advance sole mutable pointer."""
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
    logical_paths = [item["logicalPath"] for item in objects]
    if len(logical_paths) != len(set(logical_paths)):
        raise ValueError("Release has duplicate logical paths")
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


def carry_forward_active_artifacts(store: ObjectStore, replacing_logical_paths: set[str]) -> list[CarriedArtifact]:
    """Carry inactive scope objects by immutable reference, no download/upload."""
    release = active_release(store)
    if release is None:
        return []
    carried = []
    for item in release.get("objects", []):
        logical_path = str(item["logicalPath"])
        if logical_path in replacing_logical_paths or logical_path == "metadata/source-state.json":
            continue
        carried.append(CarriedArtifact(
            key=str(item["key"]), sha256=str(item["sha256"]), bytes=int(item["bytes"]),
            name=str(item["name"]), logical_path=logical_path,
        ))
    return carried


def hydrate_active_artifact(store: ObjectStore, logical_path: str, destination: Path) -> None:
    """Fetch one immutable dependency from active release only when runner lacks it."""
    if destination.exists():
        return
    release = active_release(store)
    if release is None:
        raise FileNotFoundError(f"No active release to hydrate required artifact: {logical_path}")
    matches = [item for item in release.get("objects", []) if item.get("logicalPath") == logical_path]
    if len(matches) != 1:
        raise FileNotFoundError(f"Active release lacks required artifact: {logical_path}")
    store.get_file(str(matches[0]["key"]), destination)
    if sha256_file(destination) != matches[0]["sha256"]:
        raise ValueError(f"Hydrated artifact checksum mismatch: {logical_path}")


def rollback(store: ObjectStore, release_id: str) -> dict:
    key = f"releases/{release_id}/release.json"
    if not store.exists(key):
        raise ValueError(f"Release does not exist: {release_id}")
    manifest = {"schemaVersion": 1, "releaseId": release_id, "generatedAt": now_iso(), "releaseKey": key, "rollback": True}
    store.put_json("manifest.json", manifest, immutable=False)
    return manifest
