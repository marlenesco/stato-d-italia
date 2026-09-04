from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import stato_italia.cli as cli
from stato_italia.bigbang_historical_processing import HISTORICAL_DERIVED_LOGICAL_PATH
from stato_italia.bigbang_raster_poc import METRIC_SPECS
from stato_italia.release import LocalObjectStore, ReleaseArtifact, active_release, carry_forward_active_artifacts, publish_release
from stato_italia.ingestion_plan import clear_ingestion_plan, load_ingestion_plan
from stato_italia.source_state import changed_source_entries, source_family, source_state_changed
from stato_italia.water import bigbang_raw_assets


def _state_entry(asset_path: str, checksum: str) -> dict:
    return {
        "source_id": "ispra-bigbang-10",
        "asset_path": asset_path,
        "resolved_url": "https://official.example/" + Path(asset_path).name,
        "etag": None,
        "last_modified": None,
        "sha256": checksum,
        "bytes": 1,
        "dataset_version": "bigbang-10-1951-2025",
        "period": "annual",
        "checked_at": "2026-09-04T00:00:00Z",
    }


def test_bigbang_source_state_bootstrap_adds_only_missing_registered_assets() -> None:
    names = list(bigbang_raw_assets())
    assert set(names) == {
        "AE_ANNUAL_1951-2025.zip", "BIGBANG100_TABLES_ITALY_01.xlsx",
        "BIGBANG100_TABLES_REGIONS_02.xlsx", "GRID_UNITS.txt", "GR_ANNUAL_1951-2025.zip",
        "IF_ANNUAL_1951-2025.zip", "RF_ANNUAL_1951-2025.zip", "TP_ANNUAL_1951-2025.zip",
    }
    persisted = {"schemaVersion": 1, "sources": [
        _state_entry(f"ispra-bigbang-10/{name}", f"{index:x}" * 64)
        for index, name in enumerate(names[:2], start=1)
    ]}
    missing = cli._missing_bigbang_source_plan_entries(persisted)

    assert [entry["asset_path"] for entry in missing] == [
        f"ispra-bigbang-10/{name}" for name in names[2:]
    ]
    assert {entry["status"] for entry in missing} == {"changed"}
    complete = {"schemaVersion": 1, "sources": [
        _state_entry(f"ispra-bigbang-10/{name}", "a" * 64) for name in names
    ]}
    assert cli._missing_bigbang_source_plan_entries(complete) == []
    checked_only = {**complete, "sources": [{**entry, "checked_at": "later"} for entry in complete["sources"]]}
    assert source_state_changed(complete, checked_only) is False
    changed_raster = {**complete, "sources": [
        {**entry, "sha256": "b" * 64} if entry["asset_path"].endswith("TP_ANNUAL_1951-2025.zip") else entry
        for entry in complete["sources"]
    ]}
    changed_grid = {**complete, "sources": [
        {**entry, "sha256": "c" * 64} if entry["asset_path"].endswith("GRID_UNITS.txt") else entry
        for entry in complete["sources"]
    ]}
    for candidate in (changed_raster, changed_grid):
        assert source_state_changed(complete, candidate) is True
        assert {source_family(entry["source_id"]) for entry in changed_source_entries(complete, candidate)} == {"water"}


def test_historical_rebuild_dependency_is_water_or_boundaries_only() -> None:
    assert cli._historical_water_affected({"water"}) is True
    assert cli._historical_water_affected({"boundaries"}) is True
    assert cli._historical_water_affected({"soil"}) is False
    assert cli._historical_water_affected({"dissesto", "emissions"}) is False


def test_boundary_rebuild_hydrates_all_unchanged_bigbang_raw_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "data" / "raw"
    plan = {
        "schemaVersion": 1,
        "scope": "data",
        "activeReleaseId": "r1",
        "sources": [
            {
                "source_id": "ispra-bigbang-10",
                "asset_path": f"ispra-bigbang-10/{name}",
                "status": "unchanged",
                "baseline_sha256": "a" * 64,
                "baseline_bytes": 1,
            }
            for name in bigbang_raw_assets()
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan))
    load_ingestion_plan(plan_path, scope="data", active_release_id="r1", raw_root=raw_root)
    hydrated: list[str] = []
    monkeypatch.setattr(cli, "_hydrate", lambda _store, _root, paths: hydrated.extend(paths))
    try:
        cli._hydrate_planned_raw_dependencies(object(), tmp_path / "data", {"boundaries", "water"})
    finally:
        clear_ingestion_plan()
    expected = {
        f"raw/ispra-bigbang-10/{name}{suffix}"
        for name in bigbang_raw_assets() for suffix in ("", ".metadata.json")
    }
    assert set(hydrated) == expected


def _write_historical_derived(root: Path, hashes: list[str]) -> Path:
    path = root / HISTORICAL_DERIVED_LOGICAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    specs = list(METRIC_SPECS.values())
    if len(hashes) != len(specs):
        raise ValueError("Synthetic historical artifact must cover every BIGBANG metric")
    pd.DataFrame([{
        "derived_observation_id": f"derived-{index}",
        "derived_metric_id": spec.derived_metric_id,
        "reference_year": 2006,
        "territory_id": f"it:province:{index:03d}",
        "territory_version_id": f"it:province:{index:03d}@2006-01-01",
        "territory_level": "province",
        "source_asset_sha256": checksum,
        "source_raster_sha256": f"raster-{index}",
        "source_raster_locator": f"archive-{index}.zip!tp_2006_yyc.asc",
        "source_dataset_id": "ispra-bigbang-10",
        "source_dataset_version": "bigbang-10-1951-2025",
        "unit_ucum": spec.unit_ucum,
        "territory_geometry_reference": "canonical/territories/reference_year=2006/province.parquet#test",
        "territory_geometry_sha256": f"geometry-{index}",
        "algorithm_version": "bigbang-tp-zonal-area-weighted-v1",
        "coverage_ratio": 1.0,
        "valid_intersection_area_m2": 1.0,
        "intersecting_cell_count": 1,
        "valid_cell_count": 1,
        "quality_flags": [],
        "official_status": "derived_by_stato_italia",
    } for index, (checksum, spec) in enumerate(zip(hashes, specs, strict=True), start=1)]).to_parquet(path, index=False)
    return path


def test_historical_release_provenance_requires_all_release_raster_archives(tmp_path: Path) -> None:
    hashes = [f"{index:x}" * 64 for index in range(1, 6)]
    _write_historical_derived(tmp_path, hashes)
    state = {"schemaVersion": 1, "sources": [
        _state_entry(f"ispra-bigbang-10/archive-{index}.zip", checksum)
        for index, checksum in enumerate(hashes, start=1)
    ]}
    cli._validate_bigbang_historical_provenance(
        tmp_path,
        state,
        {
            HISTORICAL_DERIVED_LOGICAL_PATH,
            "canonical/territories/reference_year=2006/province.parquet",
        },
        {"water_historical"},
    )
    state["sources"][0]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="provenance does not match"):
        cli._validate_bigbang_historical_provenance(
            tmp_path,
            state,
            {
                HISTORICAL_DERIVED_LOGICAL_PATH,
                "canonical/territories/reference_year=2006/province.parquet",
            },
            {"water_historical"},
        )


def test_local_release_bootstrap_noop_and_unrelated_carry_forward(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    phase_a = tmp_path / "phase-a.parquet"
    phase_a.write_bytes(b"phase-a")
    publish_release(store, "phase-a", [ReleaseArtifact(phase_a, "canonical/soil/observations.parquet")])

    hashes = [f"{index:x}" * 64 for index in range(1, 6)]
    historical = _write_historical_derived(tmp_path, hashes)
    rasters = []
    for index in range(1, 6):
        raw = tmp_path / f"archive-{index}.zip"
        raw.write_bytes(f"archive-{index}".encode())
        rasters.append(ReleaseArtifact(raw, f"raw/ispra-bigbang-10/archive-{index}.zip"))
    bootstrap = publish_release(store, "bigbang-bootstrap", [
        ReleaseArtifact(phase_a, "canonical/soil/observations.parquet"),
        ReleaseArtifact(historical, HISTORICAL_DERIVED_LOGICAL_PATH),
        *rasters,
    ])
    active = active_release(store)
    assert bootstrap["releaseId"] == "bigbang-bootstrap"
    assert HISTORICAL_DERIVED_LOGICAL_PATH in {item["logicalPath"] for item in active["objects"]}
    manifest_before = store.read_json("manifest.json")
    # A true no-op invokes no publication and leaves the sole mutable pointer intact.
    assert source_state_changed({"schemaVersion": 1, "sources": []}, {"schemaVersion": 1, "sources": []}) is False
    assert store.read_json("manifest.json") == manifest_before

    updated_soil = tmp_path / "updated-soil.parquet"
    updated_soil.write_bytes(b"updated-soil")
    carried = carry_forward_active_artifacts(
        store,
        {"canonical/soil/observations.parquet"},
        scope="data",
        affected_families={"soil"},
    )
    historical_before = next(item for item in active["objects"] if item["logicalPath"] == HISTORICAL_DERIVED_LOGICAL_PATH)
    publish_release(store, "soil-only", [ReleaseArtifact(updated_soil, "canonical/soil/observations.parquet"), *carried])
    historical_after = next(
        item for item in active_release(store)["objects"] if item["logicalPath"] == HISTORICAL_DERIVED_LOGICAL_PATH
    )
    assert historical_after["key"] == historical_before["key"]
    assert historical_after["sha256"] == historical_before["sha256"]
    assert historical_after["bytes"] == historical_before["bytes"]


def test_water_raster_change_replaces_historical_artifact_but_reuses_official_canonical(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    official = tmp_path / "official.parquet"
    official.write_bytes(b"official-bigbang")
    first_historical = _write_historical_derived(tmp_path, [f"{index:x}" * 64 for index in range(1, 6)])
    publish_release(store, "r1", [
        ReleaseArtifact(official, "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet"),
        ReleaseArtifact(first_historical, HISTORICAL_DERIVED_LOGICAL_PATH),
    ])
    before = active_release(store)
    first_historical_object = next(item for item in before["objects"] if item["logicalPath"] == HISTORICAL_DERIVED_LOGICAL_PATH)
    first_official_object = next(item for item in before["objects"] if item["logicalPath"].startswith("canonical/water/"))

    second_historical = _write_historical_derived(tmp_path / "second", [f"{index:x}" * 64 for index in range(6, 11)])
    carried = carry_forward_active_artifacts(
        store, {"canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet", HISTORICAL_DERIVED_LOGICAL_PATH},
        scope="data", affected_families={"water", "water_historical"},
    )
    publish_release(store, "r2", [
        ReleaseArtifact(official, "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet"),
        ReleaseArtifact(second_historical, HISTORICAL_DERIVED_LOGICAL_PATH),
        *carried,
    ])
    after = active_release(store)
    second_historical_object = next(item for item in after["objects"] if item["logicalPath"] == HISTORICAL_DERIVED_LOGICAL_PATH)
    second_official_object = next(item for item in after["objects"] if item["logicalPath"].startswith("canonical/water/"))
    assert second_historical_object["key"] != first_historical_object["key"]
    assert second_official_object["key"] == first_official_object["key"]


def test_duplicate_historical_logical_path_fails_before_manifest_update(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    initial = tmp_path / "initial.parquet"
    initial.write_bytes(b"initial")
    publish_release(store, "r1", [ReleaseArtifact(initial, "canonical/soil/observations.parquet")])
    before = store.read_json("manifest.json")
    derived = _write_historical_derived(tmp_path, ["a" * 64] * 5)
    with pytest.raises(ValueError, match="duplicate logical paths"):
        publish_release(store, "r2", [
            ReleaseArtifact(derived, HISTORICAL_DERIVED_LOGICAL_PATH),
            ReleaseArtifact(derived, HISTORICAL_DERIVED_LOGICAL_PATH),
        ])
    assert store.read_json("manifest.json") == before
