import json
from argparse import Namespace
from pathlib import Path

import pandas as pd
import pytest

import stato_italia.cli as cli
from stato_italia.cli import (
    _active_source_state_with_legacy_bootstrap,
    _data_downstream_families,
    _geospatial_downstream_families,
    _process_geospatial_forest_sources,
    _publish_scoped,
    _run_geospatial,
    _validate_delivery_dependencies,
    _validate_release_coherence,
)
from stato_italia.ingestion_plan import clear_ingestion_plan, load_ingestion_plan
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
    assert "INFC_HTTPS_PROXIES" not in data_workflow
    assert "INFC_HTTPS_PROXIES: ${{ secrets.INFC_HTTPS_PROXIES }}" in geospatial_workflow
    assert "--plan reports/data-source-check.json" in data_workflow
    assert "--plan reports/geospatial-source-check.json" in geospatial_workflow
    assert "if: steps.preflight.outputs.changed == 'true' || inputs.force" in data_workflow
    assert "if: inputs.bootstrap_all || steps.preflight.outputs.changed == 'true' || inputs.force" in geospatial_workflow
    assert "data/canonical/forests/algorithm_version=forests-zonal-statistics-v2" in data_workflow
    assert "data/raw/infc-2015-forests" in geospatial_workflow


def test_data_scope_uses_carried_forest_input_without_fetch_or_infc_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical"
    zonal = canonical / f"forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"
    zonal.parent.mkdir(parents=True)
    zonal.write_bytes(b"carried-zonal")
    monkeypatch.setattr(
        cli, "fetch_forests",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("data scope fetched forests")),
    )
    monkeypatch.setattr(
        cli, "ingest_infc_forests",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("data scope ingested INFC")),
    )

    forests = cli._run_combined_scope_forests(
        Namespace(scope="data", offline=False, force=False), tmp_path, canonical, previous_source_state=None,
    )

    assert forests == {
        "fetch": {"status": "out_of_scope", "scope": "geospatial"},
        "zonal": {"changed": False, "canonical_bytes": len(b"carried-zonal"), "mode": "carried_forward"},
    }


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
    manifest_before_noop = store.read_json("manifest.json")

    second, second_metrics, second_publication = _publish_scoped(
        store=store, root=root, output=output, release_id="data-r2", scope="data",
        previous_state=data_state, current_state=data_state, declared_paths=[data_raw, data_sidecar], changed=False,
    )
    assert second_publication["changed"] is False
    assert second["releaseId"] == first["releaseId"]
    assert store.read_json("manifest.json") == manifest_before_noop
    assert second_metrics["bytesUploadedToR2"] == 0
    assert second_metrics["objectsUploaded"] == 0
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
    monkeypatch.setattr(cli, "_validate_infc_canonical_provenance", lambda *_args: None)
    monkeypatch.setenv("FOREST_PROCESSING_MODE", "statistical-api")

    with pytest.raises(ValueError, match="signatures differ"):
        _validate_release_coherence(root, state, [
            ReleaseArtifact(catalog, "raw/copernicus-hrl-forests/catalog.json"),
            ReleaseArtifact(zonal, f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"),
            ReleaseArtifact(state_path, "metadata/source-state.json"),
        ], scope="geospatial")


def test_infc_release_coherence_rejects_new_state_with_old_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    raw = root / "raw/infc-2015-forests/volume.zip"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"infc-v2")
    sidecar = Path(f"{raw}.metadata.json")
    sidecar.write_text("{}")
    canonical = root / "canonical/forests/dataset_version=infc2015-published-tables/observations.parquet"
    canonical.parent.mkdir(parents=True)
    pd.DataFrame({"source_asset_sha256": ["1" * 64]}).to_parquet(canonical)
    state_path = tmp_path / "source-state.json"
    state_path.write_text("{}")
    state = {"schemaVersion": 1, "sources": [
        _entry("infc-2015-forests", "infc-2015-forests/volume.zip", "2" * 64),
    ]}
    monkeypatch.setattr(cli, "_territory_paths", lambda _canonical: [])
    monkeypatch.setattr(cli, "_validate_data_canonical_provenance", lambda *_args: None)

    with pytest.raises(ValueError, match="Source-state and canonical provenance differ"):
        _validate_release_coherence(root, state, [
            ReleaseArtifact(raw, "raw/infc-2015-forests/volume.zip"),
            ReleaseArtifact(sidecar, "raw/infc-2015-forests/volume.zip.metadata.json"),
            ReleaseArtifact(canonical, "canonical/forests/dataset_version=infc2015-published-tables/observations.parquet"),
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
    ):
        artifacts.append(ReleaseArtifact(tmp_path / "unused", logical_path))

    with pytest.raises(ValueError, match="Source-state and canonical provenance differ"):
        _validate_release_coherence(root, state, artifacts, scope="data")


def test_forest_delivery_signature_must_match_release_canonicals(tmp_path: Path) -> None:
    infc = tmp_path / "infc.parquet"
    zonal = tmp_path / "zonal.parquet"
    index = tmp_path / "forest-index.json"
    infc.write_bytes(b"infc-v2")
    zonal.write_bytes(b"zonal-v1")
    index.write_text(json.dumps({
        "canonicalSignature": {"infc": "0" * 64, "zonal": "1" * 64},
        "geometry": [], "maps": [], "mapGeometry": {},
    }))

    with pytest.raises(ValueError, match="Forest delivery canonical signatures"):
        _validate_delivery_dependencies([
            ReleaseArtifact(infc, "canonical/forests/dataset_version=infc2015-published-tables/observations.parquet"),
            ReleaseArtifact(zonal, f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"),
            ReleaseArtifact(index, "delivery/foreste/index.json"),
        ], store=None, affected_families={"forest_delivery"})


def test_territory_insights_signature_must_match_all_semantic_inputs(tmp_path: Path) -> None:
    logical_inputs = (
        "canonical/soil/dataset_version=2025-2024-observations/observations.parquet",
        "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet",
        "canonical/dissesto/dataset_version=idrogeo-risk-2024/observations.parquet",
        "canonical/emissions/dataset_version=2026-2023-disaggregation/observations.parquet",
        f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet",
    )
    artifacts = []
    for number, logical_path in enumerate(logical_inputs):
        path = tmp_path / f"input-{number}.parquet"
        path.write_bytes(f"input-{number}".encode())
        artifacts.append(ReleaseArtifact(path, logical_path))
    index = tmp_path / "insights-index.json"
    index.write_text(json.dumps({"inputSignature": "stale"}))
    artifacts.append(ReleaseArtifact(index, "delivery/territory-insights/index.json"))

    with pytest.raises(ValueError, match="Territory insights input signature"):
        _validate_delivery_dependencies(
            artifacts, store=None, affected_families={"territory_insights"},
        )


def test_map_reference_year_must_have_matching_geometry(tmp_path: Path) -> None:
    index = tmp_path / "soil-index.json"
    values = tmp_path / "soil-map.json"
    geometry = tmp_path / "istat-region-2025.pmtiles"
    index.write_text(json.dumps({
        "geometry": ["delivery/soil/geometry/istat-region-2025.pmtiles"],
        "maps": ["delivery/soil/maps/example/2024-2024/region.json"],
    }))
    values.write_text(json.dumps({
        "territoryLevel": "region", "territoryReferenceDate": "2024-01-01",
    }))
    geometry.write_bytes(b"pmtiles")

    with pytest.raises(ValueError, match="map lacks compatible geometry"):
        _validate_delivery_dependencies([
            ReleaseArtifact(index, "delivery/soil/index.json"),
            ReleaseArtifact(values, "delivery/soil/maps/example/2024-2024/region.json"),
            ReleaseArtifact(geometry, "delivery/soil/geometry/istat-region-2025.pmtiles"),
        ], store=None, affected_families={"soil_delivery"})


def test_boundary_dependencies_are_reference_year_specific() -> None:
    current_delivery, current_geometry = _data_downstream_families({"boundaries"}, {2025})
    assert current_delivery == {"soil_delivery", "water_delivery"}
    assert current_geometry == {"soil_geometry_2025"}

    dissesto_delivery, dissesto_geometry = _data_downstream_families({"boundaries"}, {2024})
    assert dissesto_delivery == {"dissesto_delivery"}
    assert dissesto_geometry == {"dissesto_geometry_2024"}

    emissions_delivery, emissions_geometry = _data_downstream_families({"boundaries"}, {2019})
    assert emissions_delivery == {"emissions_delivery"}
    assert emissions_geometry == {"emissions_geometry_2019"}

    historical_delivery, historical_geometry = _data_downstream_families({"boundaries"}, {2022})
    assert historical_delivery == set()
    assert historical_geometry == set()


def test_forest_downstream_dependencies_distinguish_infc_and_copernicus() -> None:
    assert _geospatial_downstream_families({"infc"}) == {
        "infc", "forest_delivery", "forest_geometry_2015",
    }
    assert _geospatial_downstream_families({"copernicus"}) == {
        "copernicus", "forest_delivery", "forest_geometry_2023", "territory_insights",
    }


def test_raster_release_coherence_rejects_manifest_signature_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    catalog = root / "raw/copernicus-hrl-forests/catalog.json"
    manifest = root / "raw/copernicus-hrl-forests/tree-cover/2023/01/slice-manifest.json"
    zonal = root / f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"
    state_path = tmp_path / "source-state.json"
    catalog.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    zonal.parent.mkdir(parents=True)
    catalog.write_bytes(b"catalog")
    manifest.write_text(json.dumps({"source_signature": "2" * 64}))
    pd.DataFrame({"source_asset_sha256": ["1" * 64]}).to_parquet(zonal)
    state_path.write_text("{}")
    state = {"schemaVersion": 1, "sources": [
        _entry("copernicus-hrl-forests", "copernicus-hrl-forests/catalog.json", "3" * 64, kind="catalog"),
    ]}
    monkeypatch.setattr(cli, "_territory_paths", lambda _canonical: [])
    monkeypatch.setattr(cli, "_validate_data_canonical_provenance", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "_validate_delivery_dependencies", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("FOREST_PROCESSING_MODE", "raster")

    with pytest.raises(ValueError, match="raster provenance"):
        _validate_release_coherence(root, state, [
            ReleaseArtifact(catalog, "raw/copernicus-hrl-forests/catalog.json"),
            ReleaseArtifact(manifest, "raw/copernicus-hrl-forests/tree-cover/2023/01/slice-manifest.json"),
            ReleaseArtifact(zonal, f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"),
            ReleaseArtifact(state_path, "metadata/source-state.json"),
        ], scope="geospatial", affected_families={"copernicus", "forest_delivery", "territory_insights"})


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


def test_release_validation_failure_never_advances_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalObjectStore(tmp_path / "store")
    initial = tmp_path / "initial.parquet"
    candidate = tmp_path / "candidate.parquet"
    initial.write_bytes(b"initial")
    candidate.write_bytes(b"candidate")
    publish_release(store, "r1", [ReleaseArtifact(initial, "canonical/soil/initial.parquet")])
    before = store.read_json("manifest.json")
    monkeypatch.setattr(
        cli, "_validate_release_coherence",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("coherence failed")),
    )

    with pytest.raises(RuntimeError, match="coherence failed"):
        _publish_scoped(
            store=store, root=tmp_path, output=tmp_path / "output", release_id="r2", scope="all",
            previous_state={"schemaVersion": 1, "sources": []},
            current_state={"schemaVersion": 1, "sources": []},
            declared_paths=[candidate], changed=True,
        )

    assert store.read_json("manifest.json") == before


def test_affected_family_requires_current_source_state_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalObjectStore(tmp_path / "store")
    initial = tmp_path / "initial.parquet"
    initial.write_bytes(b"initial")
    publish_release(store, "r1", [ReleaseArtifact(initial, "canonical/soil/initial.parquet")])
    before = store.read_json("manifest.json")
    monkeypatch.setattr(cli, "_validate_release_coherence", lambda *_args, **_kwargs: None)

    with pytest.raises(ValueError, match="Affected source families lack current source-state"):
        _publish_scoped(
            store=store, root=tmp_path, output=tmp_path / "output", release_id="r2", scope="data",
            previous_state={"schemaVersion": 1, "sources": [
                _entry("ispra-soil-2025", "ispra-soil-2025/old.xlsx", "1" * 64),
            ]},
            current_state={"schemaVersion": 1, "sources": []},
            declared_paths=[], changed=True,
            affected_families={"soil", "soil_delivery", "territory_insights"},
        )

    assert store.read_json("manifest.json") == before


def test_geospatial_scope_reuses_active_infc_raw_and_owns_infc_ingest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalObjectStore(tmp_path / "store")
    hydrated: list[str] = []
    previous = {"schemaVersion": 1, "sources": [
        _entry("infc-2015-forests", "infc-2015-forests/volume.zip", "a" * 64),
    ]}
    monkeypatch.setattr(cli, "_hydrate", lambda _store, _root, paths: hydrated.extend(paths))

    def fetch(_root: Path, **kwargs: object) -> dict:
        assert kwargs["include_infc"] is True
        return {"infc": [], "catalog": {"status": "offline"}, "raw_retention": "selective"}

    monkeypatch.setattr(cli, "fetch_forests", fetch)
    monkeypatch.setattr(
        cli, "ingest_infc_forests",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("INFC ingest reached")),
    )

    with pytest.raises(RuntimeError, match="INFC ingest reached"):
        _run_geospatial(
            Namespace(offline=False, force=False, report=str(tmp_path / "report.json")),
            root=tmp_path / "data", output=tmp_path / "output", canonical=tmp_path / "data/canonical",
            delivery=tmp_path / "data/delivery", store=store, previous_state=previous, release_id="r2",
            started=0.0, started_at="2026-08-30T00:00:00Z",
        )

    assert "raw/infc-2015-forests/volume.zip" in hydrated
    assert "raw/infc-2015-forests/volume.zip.metadata.json" in hydrated


def _forest_plan(tmp_path: Path, *, infc_status: str, catalog_status: str) -> None:
    plan = {
        "schemaVersion": 1, "activeReleaseId": "r1", "scope": "geospatial",
        "sourceChecks": 2, "sourcesChanged": int(infc_status == "changed") + int(catalog_status == "changed"),
        "sourcesUnchanged": int(infc_status == "unchanged") + int(catalog_status == "unchanged"),
        "sourcesUnverifiable": 0, "changed": "changed" in {infc_status, catalog_status},
        "sources": [{
            "source_id": "infc-2015-forests", "asset_path": "infc-2015-forests/volume.zip",
            "status": infc_status, "baseline_sha256": "a" * 64, "baseline_bytes": 1,
        }],
        "catalog": {"status": catalog_status},
    }
    path = tmp_path / "forest-plan.json"
    path.write_text(json.dumps(plan))
    load_ingestion_plan(
        path, scope="geospatial", active_release_id="r1", raw_root=tmp_path / "data/raw",
    )


def _scoped_plan(
    tmp_path: Path, *, scope: str, sources: list[dict], catalog: dict | None = None,
) -> None:
    payload = {
        "schemaVersion": 1, "activeReleaseId": "r1", "scope": scope,
        "sourceChecks": len(sources),
        "sourcesChanged": sum(item["status"] == "changed" for item in sources),
        "sourcesUnchanged": sum(item["status"] == "unchanged" for item in sources),
        "sourcesUnverifiable": sum(item["status"] == "unverifiable" for item in sources),
        "changed": any(item["status"] == "changed" for item in sources),
        "sources": sources,
    }
    if catalog is not None:
        payload["catalog"] = catalog
        payload["changed"] = payload["changed"] or catalog.get("status") == "changed"
    path = tmp_path / f"{scope}-selective-plan.json"
    path.write_text(json.dumps(payload))
    load_ingestion_plan(
        path, scope=scope, active_release_id="r1", raw_root=tmp_path / "data/raw",
    )


def _planned_entry(source_id: str, asset_path: str, status: str) -> dict:
    return {
        "source_id": source_id, "asset_path": asset_path, "status": status,
        "baseline_sha256": "a" * 64, "baseline_bytes": 8,
    }


@pytest.mark.parametrize(("year", "offline"), ((2015, False), (2023, True)))
def test_scoped_data_rejects_forest_boundary_change_before_any_work_or_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, year: int, offline: bool,
) -> None:
    root = tmp_path / "data"
    output = tmp_path / "artifacts"
    store = LocalObjectStore(output / "object-store")
    initial = tmp_path / "initial.json"
    initial.write_text("{}")
    publish_release(store, "r1", [ReleaseArtifact(initial, "delivery/soil/index.json")])
    manifest_path = store.root / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    asset_path = f"istat-administrative-boundaries/{year}/limiti-{year}-generalized.zip"
    _scoped_plan(tmp_path, scope="data", sources=[
        _planned_entry("istat-administrative-boundaries", asset_path, "changed"),
    ])
    monkeypatch.setattr(
        cli, "_hydrate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("guard hydrated artifacts")),
    )
    monkeypatch.setattr(
        cli, "ingest_boundaries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("guard processed boundaries")),
    )
    try:
        with pytest.raises(RuntimeError, match=rf"reference year {year} changed.*scope=all"):
            cli._run_incremental_data(
                Namespace(force=False, offline=offline, report=str(tmp_path / "report.json")),
                root=root, output=output, canonical=root / "canonical", derived=root / "derived",
                delivery=root / "delivery", store=store,
                previous_state={"schemaVersion": 1, "sources": [
                    _entry("istat-administrative-boundaries", asset_path, "a" * 64),
                ]},
                release_id="r2", started=0.0, started_at="2026-09-02T00:00:00Z",
            )
    finally:
        clear_ingestion_plan()

    assert manifest_path.read_bytes() == manifest_before


def test_publish_boundary_guard_also_applies_without_incremental_family_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalObjectStore(tmp_path / "store")
    initial = tmp_path / "initial.json"
    initial.write_text("{}")
    publish_release(store, "r1", [ReleaseArtifact(initial, "delivery/soil/index.json")])
    manifest_path = store.root / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    asset_path = "istat-administrative-boundaries/2015/limiti-2015-generalized.zip"
    previous = {"schemaVersion": 1, "sources": [
        _entry("istat-administrative-boundaries", asset_path, "a" * 64),
    ]}
    current = {"schemaVersion": 1, "sources": [
        _entry("istat-administrative-boundaries", asset_path, "b" * 64),
    ]}
    monkeypatch.setattr(cli, "_validate_release_coherence", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="reference year 2015 changed.*scope=all"):
        _publish_scoped(
            store=store, root=tmp_path, output=tmp_path / "output", release_id="r2", scope="data",
            previous_state=previous, current_state=current, declared_paths=[], changed=True,
        )

    assert manifest_path.read_bytes() == manifest_before


def test_publish_boundary_rejects_cross_scope_state_delta_even_if_runner_guard_is_bypassed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalObjectStore(tmp_path / "store")
    initial = tmp_path / "initial.json"
    initial.write_text("{}")
    publish_release(store, "r1", [ReleaseArtifact(initial, "delivery/soil/index.json")])
    manifest_path = store.root / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    asset_path = "istat-administrative-boundaries/2023/limiti-2023-generalized.zip"
    previous = {"schemaVersion": 1, "sources": [
        _entry("istat-administrative-boundaries", asset_path, "a" * 64),
    ]}
    current = {"schemaVersion": 1, "sources": [
        _entry("istat-administrative-boundaries", asset_path, "b" * 64),
    ]}
    monkeypatch.setattr(cli, "_validate_release_coherence", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="reference year 2023 changed.*scope=all"):
        _publish_scoped(
            store=store, root=tmp_path, output=tmp_path / "output", release_id="r2", scope="data",
            previous_state=previous, current_state=current, declared_paths=[], changed=True,
            affected_families={"boundaries"},
        )

    assert manifest_path.read_bytes() == manifest_before


def test_scope_all_accepts_cross_scope_boundary_delta_without_carrying_obsolete_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    output = tmp_path / "output"
    store = LocalObjectStore(tmp_path / "store")
    old = tmp_path / "old.zip"
    old.write_bytes(b"old")
    publish_release(store, "r1", [
        ReleaseArtifact(old, "raw/istat-administrative-boundaries/2023/obsolete.zip"),
    ])
    current_raw = root / "raw/istat-administrative-boundaries/2023/limiti-2023-generalized.zip"
    current_raw.parent.mkdir(parents=True)
    current_raw.write_bytes(b"new")
    current = {"schemaVersion": 1, "sources": [
        _entry(
            "istat-administrative-boundaries",
            "istat-administrative-boundaries/2023/limiti-2023-generalized.zip",
            "b" * 64,
        ),
    ]}
    monkeypatch.setattr(cli, "_validate_release_coherence", lambda *_args, **_kwargs: None)

    manifest, _metrics, publication = _publish_scoped(
        store=store, root=root, output=output, release_id="r2", scope="all",
        previous_state={"schemaVersion": 1, "sources": [
            _entry("istat-administrative-boundaries", "istat-administrative-boundaries/2023/obsolete.zip", "a" * 64),
        ]},
        current_state=current, declared_paths=[current_raw], changed=True,
    )

    release = store.read_json(manifest["releaseKey"])
    logical_paths = {item["logicalPath"] for item in release["objects"]}
    assert publication["carried"] == 0
    assert "raw/istat-administrative-boundaries/2023/obsolete.zip" not in logical_paths
    assert "raw/istat-administrative-boundaries/2023/limiti-2023-generalized.zip" in logical_paths


def test_changed_data_family_hydrates_only_its_unchanged_raw_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [
        _planned_entry("ispra-emissions-ghg-2026", "ispra-emissions-ghg-2026/ghg.xlsx", "changed"),
        _planned_entry("ispra-emissions-nfr-2026", "ispra-emissions-nfr-2026/nfr.xlsx", "unchanged"),
        _planned_entry("ispra-bigbang-10", "ispra-bigbang-10/water.nc", "unchanged"),
    ]
    _scoped_plan(tmp_path, scope="data", sources=sources)
    hydrated: list[str] = []
    monkeypatch.setattr(cli, "_hydrate", lambda _store, _root, paths: hydrated.extend(paths))
    try:
        cli._hydrate_planned_raw_dependencies(object(), tmp_path / "data", {"emissions"})
    finally:
        clear_ingestion_plan()

    assert hydrated == [
        "raw/ispra-emissions-nfr-2026/nfr.xlsx",
        "raw/ispra-emissions-nfr-2026/nfr.xlsx.metadata.json",
    ]
    assert not any("bigbang" in path or "delivery/" in path for path in hydrated)


def test_infc_only_run_hydrates_only_infc_raw_and_copernicus_zonal_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [
        _planned_entry("infc-2015-forests", "infc-2015-forests/volume.zip", "changed"),
        _planned_entry("infc-2015-forests", "infc-2015-forests/biomass.zip", "unchanged"),
        _planned_entry(
            "copernicus-hrl-forests",
            "copernicus-hrl-forests/tree-cover-density/2021-2021/01/tile-r0-c0.tif",
            "unchanged",
        ),
    ]
    _scoped_plan(tmp_path, scope="geospatial", sources=sources, catalog={"status": "unchanged"})
    hydrated: list[str] = []
    monkeypatch.setattr(cli, "_hydrate", lambda _store, _root, paths: hydrated.extend(paths))
    monkeypatch.setattr(
        cli, "_process_geospatial_forest_sources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("hydration inspected")),
    )
    try:
        with pytest.raises(RuntimeError, match="hydration inspected"):
            _run_geospatial(
                Namespace(offline=False, force=False, report=str(tmp_path / "report.json")),
                root=tmp_path / "data", output=tmp_path / "output", canonical=tmp_path / "data/canonical",
                delivery=tmp_path / "data/delivery", store=object(), previous_state=None, release_id="r2",
                started=0.0, started_at="2026-09-02T00:00:00Z",
            )
    finally:
        clear_ingestion_plan()

    assert "raw/infc-2015-forests/biomass.zip" in hydrated
    assert "raw/infc-2015-forests/biomass.zip.metadata.json" in hydrated
    assert f"canonical/forests/algorithm_version={cli.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet" in hydrated
    assert not any(path.startswith("raw/copernicus-") for path in hydrated)
    assert not any(path.startswith("canonical/soil/") for path in hydrated)


def test_copernicus_only_run_does_not_hydrate_process_slices_and_reuses_infc_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = "raw/copernicus-hrl-forests/tree-cover-density/2021-2021/01/tile-r0-c0.tif"
    obsolete = "raw/copernicus-hrl-forests/tree-cover-density/2018-2018/01/obsolete.tif"
    sources = [
        _planned_entry("infc-2015-forests", "infc-2015-forests/volume.zip", "unchanged"),
        _planned_entry("copernicus-hrl-forests", current.removeprefix("raw/"), "unchanged"),
        _planned_entry("copernicus-hrl-forests", obsolete.removeprefix("raw/"), "unchanged"),
    ]
    _scoped_plan(tmp_path, scope="geospatial", sources=sources, catalog={"status": "changed"})
    hydrated: list[str] = []
    monkeypatch.setattr(cli, "_hydrate", lambda _store, _root, paths: hydrated.extend(paths))
    monkeypatch.setattr(
        cli, "_process_geospatial_forest_sources",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("hydration inspected")),
    )
    try:
        with pytest.raises(RuntimeError, match="hydration inspected"):
            _run_geospatial(
                Namespace(offline=False, force=False, report=str(tmp_path / "report.json")),
                root=tmp_path / "data", output=tmp_path / "output", canonical=tmp_path / "data/canonical",
                delivery=tmp_path / "data/delivery", store=object(), previous_state=None, release_id="r2",
                started=0.0, started_at="2026-09-02T00:00:00Z",
            )
    finally:
        clear_ingestion_plan()

    assert "canonical/forests/dataset_version=infc2015-published-tables/observations.parquet" in hydrated
    assert current not in hydrated
    assert f"{current}.metadata.json" not in hydrated
    assert obsolete not in hydrated
    assert f"{obsolete}.metadata.json" not in hydrated
    assert not any(path.startswith("raw/infc-") for path in hydrated)


def test_planned_noop_does_not_hydrate_or_advance_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    output = tmp_path / "artifacts"
    store = LocalObjectStore(output / "object-store")
    state = tmp_path / "source-state.json"
    state.write_text(json.dumps({"schemaVersion": 1, "sources": []}))
    publish_release(store, "r1", [ReleaseArtifact(state, "metadata/source-state.json")])
    plan = tmp_path / "noop-plan.json"
    plan.write_text(json.dumps({
        "schemaVersion": 1, "activeReleaseId": "r1", "scope": "data",
        "sourceChecks": 1, "sourcesChanged": 0, "sourcesUnchanged": 1,
        "sourcesUnverifiable": 0, "changed": False,
        "sources": [_planned_entry("ispra-soil-2025", "ispra-soil-2025/soil.xlsx", "unchanged")],
    }))
    before = store.read_json("manifest.json")
    monkeypatch.setattr(
        cli, "_hydrate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no-op hydrated artifacts")),
    )
    monkeypatch.setattr(
        cli, "_run_incremental_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no-op entered ingestion")),
    )
    try:
        result = cli.run(Namespace(
            workdir=str(root), output=str(output), release_id="r2", publish="local", scope="data",
            plan=str(plan), force=False, offline=False, report=str(tmp_path / "noop-report.json"),
        ))
    finally:
        clear_ingestion_plan()

    assert result == 0
    assert store.read_json("manifest.json") == before
    report = json.loads((tmp_path / "noop-report.json").read_text())
    assert report["status"] == "noop"
    assert report["operationalMetrics"]["bytesUploadedToR2"] == 0


def test_infc_only_change_does_not_acquire_or_ingest_copernicus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forest_plan(tmp_path, infc_status="changed", catalog_status="unchanged")
    calls: list[tuple[str, bool]] = []

    def fetch(_root: Path, **kwargs: object) -> dict:
        calls.append(("fetch", bool(kwargs["check_geospatial"])))
        assert kwargs["include_infc"] is True
        return {"infc": [], "catalog": {"status": "deferred"}}

    monkeypatch.setattr(cli, "fetch_forests", fetch)
    monkeypatch.setattr(cli, "ingest_infc_forests", lambda *_args, **kwargs: calls.append(("infc", bool(kwargs["force"]))) or {"changed": True})
    monkeypatch.setattr(cli, "ingest_forests", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Copernicus ingested")))
    monkeypatch.setattr(cli, "_reused_canonical", lambda *_args, **_kwargs: {"changed": False, "mode": "active_release"})
    try:
        _fetch, infc, zonal = _process_geospatial_forest_sources(
            Namespace(offline=False, force=False), root=tmp_path / "data",
            canonical=tmp_path / "data/canonical", previous_state=None,
        )
    finally:
        clear_ingestion_plan()

    assert calls == [("fetch", False), ("infc", True)]
    assert infc["changed"] is True
    assert zonal == {"changed": False, "mode": "active_release"}


def test_copernicus_only_change_does_not_acquire_or_ingest_infc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forest_plan(tmp_path, infc_status="unchanged", catalog_status="changed")
    calls: list[tuple[str, bool]] = []

    def fetch(_root: Path, **kwargs: object) -> dict:
        calls.append(("fetch", bool(kwargs["check_geospatial"])))
        assert kwargs["include_infc"] is False
        return {"infc": [], "catalog": {"status": "checked", "signature": "b" * 64}}

    previous = {"schemaVersion": 1, "sources": [
        _entry("copernicus-hrl-forests", "copernicus-hrl-forests/catalog.json", "a" * 64, kind="catalog"),
    ]}
    monkeypatch.setattr(cli, "fetch_forests", fetch)
    monkeypatch.setattr(cli, "ingest_infc_forests", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("INFC ingested")))
    monkeypatch.setattr(cli, "ingest_forests", lambda *_args, **kwargs: calls.append(("copernicus", bool(kwargs["force"]))) or {"changed": True})
    monkeypatch.setattr(cli, "_reused_canonical", lambda *_args, **_kwargs: {"changed": False, "mode": "active_release"})
    try:
        _fetch, infc, zonal = _process_geospatial_forest_sources(
            Namespace(offline=False, force=False), root=tmp_path / "data",
            canonical=tmp_path / "data/canonical", previous_state=previous,
        )
    finally:
        clear_ingestion_plan()

    assert calls == [("fetch", True), ("copernicus", True)]
    assert infc == {"changed": False, "mode": "active_release"}
    assert zonal["changed"] is True


def test_offline_copernicus_change_fails_before_using_stale_process_slices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forest_plan(tmp_path, infc_status="unchanged", catalog_status="changed")
    monkeypatch.setattr(
        cli, "fetch_forests",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("offline contacted upstream")),
    )
    try:
        with pytest.raises(RuntimeError, match="cannot acquire changed Copernicus"):
            _process_geospatial_forest_sources(
                Namespace(offline=True, force=False), root=tmp_path / "data",
                canonical=tmp_path / "data/canonical", previous_state=None,
            )
    finally:
        clear_ingestion_plan()


def test_geospatial_noop_contacts_neither_forest_source_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forest_plan(tmp_path, infc_status="unchanged", catalog_status="unchanged")

    def fetch(_root: Path, **kwargs: object) -> dict:
        assert kwargs["include_infc"] is False
        assert kwargs["check_geospatial"] is False
        return {"infc": [], "catalog": {"status": "deferred"}}

    monkeypatch.setattr(cli, "fetch_forests", fetch)
    monkeypatch.setattr(cli, "ingest_infc_forests", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("INFC ingested")))
    monkeypatch.setattr(cli, "ingest_forests", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Copernicus ingested")))
    monkeypatch.setattr(cli, "_reused_canonical", lambda *_args, **_kwargs: {"changed": False, "mode": "active_release"})
    try:
        _fetch, infc, zonal = _process_geospatial_forest_sources(
            Namespace(offline=False, force=False), root=tmp_path / "data",
            canonical=tmp_path / "data/canonical", previous_state=None,
        )
    finally:
        clear_ingestion_plan()

    assert infc["changed"] is False
    assert zonal["changed"] is False
