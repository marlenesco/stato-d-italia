from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import stato_italia.cli as cli
from stato_italia.bigbang_historical_processing import HISTORICAL_DERIVED_LOGICAL_PATH
from stato_italia.bigbang_historical_processing import build_bigbang_historical_processing_plan
from stato_italia.bigbang_historical_territory_policy import TerritoryGeometryVersion
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


def _bigbang_state() -> tuple[dict, dict[str, str]]:
    checksums = {
        "BIGBANG100_TABLES_ITALY_01.xlsx": "1" * 64,
        "BIGBANG100_TABLES_REGIONS_02.xlsx": "2" * 64,
        "GRID_UNITS.txt": "3" * 64,
        "TP_ANNUAL_1951-2025.zip": "4" * 64,
        "AE_ANNUAL_1951-2025.zip": "5" * 64,
        "IF_ANNUAL_1951-2025.zip": "6" * 64,
        "GR_ANNUAL_1951-2025.zip": "7" * 64,
        "RF_ANNUAL_1951-2025.zip": "8" * 64,
    }
    return {
        "schemaVersion": 1,
        "sources": [
            _state_entry(f"ispra-bigbang-10/{name}", checksum)
            for name, checksum in checksums.items()
        ],
    }, checksums


def _write_canonical_water(root: Path, hashes: list[str]) -> Path:
    path = root / "canonical/water/dataset_version=bigbang-10-1951-2025/observations.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"source_asset_sha256": hashes}).to_parquet(path, index=False)
    return path


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


def test_historical_rebuild_policy_covers_full_scope_all_and_legacy_bootstrap() -> None:
    assert cli.should_build_historical_water(
        scope="data", incremental=True, affected_source_families={"soil"}, active_release_has_historical=True,
    ) is False
    assert cli.should_build_historical_water(
        scope="data", incremental=True, affected_source_families={"water"}, active_release_has_historical=True,
    ) is True
    assert cli.should_build_historical_water(
        scope="data", incremental=True, affected_source_families={"boundaries"}, active_release_has_historical=True,
    ) is True
    assert cli.should_build_historical_water(
        scope="data", incremental=False, affected_source_families=set(), active_release_has_historical=True,
    ) is True
    assert cli.should_build_historical_water(
        scope="all", incremental=False, affected_source_families=set(), active_release_has_historical=True,
    ) is True
    assert cli.should_build_historical_water(
        scope="data", incremental=True, affected_source_families={"soil"}, active_release_has_historical=False,
    ) is True


def test_canonical_water_provenance_accepts_only_the_two_workbooks(tmp_path: Path) -> None:
    state, hashes = _bigbang_state()
    canonical = _write_canonical_water(tmp_path, [
        hashes["BIGBANG100_TABLES_ITALY_01.xlsx"], hashes["BIGBANG100_TABLES_REGIONS_02.xlsx"],
    ])
    cli._validate_data_canonical_provenance(
        tmp_path, state, {str(canonical.relative_to(tmp_path))}, {"water"},
    )


def test_canonical_water_provenance_rejects_raster_and_missing_workbook(tmp_path: Path) -> None:
    state, hashes = _bigbang_state()
    canonical = _write_canonical_water(tmp_path, [
        hashes["BIGBANG100_TABLES_ITALY_01.xlsx"], hashes["TP_ANNUAL_1951-2025.zip"],
    ])
    logical_path = str(canonical.relative_to(tmp_path))
    with pytest.raises(ValueError, match="canonical provenance differ"):
        cli._validate_data_canonical_provenance(tmp_path, state, {logical_path}, {"water"})

    canonical = _write_canonical_water(tmp_path, [
        hashes["BIGBANG100_TABLES_ITALY_01.xlsx"], hashes["BIGBANG100_TABLES_REGIONS_02.xlsx"],
    ])
    state["sources"] = [
        entry for entry in state["sources"]
        if not entry["asset_path"].endswith("BIGBANG100_TABLES_REGIONS_02.xlsx")
    ]
    with pytest.raises(ValueError, match="lacks canonical provenance asset"):
        cli._validate_data_canonical_provenance(tmp_path, state, {logical_path}, {"water"})


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


def test_release_coherence_keeps_official_workbook_and_derived_raster_provenance_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    state, hashes = _bigbang_state()
    raw_artifacts = []
    for entry in state["sources"]:
        raw = root / "raw" / entry["asset_path"]
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"official")
        sidecar = Path(f"{raw}.metadata.json")
        sidecar.write_text("{}")
        raw_artifacts.extend((
            ReleaseArtifact(raw, str(raw.relative_to(root))),
            ReleaseArtifact(sidecar, str(sidecar.relative_to(root))),
        ))
    canonical = _write_canonical_water(root, [
        hashes["BIGBANG100_TABLES_ITALY_01.xlsx"], hashes["BIGBANG100_TABLES_REGIONS_02.xlsx"],
    ])
    historical = _write_historical_derived(root, [
        hashes[name] for name in (
            "TP_ANNUAL_1951-2025.zip", "AE_ANNUAL_1951-2025.zip", "IF_ANNUAL_1951-2025.zip",
            "GR_ANNUAL_1951-2025.zip", "RF_ANNUAL_1951-2025.zip",
        )
    ])
    territory = root / "canonical/territories/reference_year=2006/province.parquet"
    territory.parent.mkdir(parents=True, exist_ok=True)
    territory.write_bytes(b"territory")
    state_path = root / "metadata/source-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{}")
    monkeypatch.setattr(cli, "_territory_paths", lambda _canonical: [territory])
    monkeypatch.setattr(cli, "_validate_delivery_dependencies", lambda *_args, **_kwargs: None)

    cli._validate_release_coherence(
        root, state, [
            *raw_artifacts,
            ReleaseArtifact(canonical, str(canonical.relative_to(root))),
            ReleaseArtifact(historical, HISTORICAL_DERIVED_LOGICAL_PATH),
            ReleaseArtifact(territory, str(territory.relative_to(root))),
            ReleaseArtifact(state_path, "metadata/source-state.json"),
        ],
        scope="data", affected_families={"water", "water_historical"},
    )


def test_full_release_missing_historical_fails_before_publish(tmp_path: Path) -> None:
    state, _hashes = _bigbang_state()
    with pytest.raises(ValueError, match="lacks BIGBANG historical"):
        cli._validate_bigbang_historical_provenance(tmp_path, state, set(), None)


def test_scope_all_rebuild_requires_a_fresh_historical_artifact(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "store")
    first = _write_historical_derived(tmp_path / "first", [f"{index:x}" * 64 for index in range(1, 6)])
    publish_release(store, "r1", [ReleaseArtifact(first, HISTORICAL_DERIVED_LOGICAL_PATH)])
    first_key = next(item for item in active_release(store)["objects"] if item["logicalPath"] == HISTORICAL_DERIVED_LOGICAL_PATH)["key"]
    assert carry_forward_active_artifacts(store, set(), scope="all") == []

    second = _write_historical_derived(tmp_path / "second", [f"{index:x}" * 64 for index in range(6, 11)])
    publish_release(store, "r2", [ReleaseArtifact(second, HISTORICAL_DERIVED_LOGICAL_PATH)])
    release = active_release(store)
    historical = next(item for item in release["objects"] if item["logicalPath"] == HISTORICAL_DERIVED_LOGICAL_PATH)
    assert historical["key"] != first_key


def test_historical_policy_remains_without_2021_fallback() -> None:
    versions = [
        TerritoryGeometryVersion(
            territory_level="province", reference_year=2020, territory_reference_date="2020-01-01",
            territory_source="ISTAT", geometry_reference="canonical/territories/reference_year=2020/province.parquet",
        ),
        TerritoryGeometryVersion(
            territory_level="province", reference_year=2022, territory_reference_date="2022-01-01",
            territory_source="ISTAT", geometry_reference="canonical/territories/reference_year=2022/province.parquet",
        ),
    ]
    plan = build_bigbang_historical_processing_plan(versions)
    assert next(entry for entry in plan if entry.reference_year == 2021).process_provinces is False


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
