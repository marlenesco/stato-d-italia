import json
from hashlib import sha256
from pathlib import Path

import pytest

import stato_italia.download as download_module
import stato_italia.forests as forests
from stato_italia.download import download
from stato_italia.ingestion_plan import clear_ingestion_plan, load_ingestion_plan
from stato_italia.source_state import check_persisted_sources


@pytest.fixture(autouse=True)
def _clear_plan() -> None:
    clear_ingestion_plan()
    yield
    clear_ingestion_plan()


def _load(tmp_path: Path, raw_root: Path, sources: list[dict], *, catalog: dict | None = None) -> None:
    payload = {
        "schemaVersion": 1, "activeReleaseId": "r1", "scope": "geospatial",
        "sourceChecks": len(sources), "sourcesChanged": sum(item["status"] == "changed" for item in sources),
        "sourcesUnchanged": sum(item["status"] == "unchanged" for item in sources),
        "sourcesUnverifiable": sum(item["status"] == "unverifiable" for item in sources),
        "changed": any(item["status"] == "changed" for item in sources), "sources": sources,
    }
    if catalog is not None:
        payload["catalog"] = catalog
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload))
    load_ingestion_plan(path, scope="geospatial", active_release_id="r1", raw_root=raw_root)


def _baseline_entry(source_id: str, asset_path: str, body: bytes, status: str = "unchanged") -> dict:
    return {
        "source_id": source_id, "asset_path": asset_path, "status": status,
        "baseline_sha256": sha256(body).hexdigest(), "baseline_bytes": len(body),
    }


def _write_baseline(raw_root: Path, entry: dict, body: bytes) -> Path:
    destination = raw_root / entry["asset_path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(body)
    Path(f"{destination}.metadata.json").write_text(json.dumps({
        "source_id": entry["source_id"], "sha256": entry["baseline_sha256"],
        "bytes": len(body), "acquired_at": "2026-08-31T00:00:00Z",
        "resolved_url": "https://official.example/asset",
    }))
    return destination


def test_valid_local_asset_is_reused_without_upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw_root = tmp_path / "raw"
    entry = _baseline_entry("official-source", "official-source/asset.zip", b"V1")
    destination = _write_baseline(raw_root, entry, b"V1")
    _load(tmp_path, raw_root, [entry])
    monkeypatch.setattr(
        download_module.requests, "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("upstream contacted")),
    )

    result = download("https://official.example/asset", destination, "official-source")

    assert result["unchanged"] is True
    assert result["plan_status"] == "unchanged"
    assert destination.read_bytes() == b"V1"


def test_unverifiable_infc_preserves_trusted_baseline_without_upstream_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw"
    entry = _baseline_entry(
        "infc-2015-forests", "infc-2015-forests/volume.zip", b"trusted", "unverifiable",
    )
    destination = _write_baseline(raw_root, entry, b"trusted")
    _load(tmp_path, raw_root, [entry])
    monkeypatch.setattr(
        download_module.requests, "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("INFC retried during ingest")),
    )

    result = download(
        "https://www.inventarioforestale.org/volume.zip", destination, "infc-2015-forests",
    )

    assert result["plan_status"] == "unverifiable"
    assert result["unchanged"] is True
    assert destination.read_bytes() == b"trusted"


def test_preflight_full_body_is_promoted_without_second_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = b"V1"
    new = b"V2-complete-body"
    state = {"schemaVersion": 1, "sources": [{
        "source_id": "infc-2015-forests", "asset_path": "infc-2015-forests/biomass.zip",
        "resolved_url": "https://www.inventarioforestale.org/biomass.zip",
        "etag": None, "last_modified": None, "sha256": sha256(old).hexdigest(), "bytes": len(old),
        "dataset_version": "infc2015-published-tables", "period": "2015",
        "checked_at": "2026-08-31T00:00:00Z",
    }]}

    class Response:
        status_code = 200
        url = "https://www.inventarioforestale.org/biomass.zip"
        headers = {"Content-Type": "application/zip", "ETag": '"v2"'}

        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def raise_for_status(self): return None
        def iter_content(self, chunk_size: int):
            del chunk_size
            yield new

    calls = 0

    def get(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response()

    monkeypatch.setattr("stato_italia.source_state.requests.get", get)
    result = check_persisted_sources(
        state, scope="geospatial", stage_dir=tmp_path / "data/.preflight/geospatial",
    )
    assert result["sourcesChanged"] == 1
    result |= {"schemaVersion": 1, "activeReleaseId": "r1"}
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(result))
    raw_root = tmp_path / "data/raw"
    load_ingestion_plan(plan_path, scope="geospatial", active_release_id="r1", raw_root=raw_root)
    monkeypatch.setattr(
        download_module.requests, "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("duplicate upstream GET")),
    )

    destination = raw_root / "infc-2015-forests/biomass.zip"
    metadata = download(state["sources"][0]["resolved_url"], destination, "infc-2015-forests")

    assert calls == 1
    assert destination.read_bytes() == new
    assert metadata["sha256"] == sha256(new).hexdigest()


def test_one_changed_infc_asset_reuses_other_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "data/raw"
    entries = []
    changed_id = "biomass"
    for asset in forests.INFC["assets"]:
        asset_path = f"infc-2015-forests/{asset['id']}.zip"
        baseline = f"baseline-{asset['id']}".encode()
        entry = _baseline_entry("infc-2015-forests", asset_path, baseline)
        if asset["id"] == changed_id:
            staged = tmp_path / "staged-biomass.zip"
            staged.write_bytes(b"changed-biomass")
            entry |= {
                "status": "changed", "staged_path": str(staged),
                "observed_sha256": sha256(staged.read_bytes()).hexdigest(),
                "observed_bytes": staged.stat().st_size,
                "remote": {"resolved_url": asset["url"], "checked_at": "2026-09-01T00:00:00Z"},
            }
        else:
            _write_baseline(raw_root, entry, baseline)
        entries.append(entry)
    _load(tmp_path, raw_root, entries)
    monkeypatch.setattr(
        download_module.requests, "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("INFC asset redownloaded")),
    )

    result = forests.fetch_forests(tmp_path / "data", include_infc=True, check_geospatial=False)

    assert len(result["infc"]) == len(forests.INFC["assets"])
    assert sum(item["plan_status"] == "changed" for item in result["infc"]) == 1
    assert (raw_root / f"infc-2015-forests/{changed_id}.zip").read_bytes() == b"changed-biomass"


def test_unrelated_unchanged_source_is_not_downloaded_when_another_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_root = tmp_path / "raw"
    unchanged = _baseline_entry("source-b", "source-b/b.xlsx", b"B1")
    destination = _write_baseline(raw_root, unchanged, b"B1")
    staged = tmp_path / "source-a-v2.xlsx"
    staged.write_bytes(b"A2")
    changed = _baseline_entry("source-a", "source-a/a.xlsx", b"A1", "changed") | {
        "staged_path": str(staged), "observed_sha256": sha256(b"A2").hexdigest(),
        "observed_bytes": 2, "remote": {"checked_at": "2026-09-01T00:00:00Z"},
    }
    _load(tmp_path, raw_root, [changed, unchanged])
    monkeypatch.setattr(
        download_module.requests, "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unrelated source contacted")),
    )

    changed_result = download("https://official.example/a", raw_root / changed["asset_path"], "source-a")
    unchanged_result = download("https://official.example/b", destination, "source-b")

    assert changed_result["plan_status"] == "changed"
    assert unchanged_result["plan_status"] == "unchanged"
    assert destination.read_bytes() == b"B1"


def test_changed_copernicus_catalog_reuses_preflight_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    staged = tmp_path / "copernicus-catalog.json"
    catalog = {
        "source_id": "copernicus-hrl-forests", "signature": "c" * 64,
        "products_payload": [{"Id": "product-v2", "Name": "HRL V2"}],
        "products": 1, "checked_at": "2026-09-01T00:00:00Z",
    }
    staged.write_text(json.dumps(catalog))
    _load(tmp_path, tmp_path / "data/raw", [], catalog={
        "status": "changed", "signature": catalog["signature"], "stagedPath": str(staged),
    })
    monkeypatch.setenv(forests.HRL["client_id_environment"], "fake")
    monkeypatch.setenv(forests.HRL["client_secret_environment"], "fake")
    monkeypatch.setattr(forests, "_cdse_token", lambda _source: "fake-token")
    monkeypatch.setattr(
        forests, "_check_catalog",
        lambda *_args: (_ for _ in ()).throw(AssertionError("catalog downloaded twice")),
    )
    process_calls = []

    def process(*_args, **kwargs):
        process_calls.append(kwargs)
        return {"changed": False, "requests": 0, "files": [], "raw_files": [], "raw_bytes": 0}

    monkeypatch.setattr(forests, "_fetch_process_raster_slices", process)

    result = forests.fetch_forests(
        tmp_path / "data", include_infc=False, check_geospatial=True,
    )

    assert result["catalog"]["signature"] == "c" * 64
    assert process_calls == [{"force": True}]
    persisted = json.loads((tmp_path / "data/raw/copernicus-hrl-forests/catalog.json").read_text())
    assert persisted["products"] == catalog["products_payload"]


def test_unchanged_copernicus_catalog_makes_no_process_api_acquisition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        forests, "_fetch_process_raster_slices",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Process API contacted")),
    )

    result = forests.fetch_forests(
        tmp_path / "data", include_infc=False, check_geospatial=False,
    )

    assert result["catalog"] == {"status": "deferred"}
    assert "raster" not in result


def test_forest_raw_declaration_excludes_stale_same_scope_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(forests.HRL["processing_mode_environment"], "statistical-api")
    stale = tmp_path / "raw/infc-2015-forests/old.zip"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"obsolete")

    declared = set(forests.declared_forest_raw_paths(tmp_path))

    assert stale not in declared
    assert tmp_path / "raw/copernicus-hrl-forests/catalog.json" in declared
    assert {
        tmp_path / f"raw/infc-2015-forests/{asset['id']}.zip"
        for asset in forests.INFC["assets"]
    } <= declared
