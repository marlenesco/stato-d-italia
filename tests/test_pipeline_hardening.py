import json
from argparse import Namespace
from pathlib import Path

import pandas as pd
import pytest

import stato_italia.cli as cli
from stato_italia.cli import _active_source_state_with_legacy_bootstrap, _publish_scoped, _run_geospatial, _validate_release_coherence
from stato_italia.release import LocalObjectStore, ReleaseArtifact, publish_release


def test_workflows_serialize_publish_and_bootstrap_all_is_explicit() -> None:
    repository = Path(__file__).parents[1]
    data_workflow = (repository / ".github/workflows/ingest-data.yml").read_text()
    geospatial_workflow = (repository / ".github/workflows/ingest-geospatial.yml").read_text()
    concurrency = "group: stato-d-italia-r2-publish\n  cancel-in-progress: false"
    assert concurrency in data_workflow
    assert concurrency in geospatial_workflow
    assert "bootstrap_all:" in geospatial_workflow
    assert "if: ${{ !inputs.bootstrap_all }}" in geospatial_workflow
    assert "--scope ${{ inputs.bootstrap_all && 'all' || 'geospatial' }}" in geospatial_workflow
    assert "timeout-minutes: 360" in geospatial_workflow
    assert "FOREST_PROCESSING_MODE: raster" in geospatial_workflow
    assert "INFC_HTTPS_PROXIES: ${{ secrets.INFC_HTTPS_PROXIES }}" in data_workflow
    assert "INFC_HTTPS_PROXIES: ${{ secrets.INFC_HTTPS_PROXIES }}" in geospatial_workflow


def _entry(source_id: str, asset_path: str, checksum: str, *, kind: str | None = None) -> dict:
    entry = {
        "source_id": source_id, "asset_path": asset_path, "resolved_url": "https://official.example/asset",
        "etag": None, "last_modified": None, "sha256": checksum, "bytes": 8,
        "dataset_version": None, "period": None, "checked_at": "2026-08-30T00:00:00Z",
    }
    if kind:
        entry["kind"] = kind
    return entry


def _raw(root: Path, logical_path: str) -> tuple[Path, Path]:
    raw = root / logical_path
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(b"official")
    sidecar = Path(f"{raw}.metadata.json")
    sidecar.write_text(json.dumps({"source_id": "test", "sha256": "a" * 64, "bytes": 8}))
    return raw, sidecar


def test_legacy_active_release_bootstraps_source_state_from_raw_sidecars(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    raw = tmp_path / "source.xlsx"
    raw.write_bytes(b"official")
    sidecar = tmp_path / "source.xlsx.metadata.json"
    sidecar.write_text(json.dumps({
        "source_id": "ispra-source", "resolved_url": "https://official.example/source.xlsx",
        "sha256": "a" * 64, "bytes": 8, "acquired_at": "2026-08-30T00:00:00Z",
    }))
    publish_release(store, "legacy", [
        ReleaseArtifact(raw, "raw/ispra-source/source.xlsx"),
        ReleaseArtifact(sidecar, "raw/ispra-source/source.xlsx.metadata.json"),
    ])

    state = _active_source_state_with_legacy_bootstrap(store)

    assert state is not None
    assert state["sources"][0]["asset_path"] == "ispra-source/source.xlsx"
    assert state["sources"][0]["sha256"] == "a" * 64


def test_scoped_noops_and_data_geospatial_data_preserve_other_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    output = root / "artifacts"
    store = LocalObjectStore(output / "object-store")
    monkeypatch.setattr(cli, "_validate_release_coherence", lambda *_args, **_kwargs: None)
    data_raw, data_sidecar = _raw(root, "raw/ispra-source/data.xlsx")
    data_state = {"schemaVersion": 1, "sources": [_entry("ispra-source", "ispra-source/data.xlsx", "a" * 64)]}

    first, first_metrics, first_publication = _publish_scoped(
        store=store, root=root, output=output, release_id="data-r1", scope="all",
        previous_state=None, current_state=data_state, declared_paths=[data_raw, data_sidecar], changed=True,
    )
    assert first_publication["changed"] is True
    assert first_metrics["sourceChecks"] == 1

    second, second_metrics, second_publication = _publish_scoped(
        store=store, root=root, output=output, release_id="data-r2", scope="data",
        previous_state=data_state, current_state=data_state, declared_paths=[data_raw, data_sidecar], changed=False,
    )
    assert second_publication["changed"] is False
    assert second["releaseId"] == first["releaseId"]
    assert second_metrics["bytesUploadedToR2"] == 0
    assert second_metrics["sourceChecks"] == 1
    assert second_metrics["carriedSources"] == 0

    geo_raw = root / "raw/copernicus-hrl-forests/catalog.json"
    geo_raw.parent.mkdir(parents=True)
    geo_raw.write_bytes(b"catalog2")
    geo_state = {"schemaVersion": 1, "sources": [
        _entry("copernicus-hrl-forests", "copernicus-hrl-forests/catalog.json", "b" * 64, kind="catalog"),
    ]}
    merged = cli.merge_source_states(data_state, geo_state, scope="geospatial")
    third, third_metrics, third_publication = _publish_scoped(
        store=store, root=root, output=output, release_id="geo-r1", scope="geospatial",
        previous_state=data_state, current_state=geo_state, declared_paths=[geo_raw], changed=True,
    )
    assert third_publication["changed"] is True
    assert third_metrics["sourceChecks"] == 1
    assert third_metrics["carriedSources"] == 1
    release = store.read_json(third["releaseKey"])
    assert {item["logicalPath"] for item in release["objects"]} >= {
        "raw/ispra-source/data.xlsx", "raw/copernicus-hrl-forests/catalog.json",
    }

    fourth, fourth_metrics, fourth_publication = _publish_scoped(
        store=store, root=root, output=output, release_id="data-r3", scope="data",
        previous_state=merged, current_state=data_state, declared_paths=[data_raw, data_sidecar], changed=False,
    )
    assert fourth_publication["changed"] is False
    assert fourth["releaseId"] == third["releaseId"]
    assert fourth_metrics["bytesUploadedToR2"] == 0
    assert fourth_metrics["sourceChecks"] == 1
    assert fourth_metrics["carriedSources"] == 1

    fifth, fifth_metrics, fifth_publication = _publish_scoped(
        store=store, root=root, output=output, release_id="geo-r2", scope="geospatial",
        previous_state=merged, current_state=geo_state, declared_paths=[geo_raw], changed=False,
    )
    assert fifth_publication["changed"] is False
    assert fifth["releaseId"] == third["releaseId"]
    assert fifth_metrics["bytesUploadedToR2"] == 0


def test_copernicus_release_coherence_rejects_new_state_with_old_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    catalog = root / "raw/copernicus-hrl-forests/catalog.json"
    catalog.parent.mkdir(parents=True)
    catalog.write_bytes(b"catalog-v2")
    zonal = root / f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"
    zonal.parent.mkdir(parents=True)
    pd.DataFrame({"source_asset_sha256": ["1" * 64]}).to_parquet(zonal)
    state_path = tmp_path / "source-state.json"
    state_path.write_text("{}")
    state = {"schemaVersion": 1, "sources": [
        _entry("copernicus-hrl-forests", "copernicus-hrl-forests/catalog.json", "2" * 64, kind="catalog"),
    ]}
    monkeypatch.setattr(cli, "_territory_paths", lambda _canonical: [])
    monkeypatch.setattr(cli, "_validate_data_canonical_provenance", lambda *_args: None)
    monkeypatch.setenv("FOREST_PROCESSING_MODE", "statistical-api")

    with pytest.raises(ValueError, match="signatures differ"):
        _validate_release_coherence(root, state, [
            ReleaseArtifact(catalog, "raw/copernicus-hrl-forests/catalog.json"),
            ReleaseArtifact(zonal, f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"),
            ReleaseArtifact(state_path, "metadata/source-state.json"),
        ], scope="geospatial")


def test_data_release_coherence_rejects_new_state_with_old_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    raw = root / "raw/ispra-soil-2025/data.xlsx"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"data-v2")
    sidecar = Path(f"{raw}.metadata.json")
    sidecar.write_text("{}")
    canonical = root / "canonical/soil/dataset_version=2025-2024-observations/observations.parquet"
    canonical.parent.mkdir(parents=True)
    pd.DataFrame({"source_asset_sha256": ["1" * 64]}).to_parquet(canonical)
    state_path = tmp_path / "source-state.json"
    state_path.write_text("{}")
    state = {"schemaVersion": 1, "sources": [
        _entry("ispra-soil-2025", "ispra-soil-2025/data.xlsx", "2" * 64),
    ]}
    monkeypatch.setattr(cli, "_territory_paths", lambda _canonical: [])
    real_read = pd.read_parquet

    def only_soil(path: Path, **kwargs):
        if Path(path) == canonical:
            return real_read(path, **kwargs)
        return pd.DataFrame({"source_asset_sha256": ["unused"]})

    monkeypatch.setattr(cli.pd, "read_parquet", only_soil)
    artifacts = [
        ReleaseArtifact(raw, "raw/ispra-soil-2025/data.xlsx"),
        ReleaseArtifact(sidecar, "raw/ispra-soil-2025/data.xlsx.metadata.json"),
        ReleaseArtifact(canonical, "canonical/soil/dataset_version=2025-2024-observations/observations.parquet"),
        ReleaseArtifact(state_path, "metadata/source-state.json"),
    ]
    # Membership for other data canonicals is present, but soil provenance is stale.
    for logical_path in (
        "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet",
        "canonical/dissesto/dataset_version=idrogeo-risk-2024/observations.parquet",
        "canonical/emissions/dataset_version=2026-2023-disaggregation/observations.parquet",
        "canonical/emissions/national/greenhouse-gases/dataset_version=2026-1990-2024/observations.parquet",
        "canonical/emissions/national/air-pollutants-nfr/dataset_version=2026-1990-2024/observations.parquet",
        "canonical/forests/dataset_version=infc2015-published-tables/observations.parquet",
    ):
        artifacts.append(ReleaseArtifact(tmp_path / "unused", logical_path))

    with pytest.raises(ValueError, match="Source-state and canonical provenance differ"):
        _validate_release_coherence(root, state, artifacts, scope="data")


def test_geospatial_processing_failure_never_advances_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalObjectStore(tmp_path / "store")
    initial = tmp_path / "initial.parquet"
    initial.write_bytes(b"initial")
    publish_release(store, "r1", [ReleaseArtifact(initial, "canonical/soil/observations.parquet")])
    before = store.read_json("manifest.json")
    monkeypatch.setattr(cli, "_hydrate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "fetch_forests", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("geospatial failed")))
    args = Namespace(offline=False, force=False, report=str(tmp_path / "report.json"))

    with pytest.raises(RuntimeError, match="geospatial failed"):
        _run_geospatial(
            args, root=tmp_path / "data", output=tmp_path / "output", canonical=tmp_path / "data/canonical",
            delivery=tmp_path / "data/delivery", store=store, previous_state=None, release_id="r2",
            started=0.0, started_at="2026-08-30T00:00:00Z",
        )

    assert store.read_json("manifest.json") == before
