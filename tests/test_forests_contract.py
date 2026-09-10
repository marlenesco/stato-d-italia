from pathlib import Path
import json
import os
import re

import numpy as np
import pandas as pd
import pytest
import requests
from shapely.geometry import Polygon

from stato_italia.cli import load_local_env
import stato_italia.forests as forests
from stato_italia.forests_delivery import generate_forests_delivery
from stato_italia.forests import CORINE, HRL, INFC, _asset_periods, _catalog_snapshot, _check_catalog, _coverage_report, _expected_region_codes_from_coverage, _persist_catalog, _process_payload, _process_request_contract, _process_tile_grid, _read_statistical_checkpoint, _reference_years_for_asset, _require_numeric_tree_cover_change_coverage, _stats_payload, _valid_source_values, _write_statistical_checkpoint, forest_coverage_mode, territory_reference_year_for_period
from stato_italia.territories import territory_reference_date


def test_corine_and_hrl_keep_separate_forest_cover_metrics() -> None:
    assert CORINE["source_id"] != HRL["source_id"]
    assert "CORINE" in CORINE["known_limitations"][0]
    assert HRL["assets"][0]["kind"] == "tree_cover_density"


def test_change_raster_requires_two_reference_years() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_change")
    assert _reference_years_for_asset(asset, Path("tree-cover-change-2018-2021.tif")) == (2018, 2021)
    with pytest.raises(ValueError, match="start and end year"):
        _reference_years_for_asset(asset, Path("tree-cover-change-2021.tif"))


def test_derived_metric_identity_includes_territory_geometry_version() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density") | {"source_id": HRL["source_id"]}
    common = {"territory_id": "it:province:215", "level": "province"}
    historical = common | {"territory_version_id": "it:province:215@2018-01-01"}
    current = common | {"territory_version_id": "it:province:215@2021-12-31"}

    first = forests._record(asset, "slice.tif", "a" * 64, historical, "tree_cover_mean", 20.0, 2021, 2021)
    repeated = forests._record(asset, "slice.tif", "a" * 64, historical, "tree_cover_mean", 20.0, 2021, 2021)
    changed_geometry = forests._record(asset, "slice.tif", "a" * 64, current, "tree_cover_mean", 20.0, 2021, 2021)

    assert first["derived_metric_id"] == repeated["derived_metric_id"]
    assert first["derived_metric_id"] != changed_geometry["derived_metric_id"]


def test_statistical_payload_uses_cdse_byoc_and_equal_area_crs() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density")
    territory = {"geometry_wkb": Polygon([(12, 41), (12.1, 41), (12.1, 41.1), (12, 41.1)]).wkb}
    payload = _stats_payload(asset, territory, {
        "contentDateStart": "2023-01-01T00:00:00Z",
        "contentDateEnd": "2023-12-31T23:59:59Z",
    })
    assert payload["input"]["data"][0]["type"] == f"byoc-{asset['byoc_collection_id']}"
    assert payload["input"]["bounds"]["properties"]["crs"].endswith("/3035")
    assert payload["calculations"]["default"]["statistics"]["default"]["percentiles"]["k"] == [25, 50, 75]


def test_statistical_tcpc_uses_the_verified_catalog_content_date_interval() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_change")
    territory = {"geometry_wkb": Polygon([(12, 41), (12.1, 41), (12.1, 41.1), (12, 41.1)]).wkb}
    snapshot = {
        "contentDateStart": "2018-01-01T00:00:00Z",
        "contentDateEnd": "2021-12-31T23:59:59Z",
    }

    payload = _stats_payload(asset, territory, snapshot)

    expected = {"from": snapshot["contentDateStart"], "to": snapshot["contentDateEnd"]}
    assert payload["input"]["data"][0]["dataFilter"]["timeRange"] == expected
    assert payload["aggregation"]["timeRange"] == expected


def test_statistical_mode_contract_declares_real_and_future_modes() -> None:
    assert HRL["processing_modes"] == ["statistical-api", "raster"]
    assert HRL["development_slice"]["region_istat_codes"] == ["03", "09", "12", "19"]
    forest_type = next(item for item in HRL["assets"] if item["kind"] == "forest_type")
    assert forest_type["class_codes"]["mixed"] == 3
    assert HRL["coverage_default"] == "national"
    assert {asset["id"] for asset in HRL["assets"] if asset.get("statistical_api_enabled", True)} == {
        "hrl_tree_cover_density_100m", "hrl_forest_type", "hrl_tree_cover_presence_change",
    }
    assert all(asset["snapshot_timestamp"] == "content_date_start_at_reference_year" for asset in HRL["assets"])
    assert next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_density").get("source_nodata_codes") is None
    assert next(asset for asset in HRL["assets"] if asset["kind"] == "forest_type")["source_nodata_codes"] == [255]
    assert next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_change")["source_nodata_codes"] == [255]


def test_development_coverage_requires_explicit_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HRL["coverage_mode_environment"], raising=False)
    assert forest_coverage_mode() == "national"
    monkeypatch.setenv(HRL["coverage_mode_environment"], "development_slice")
    assert forest_coverage_mode() == "development_slice"


def test_catalog_snapshot_is_unambiguous_for_exact_asset_period() -> None:
    entry = {"asset_id": "hrl_tree_cover_density_100m", "period": [2023, 2023], "items": [{"Id": "one", "Name": "TCD_2023", "ContentDate": {"Start": "2023-01-01T00:00:00Z", "End": "2023-12-31T23:59:59Z"}}]}
    snapshot = _catalog_snapshot({"products_payload": [entry]}, HRL["assets"][0], 2023, 2023)
    assert snapshot["signature"] == forests.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with pytest.raises(ValueError, match="missing or ambiguous"):
        _catalog_snapshot({"products_payload": [entry, entry]}, HRL["assets"][0], 2023, 2023)


def test_statistical_jobs_use_the_historical_istat_population_for_each_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_years: list[int] = []

    def territories(_canonical_root: Path, year: int) -> pd.DataFrame:
        requested_years.append(year)
        return pd.DataFrame([{
            "territory_id": "it:region:01",
            "territory_version_id": f"it:region:01@{territory_reference_date(year)}",
            "level": "region",
        }])

    monkeypatch.setattr(forests, "_slice_territories", territories)
    monkeypatch.setattr(
        forests,
        "_catalog_snapshot",
        lambda _catalog, asset, start, end: {
            "contentDateStart": f"{start}-01-01T00:00:00Z",
            "contentDateEnd": f"{end}-12-31T23:59:59Z",
            "signature": f"{asset['id']}:{start}-{end}",
        },
    )

    jobs = forests._statistical_jobs(tmp_path, {"products": []})

    observed = {
        (asset["id"], start, end, territory["territory_version_id"])
        for asset, start, end, _snapshot, territory in jobs
    }
    assert requested_years == [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2018, 2021, 2024, 2021]
    assert observed == {
        (asset_id, start, end, f"it:region:01@{territory_reference_date(end)}")
        for asset_id, periods in {
            "hrl_tree_cover_density_100m": [(year, year) for year in range(2018, 2025)],
            "hrl_forest_type": [(2018, 2018), (2021, 2021), (2024, 2024)],
            "hrl_tree_cover_presence_change": [(2018, 2021)],
        }.items() for start, end in periods
    }


def test_declared_process_slices_use_the_geometry_population_for_each_asset_period(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "data"
    seen_years: list[int] = []
    monkeypatch.setenv(HRL["processing_mode_environment"], "raster")
    monkeypatch.setattr(forests, "_expected_region_codes", lambda _canonical, year: seen_years.append(year) or {"01"})
    for asset in (item for item in HRL["assets"] if item.get("statistical_api_enabled", True)):
        for start, end in _asset_periods(asset):
            manifest = forests._process_slice_path(root, asset, start, end, "01", 0, 0).parent / "slice-manifest.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps({"source_id": HRL["source_id"], "asset_id": asset["id"], "period": [start, end], "region_istat_code": "01", "entries": []}))
    for asset in INFC["assets"]:
        raw = root / "raw" / INFC["source_id"] / f"{asset['id']}.zip"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(b"infc")
        raw.with_suffix(raw.suffix + ".metadata.json").write_text("{}")
    catalog = root / "raw" / HRL["source_id"] / "catalog.json"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text("{}")

    forests.declared_forest_raw_paths(root)

    assert seen_years == [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2018, 2021, 2024, 2021]


def test_forest_slice_preserves_a_closed_canonical_municipality_population(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HRL["coverage_mode_environment"], raising=False)
    root = tmp_path / "canonical" / "territories" / "reference_year=2021"
    root.mkdir(parents=True)
    common = {"reference_date": "2021-12-31", "canonical_contract_version": 3}
    pd.DataFrame([{
        **common, "territory_id": "it:region:01", "territory_version_id": "it:region:01@2021-12-31",
        "level": "region", "istat_code": "01", "name": "Piemonte", "parent_istat_code": None,
    }]).to_parquet(root / "region.parquet")
    pd.DataFrame([{
        **common, "territory_id": "it:province:201", "territory_version_id": "it:province:201@2021-12-31",
        "level": "province", "istat_code": "201", "name": "Torino", "parent_istat_code": "01",
    }]).to_parquet(root / "province.parquet")
    pd.DataFrame([{
        **common, "territory_id": f"it:municipality:{code}", "territory_version_id": f"it:municipality:{code}@2021-12-31",
        "level": "municipality", "istat_code": code, "name": f"Comune {code}", "parent_istat_code": "201",
    } for code in ("001001", "001002")]).to_parquet(root / "municipality.parquet")

    selected = forests._slice_territories(tmp_path / "canonical", 2021)

    assert len(selected[selected["level"] == "municipality"]) == 2
    assert selected["territory_version_id"].str.endswith("@2021-12-31").all()


def test_forest_slice_fails_instead_of_dropping_orphan_municipalities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HRL["coverage_mode_environment"], raising=False)
    root = tmp_path / "canonical" / "territories" / "reference_year=2021"
    root.mkdir(parents=True)
    common = {"reference_date": "2021-12-31", "canonical_contract_version": 3}
    pd.DataFrame([{
        **common, "territory_id": "it:region:01", "territory_version_id": "it:region:01@2021-12-31",
        "level": "region", "istat_code": "01", "name": "Piemonte", "parent_istat_code": None,
    }]).to_parquet(root / "region.parquet")
    pd.DataFrame([{
        **common, "territory_id": "it:province:201", "territory_version_id": "it:province:201@2021-12-31",
        "level": "province", "istat_code": "201", "name": "Torino", "parent_istat_code": "01",
    }]).to_parquet(root / "province.parquet")
    pd.DataFrame([{
        **common, "territory_id": "it:municipality:001001", "territory_version_id": "it:municipality:001001@2021-12-31",
        "level": "municipality", "istat_code": "001001", "name": "Orfano", "parent_istat_code": "999",
    }]).to_parquet(root / "municipality.parquet")

    with pytest.raises(ValueError, match="orphan municipalities"):
        forests._slice_territories(tmp_path / "canonical", 2021)


def test_catalog_queries_every_supported_asset_period_and_verifies_reference_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            query = calls[-1]["params"]["$filter"]
            years = [year for year in range(2018, 2025) if f"{year}-01-01" in query]
            year = years[0]
            contains = query.split("contains(Name,'", 1)[1].split("')", 1)[0]
            asset = next(item for item in HRL["assets"] if item["catalog_name_contains_template"].format(start_year=2018 if "C2018-2021" in contains else year, end_year=2021 if "C2018-2021" in contains else year) == contains)
            name = re.sub(r"\^|\$", "", asset["catalog_name_regex_template"].format(start_year=2018 if "C2018-2021" in contains else year, end_year=2021 if "C2018-2021" in contains else year)).replace("[A-Z0-9]+", "E09N27").replace("[0-9]+", "01")
            end = 2021 if "TCPC" in name else year
            return {"value": [{"Id": f"id-{year}", "Name": name, "ContentDate": {"Start": f"{year}-01-01T00:00:00.000000Z", "End": f"{end}-12-31T23:59:59.999999Z"}, "Checksum": None, "S3Path": None, "OriginDate": None}]}

    def get(*_args: object, **kwargs: object) -> Response:
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr(forests.requests, "get", get)
    products = forests._catalog_products(HRL)

    assert len(products) == 14  # TCD (7), FTY (3), disabled DLT catalogue (3), TCPC (1)
    assert {tuple(item["period"]) for item in products if item["asset_id"] == "hrl_tree_cover_density_100m"} == {(year, year) for year in range(2018, 2025)}
    assert all("ContentDate/Start ge" in call["params"]["$filter"] for call in calls)
    assert all(call["headers"] == {"Accept": "application/json"} for call in calls)


def test_catalog_discovery_retries_transient_statuses_without_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.headers: dict[str, str] = {}
            self.closed = False

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

        def close(self) -> None:
            self.closed = True

    responses = iter([Response(503), Response(503), Response(200)])
    calls: list[dict] = []
    pauses: list[float] = []
    monkeypatch.setattr(forests.requests, "get", lambda *_args, **kwargs: calls.append(kwargs) or next(responses))
    monkeypatch.setattr(forests, "sleep", pauses.append)

    response = forests._get_catalog(HRL, {"$top": "1"})

    assert response.status_code == 200
    assert len(calls) == 3
    assert pauses == [1, 2]
    assert all("Authorization" not in call["headers"] for call in calls)


def test_catalog_discovery_respects_retry_after_for_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, status_code: int, retry_after: str | None = None) -> None:
            self.status_code = status_code
            self.headers = {"Retry-After": retry_after} if retry_after else {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

        def close(self) -> None:
            return None

    responses = iter([Response(429, "7"), Response(200)])
    pauses: list[float] = []
    monkeypatch.setattr(forests.requests, "get", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(forests, "sleep", pauses.append)

    assert forests._get_catalog(HRL, {"$top": "1"}).status_code == 200
    assert pauses == [7.0]


def test_catalog_discovery_fails_closed_for_persistent_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 403
        headers: dict[str, str] = {}

        def close(self) -> None:
            return None

    calls = 0

    def get(*_args: object, **_kwargs: object) -> Response:
        nonlocal calls
        calls += 1
        return Response()

    monkeypatch.setattr(forests.requests, "get", get)

    with pytest.raises(requests.HTTPError, match="denied unauthenticated product discovery: HTTP 403") as error:
        forests._get_catalog(HRL, {"$top": "1"})

    assert calls == 1
    assert "Bearer" not in str(error.value)
    assert "token" not in str(error.value).lower()


def test_process_api_keeps_bearer_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status_code = 200
        headers: dict[str, str] = {}

        def close(self) -> None:
            return None

    captured: dict[str, str] = {}

    def post(*_args: object, **kwargs: object) -> Response:
        captured.update(kwargs["headers"])  # type: ignore[arg-type]
        return Response()

    monkeypatch.setattr(forests.requests, "post", post)

    assert forests._post_process_raster({"request": "payload"}, "process-token").status_code == 200
    assert captured == {"Accept": "image/tiff", "Authorization": "Bearer process-token"}


def test_catalog_contract_rejects_tcd_confidence_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"value": [{
                "Id": "confidence", "Name": "CLMS_HRLVLCC_TCDCL_S2018_R10m_E09N27_03035_V01_R00",
                "ContentDate": {"Start": "2018-01-01T00:00:00.000000Z"},
            }]}

    monkeypatch.setattr(forests.requests, "get", lambda *_args, **_kwargs: Response())
    source = HRL | {"assets": [next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_density") | {"years": [2018]}]}

    with pytest.raises(ValueError, match="unexpected product name"):
        forests._catalog_products(source)


def test_catalog_contract_rejects_missing_or_ambiguous_content_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    asset = next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_change")
    valid_name = "CLMS_HRLVLCC_TCPC_C2018-2021_R20m_E09N27_03035_V01_R00"

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"value": [{"Id": "missing-end", "Name": valid_name, "ContentDate": {"Start": "2018-01-01T00:00:00Z"}}]}

    monkeypatch.setattr(forests.requests, "get", lambda *_args, **_kwargs: Response())
    with pytest.raises(ValueError, match="unexpected timestamp"):
        forests._catalog_products(HRL | {"assets": [asset]})
    with pytest.raises(ValueError, match="ambiguous content dates"):
        _catalog_snapshot({"products_payload": [{"asset_id": asset["id"], "period": [2018, 2021], "items": [
            {"Id": "one", "Name": valid_name, "ContentDate": {"Start": "2018-01-01T00:00:00Z", "End": "2021-12-31T23:59:59Z"}},
            {"Id": "two", "Name": valid_name, "ContentDate": {"Start": "2018-01-02T00:00:00Z", "End": "2021-12-31T23:59:59Z"}},
        ]}]}, asset, 2018, 2021)


def test_coverage_report_distinguishes_valid_nodata_and_rejects_duplicate_payloads() -> None:
    coverage = [
        {"assetId": "hrl_tree_cover_density_100m", "period": "2018-2018", "territoryLevel": "region", "territoryReferenceYear": 2023, "expectedTerritoryIds": ["it:region:01"], "numericTerritoryIds": ["it:region:01"], "validNoDataTerritoryIds": []},
        {"assetId": "hrl_tree_cover_density_100m", "period": "2018-2018", "territoryLevel": "region", "territoryReferenceYear": 2023, "expectedTerritoryIds": ["it:region:02"], "numericTerritoryIds": [], "validNoDataTerritoryIds": ["it:region:02"]},
        {"assetId": "hrl_tree_cover_density_100m", "period": "2021-2021", "territoryLevel": "region", "territoryReferenceYear": 2023, "expectedTerritoryIds": ["it:region:01"], "numericTerritoryIds": ["it:region:01"], "validNoDataTerritoryIds": []},
        {"assetId": "hrl_tree_cover_density_100m", "period": "2021-2021", "territoryLevel": "region", "territoryReferenceYear": 2023, "expectedTerritoryIds": ["it:region:02"], "numericTerritoryIds": [], "validNoDataTerritoryIds": ["it:region:02"]},
    ]
    coverage = [item | {"territoryGeometryReference": "istat-region-2023.pmtiles"} for item in coverage]
    table = pd.DataFrame([
        {"metric_id": "tree_cover_mean", "territory_level": "region", "period_start": "2018-01-01", "period_end": "2018-12-31", "territory_id": "it:region:01", "value_decimal": 20.0},
        {"metric_id": "tree_cover_mean", "territory_level": "region", "period_start": "2021-01-01", "period_end": "2021-12-31", "territory_id": "it:region:01", "value_decimal": 21.0},
        {"metric_id": "tree_cover_p25", "territory_level": "region", "period_start": "2018-01-01", "period_end": "2018-12-31", "territory_id": "it:region:01", "value_decimal": 5.0},
        {"metric_id": "tree_cover_p25", "territory_level": "region", "period_start": "2021-01-01", "period_end": "2021-12-31", "territory_id": "it:region:01", "value_decimal": 5.0},
    ])
    report = _coverage_report(table.assign(methodology_version="hrl_tree_cover_density_100m"), coverage, {2023: {"01", "02"}})
    assert sum(entry["validNoDataCount"] for entry in report["entries"]) == 2
    mean_diagnostic = next(item for item in report["temporalDiagnostics"] if item["metricId"] == "tree_cover_mean" and item["period"] == "2021-2021")
    p25_diagnostic = next(item for item in report["temporalDiagnostics"] if item["metricId"] == "tree_cover_p25" and item["period"] == "2021-2021")
    assert mean_diagnostic["comparisonWithPrevious"]["percentChangedAmongComparable"] == 100.0
    assert p25_diagnostic["identicalToPrevious"] is True
    snapshot = next(item for item in report["snapshotDiagnostics"] if item["period"] == "2021-2021")
    assert snapshot["comparisonWithPrevious"]["identical"] is False
    assert snapshot["comparisonWithPrevious"]["identicalMetrics"] == ["tree_cover_p25"]
    duplicated = table.copy()
    duplicated.loc[(duplicated["period_start"] == "2021-01-01") & (duplicated["metric_id"] == "tree_cover_mean"), "value_decimal"] = 20.0
    duplicated.loc[(duplicated["period_start"] == "2021-01-01") & (duplicated["metric_id"] == "tree_cover_p25"), "value_decimal"] = 5.0
    with pytest.raises(ValueError, match="byte-identical"):
        _coverage_report(duplicated.assign(methodology_version="hrl_tree_cover_density_100m"), coverage, {2023: {"01", "02"}})
    with pytest.raises(ValueError, match="source snapshot signature reused"):
        _coverage_report(table.assign(methodology_version="hrl_tree_cover_density_100m", source_snapshot_signature="s" * 64), coverage, {2023: {"01", "02"}})


def test_regional_coverage_union_is_per_snapshot_and_rejects_missing_development_or_overlap() -> None:
    entries = [
        {"assetId": "tcd", "period": "2018-2018", "territoryLevel": "region", "territoryReferenceYear": 2018, "expectedTerritoryIds": ["it:region:01"], "numericTerritoryIds": ["it:region:01"], "validNoDataTerritoryIds": []},
        {"assetId": "tcd", "period": "2018-2018", "territoryLevel": "region", "territoryReferenceYear": 2018, "expectedTerritoryIds": ["it:region:02"], "numericTerritoryIds": [], "validNoDataTerritoryIds": ["it:region:02"]},
        {"assetId": "tcd", "period": "2018-2018", "territoryLevel": "region", "territoryReferenceYear": 2018, "expectedTerritoryIds": ["it:region:03"], "numericTerritoryIds": ["it:region:03"], "validNoDataTerritoryIds": []},
    ]
    entries = [item | {"territoryGeometryReference": "istat-region-2018.pmtiles"} for item in entries]
    assert _expected_region_codes_from_coverage(entries, "tcd", "2018-2018") == {"01", "02", "03"}
    table = pd.DataFrame([
        {"metric_id": "tree_cover_mean", "methodology_version": "tcd", "territory_level": "region", "period_start": "2018-01-01", "period_end": "2018-12-31", "territory_id": "it:region:01", "value_decimal": 10.0},
        {"metric_id": "tree_cover_mean", "methodology_version": "tcd", "territory_level": "region", "period_start": "2018-01-01", "period_end": "2018-12-31", "territory_id": "it:region:03", "value_decimal": 11.0},
    ])
    assert _coverage_report(table, entries, {2018: {"01", "02", "03"}})["coverageMode"] == "national"
    missing_table = table[table["territory_id"] != "it:region:03"]
    with pytest.raises(ValueError, match="differs from ISTAT"):
        _coverage_report(missing_table, entries[:-1], {2018: {"01", "02", "03"}})
    development = [entry | {"expectedTerritoryIds": [f"it:region:{code}"], "numericTerritoryIds": [f"it:region:{code}"], "validNoDataTerritoryIds": []} for entry, code in zip(entries, ("03", "09", "12"), strict=True)]
    development_table = pd.DataFrame([
        {"metric_id": "tree_cover_mean", "methodology_version": "tcd", "territory_level": "region", "period_start": "2018-01-01", "period_end": "2018-12-31", "territory_id": f"it:region:{code}", "value_decimal": float(index)}
        for index, code in enumerate(("03", "09", "12"), start=1)
    ])
    with pytest.raises(ValueError, match="differs from ISTAT"):
        _coverage_report(development_table, development, {2018: {"01", "02", "03"}})
    overlapping = entries + [entries[0]]
    with pytest.raises(ValueError, match="overlapping"):
        _expected_region_codes_from_coverage(overlapping, "tcd", "2018-2018")


def test_source_nodata_255_is_not_zero_and_real_zero_is_preserved() -> None:
    forest_type = next(asset for asset in HRL["assets"] if asset["kind"] == "forest_type")
    assert _valid_source_values(forest_type, np.array([255, 255, 255], dtype=np.int16)).size == 0
    assert _valid_source_values(forest_type, np.array([0, 0, 0], dtype=np.int16)).tolist() == [0, 0, 0]


def test_tcpc_source_class_contract_preserves_zero_and_rejects_unknown_codes() -> None:
    tcpc = next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_change")
    assert _valid_source_values(tcpc, np.array([0, 1, 2, 10, 255], dtype=np.int16)).tolist() == [0, 1, 2, 10]
    with pytest.raises(ValueError, match="Unexpected source raster class"):
        _valid_source_values(tcpc, np.array([3], dtype=np.int16))


def test_tcpc_all_valid_nodata_regional_coverage_fails_closed() -> None:
    entries = [
        {"assetId": "hrl_tree_cover_presence_change", "period": "2018-2021", "territoryLevel": "region", "territoryReferenceYear": 2021, "territoryGeometryReference": "istat-region-2021.pmtiles", "expectedTerritoryIds": ["it:region:01"], "numericTerritoryIds": [], "validNoDataTerritoryIds": ["it:region:01"]},
    ]
    with pytest.raises(ValueError, match="has no numeric regional coverage"):
        _require_numeric_tree_cover_change_coverage(entries)


def test_temporal_diagnostics_allow_source_nodata_transitions() -> None:
    coverage = [
        {"assetId": "tcd", "period": "2018-2018", "territoryLevel": "region", "territoryReferenceYear": 2023, "expectedTerritoryIds": ["it:region:01", "it:region:02"], "numericTerritoryIds": ["it:region:01"], "validNoDataTerritoryIds": ["it:region:02"]},
        {"assetId": "tcd", "period": "2021-2021", "territoryLevel": "region", "territoryReferenceYear": 2023, "expectedTerritoryIds": ["it:region:01", "it:region:02"], "numericTerritoryIds": ["it:region:02"], "validNoDataTerritoryIds": ["it:region:01"]},
    ]
    coverage = [item | {"territoryGeometryReference": "istat-region-2023.pmtiles"} for item in coverage]
    table = pd.DataFrame([
        {"metric_id": "tree_cover_mean", "methodology_version": "tcd", "territory_level": "region", "period_start": "2018-01-01", "period_end": "2018-12-31", "territory_id": "it:region:01", "value_decimal": 10.0},
        {"metric_id": "tree_cover_mean", "methodology_version": "tcd", "territory_level": "region", "period_start": "2021-01-01", "period_end": "2021-12-31", "territory_id": "it:region:02", "value_decimal": 10.0},
    ])

    report = _coverage_report(table, coverage, {2023: {"01", "02"}})

    comparison = report["temporalDiagnostics"][1]["comparisonWithPrevious"]
    assert comparison == {
        "period": "2018-2018", "territoryComparable": True, "reason": None, "numericInBoth": 0, "becameNoData": 1,
        "becameNumeric": 1, "noDataInBoth": 0, "percentChangedAmongComparable": None,
        "medianAbsoluteDifference": None, "maximumAbsoluteDifference": None, "correlation": None,
    }


def test_derived_delivery_requires_national_coverage_and_exposes_geometry_reference(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    territories = canonical / "territories" / "reference_year=2023"
    territories.mkdir(parents=True)
    pd.DataFrame([
        {"territory_id": "it:region:01", "name": "Piemonte", "istat_code": "01"},
        {"territory_id": "it:region:02", "name": "Valle d'Aosta", "istat_code": "02"},
    ]).to_parquet(territories / "region.parquet")
    zonal = canonical / "forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    zonal.parent.mkdir(parents=True)
    pd.DataFrame([
        {"metric_id": "tree_cover_mean", "territory_id": "it:region:01", "territory_version_id": "it:region:01@2023-01-01", "territory_level": "region", "period_start": "2023-01-01", "period_end": "2023-12-31", "value_decimal": 21.0, "unit_ucum": "%", "official_status": "derived_by_stato_italia", "methodology_version": "hrl_tree_cover_density_100m"},
        {"metric_id": "tree_cover_mean", "territory_id": "it:region:02", "territory_version_id": "it:region:02@2023-01-01", "territory_level": "region", "period_start": "2023-01-01", "period_end": "2023-12-31", "value_decimal": 22.0, "unit_ucum": "%", "official_status": "derived_by_stato_italia", "methodology_version": "hrl_tree_cover_density_100m"},
    ]).to_parquet(zonal)
    infc = canonical / "forests" / "infc.parquet"
    pd.DataFrame(columns=["metric_id", "territory_id", "territory_version_id", "territory_level", "period_start", "period_end", "value_decimal", "official_status"]).to_parquet(infc)
    coverage = forests.forest_coverage_report_path(zonal)
    coverage.write_text(json.dumps({"coverageMode": "national", "entries": [{"assetId": "hrl_tree_cover_density_100m", "period": "2023-2023", "territoryLevel": "region", "territoryReferenceYear": 2023, "territoryGeometryReference": "istat-region-2023.pmtiles", "expectedTerritoryIds": ["it:region:01", "it:region:02"], "numericTerritoryIds": ["it:region:01", "it:region:02"], "validNoDataTerritoryIds": []}]}))
    geometry = tmp_path / "istat-region-2023.pmtiles"
    geometry.touch()

    generate_forests_delivery(zonal, infc, canonical, tmp_path / "delivery", "release-test", {"region": geometry}, force=True)

    payload = json.loads((tmp_path / "delivery" / "foreste" / "maps" / "tree_cover_mean" / "2023-2023" / "region.json").read_text())
    ranking = json.loads((tmp_path / "delivery" / "foreste" / "rankings" / "tree_cover_mean" / "2023-2023" / "region.json").read_text())
    assert payload["territoryGeometryReference"] == "istat-region-2023.pmtiles"
    assert payload["territoryReferenceYear"] == 2023
    assert payload["coverage"] == {"expectedCount": 2, "numericCount": 2, "validNoDataCount": 0, "territoryReferenceYear": 2023, "territoryGeometryReference": "istat-region-2023.pmtiles"}
    assert "campione Copernicus" not in ranking["scopeLabel"]


def test_derived_delivery_maps_each_snapshot_to_its_historical_geometry(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    rows: list[dict] = []
    coverage_entries: list[dict] = []
    geometry: dict[str, Path] = {}
    for year in range(2018, 2025):
        territories = canonical / "territories" / f"reference_year={year}"
        territories.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"territory_id": "it:region:01", "name": "Piemonte", "istat_code": "01"}]).to_parquet(territories / "region.parquet")
        path = tmp_path / f"istat-region-{year}.pmtiles"
        path.touch()
        geometry[str(year)] = path
    expected_periods = {
        "tree_cover_mean": [(year, year) for year in range(2018, 2025)],
        "forest_area_ha": [(2018, 2018), (2021, 2021), (2024, 2024)],
        "tree_cover_gain_ha": [(2018, 2021)],
    }
    assets = {"tree_cover_mean": "hrl_tree_cover_density_100m", "forest_area_ha": "hrl_forest_type", "tree_cover_gain_ha": "hrl_tree_cover_presence_change"}
    for metric, periods in expected_periods.items():
        for start, end in periods:
            rows.append({"metric_id": metric, "territory_id": "it:region:01", "territory_version_id": f"it:region:01@{territory_reference_date(end)}", "territory_level": "region", "period_start": f"{start}-01-01", "period_end": f"{end}-12-31", "value_decimal": 20.0, "unit_ucum": "%" if metric == "tree_cover_mean" else "ha", "official_status": "derived_by_stato_italia", "methodology_version": assets[metric]})
            coverage_entries.append({"assetId": assets[metric], "period": f"{start}-{end}", "territoryLevel": "region", "territoryReferenceYear": end, "territoryGeometryReference": f"istat-region-{end}.pmtiles", "expectedTerritoryIds": ["it:region:01"], "numericTerritoryIds": ["it:region:01"], "validNoDataTerritoryIds": []})
    zonal = canonical / "forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    zonal.parent.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(zonal)
    infc = canonical / "forests" / "infc.parquet"
    pd.DataFrame(columns=["metric_id", "territory_id", "territory_version_id", "territory_level", "period_start", "period_end", "value_decimal", "official_status"]).to_parquet(infc)
    forests.forest_coverage_report_path(zonal).write_text(json.dumps({"coverageMode": "national", "entries": coverage_entries}))

    generate_forests_delivery(zonal, infc, canonical, tmp_path / "delivery", "release-test", geometry, force=True)

    index = json.loads((tmp_path / "delivery" / "foreste" / "index.json").read_text())
    expected_maps = {}
    for metric, periods in expected_periods.items():
        for start, end in periods:
            logical = f"delivery/foreste/maps/{metric}/{start}-{end}/region.json"
            expected_maps[logical] = f"delivery/foreste/geometry/istat-region-{end}.pmtiles"
    assert index["mapGeometry"] == expected_maps
    assert set(index["maps"]) == set(expected_maps)
    # Having adjacent/current geometry must not satisfy missing exact 2019.
    del geometry["2019"]
    with pytest.raises(ValueError, match="lacks exact ISTAT geometry"):
        generate_forests_delivery(zonal, infc, canonical, tmp_path / "missing-geometry", "release-test", geometry, force=True)


def test_existing_raster_canonical_without_coverage_is_not_reused(tmp_path: Path) -> None:
    destination = tmp_path / "canonical" / "forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    destination.parent.mkdir(parents=True)
    pd.DataFrame({"territory_level": ["region"]}).to_parquet(destination)
    with pytest.raises(ValueError, match="Active forest canonical/coverage checksum mismatch"):
        forests.ingest_forests(tmp_path, tmp_path / "canonical", mode="raster", active_canonical=(forests.sha256_file(destination), "0" * 64))


def test_process_raster_grid_is_epsg3035_aligned_and_bounded() -> None:
    geometry = Polygon([(12, 41), (12.8, 41), (12.8, 41.7), (12, 41.7)]).wkb
    tiles = _process_tile_grid(geometry, resolution_m=100, max_pixels=256)

    assert len(tiles) > 1
    for bbox, width, height, _, _ in tiles:
        assert width <= 256 and height <= 256
        assert (bbox[2] - bbox[0]) == width * 100
        assert (bbox[3] - bbox[1]) == height * 100
        assert all(value % 100 == 0 for value in bbox)


def test_process_payload_preserves_source_band_and_explicit_nodata() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density")
    payload = _process_payload(asset, (1000, 2000, 3000, 4000), 20, 20, {"contentDateStart": "2023-01-01T00:00:00Z", "contentDateEnd": "2023-12-31T23:59:59Z"})

    assert payload["input"]["data"][0]["type"] == f"byoc-{asset['byoc_collection_id']}"
    assert payload["input"]["bounds"]["properties"]["crs"].endswith("/3035")
    assert payload["output"]["responses"][0]["format"]["type"] == "image/tiff"
    assert asset["band"] in payload["evalscript"]
    assert str(asset["process_no_data"]) in payload["evalscript"]


def test_tcpc_process_payload_uses_the_catalogued_source_interval_and_invalidates_old_request_signature() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_change")
    snapshot = {"contentDateStart": "2018-01-01T00:00:00.000000Z", "contentDateEnd": "2021-12-31T23:59:59.999999Z", "signature": "a" * 64}
    payload = _process_payload(asset, (1000, 2000, 3000, 4000), 20, 20, snapshot)

    time_range = payload["input"]["data"][0]["dataFilter"]["timeRange"]
    assert time_range == {"from": "2018-01-01T00:00:00.000000Z", "to": "2021-12-31T23:59:59.999999Z"}
    _, signature, expected = _process_request_contract(asset, (1000, 2000, 3000, 4000), 20, 20, snapshot, 2021, "01", 2018, 2021)
    _, legacy_signature, _ = _process_request_contract(asset, (1000, 2000, 3000, 4000), 20, 20, snapshot | {"contentDateEnd": "2018-01-02T00:00:00Z"}, 2021, "01", 2018, 2021)
    assert expected["process_request_sha256"] == signature
    assert signature != legacy_signature


def test_legacy_cache_reuse_is_limited_to_verified_annual_slices(tmp_path: Path) -> None:
    annual = next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_density")
    tcpc = next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_change")
    target = tmp_path / "slice.tif"
    target.write_bytes(b"verified raster")
    items = [{"Id": "tile", "Name": "CLMS_HRLVLCC_TCD_S2018_R100m_E09N27_03035_V01_R00", "ContentDate": {"Start": "2018-01-01T00:00:00Z", "End": "2018-12-31T23:59:59Z"}}]
    snapshot = {"contentDateStart": "2018-01-01T00:00:00Z", "contentDateEnd": "2018-12-31T23:59:59Z", "signature": "new" * 21 + "n", "items": items}
    _, _, expected = _process_request_contract(annual, (0, 0, 100, 100), 1, 1, snapshot, 2018, "01", 2018, 2018)
    legacy_request = {key: value for key, value in expected.items() if key not in {"territory_reference_year", "process_request_sha256", "snapshot_signature"}} | {"snapshot_signature": "old" * 21 + "o"}
    prior = {"sha256": forests.sha256_file(target), "request": legacy_request, "snapshot": {"asset_id": annual["id"], "period": [2018, 2018], "items": items}}
    assert forests._legacy_annual_slice_matches(prior, expected, snapshot, annual, target)
    assert not forests._legacy_annual_slice_matches(prior, expected, snapshot, tcpc, target)


def test_historical_snapshots_use_matching_geometry_and_are_not_compared_across_boundary_versions() -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density")
    assert territory_reference_year_for_period(asset, 2018, 2018) == 2018
    assert territory_reference_year_for_period(asset, 2021, 2021) == 2021
    tcpc = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_change")
    assert territory_reference_year_for_period(tcpc, 2018, 2021) == 2021
    coverage = [
        {"assetId": "tcd", "period": "2018-2018", "territoryLevel": "region", "territoryReferenceYear": 2018, "expectedTerritoryIds": ["it:region:01"], "numericTerritoryIds": ["it:region:01"], "validNoDataTerritoryIds": []},
        {"assetId": "tcd", "period": "2021-2021", "territoryLevel": "region", "territoryReferenceYear": 2021, "expectedTerritoryIds": ["it:region:01"], "numericTerritoryIds": ["it:region:01"], "validNoDataTerritoryIds": []},
    ]
    coverage = [item | {"territoryGeometryReference": f"istat-region-{item['territoryReferenceYear']}.pmtiles"} for item in coverage]
    table = pd.DataFrame([
        {"metric_id": "tree_cover_mean", "methodology_version": "tcd", "territory_level": "region", "period_start": "2018-01-01", "period_end": "2018-12-31", "territory_id": "it:region:01", "value_decimal": 10.0},
        {"metric_id": "tree_cover_mean", "methodology_version": "tcd", "territory_level": "region", "period_start": "2021-01-01", "period_end": "2021-12-31", "territory_id": "it:region:01", "value_decimal": 10.0},
    ])
    report = _coverage_report(table, coverage, {2018: {"01"}, 2021: {"01"}})
    comparison = report["temporalDiagnostics"][1]["comparisonWithPrevious"]
    assert comparison["territoryComparable"] is False
    assert comparison["reason"] == "territory_geometry_changed"
    assert comparison["medianAbsoluteDifference"] is None


def test_raster_development_slice_has_bounded_process_api_requests() -> None:
    # Four configured regions produce four 2048px tiles per period at 100 m.
    # 7 TCD + 3 FTY + 1 TCPC periods => 176 Process API requests, versus one
    # Statistical API request per territory and period.
    requests = 0
    for asset in (item for item in HRL["assets"] if item.get("statistical_api_enabled", True)):
        requests += len(_asset_periods(asset)) * 4 * 4
    assert requests == 176


def test_local_env_is_optional_and_never_overrides_shell_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CDSE_CLIENT_ID=local-id\nCDSE_CLIENT_SECRET='local-secret'\n", encoding="utf-8")
    monkeypatch.setenv("CDSE_CLIENT_ID", "shell-id")
    monkeypatch.delenv("CDSE_CLIENT_SECRET", raising=False)
    load_local_env(env_file)
    assert os.environ["CDSE_CLIENT_ID"] == "shell-id"
    assert os.environ["CDSE_CLIENT_SECRET"] == "local-secret"


def test_statistical_response_is_closed_after_each_territory_request(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            self.closed = True

    response = Response()
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density") | {"years": [2023]}
    territory = {"territory_id": "it:municipality:000001", "territory_version_id": "it:municipality:000001@2023-01-01", "level": "municipality", "geometry_wkb": Polygon([(12, 41), (12.1, 41), (12.1, 41.1), (12, 41.1)]).wkb}
    monkeypatch.setattr(forests, "_post_statistics", lambda *_: response)
    monkeypatch.setattr(forests, "_statistical_response", lambda *_: [{"mean": 20, "percentiles": {"25.0": 10, "50.0": 20, "75.0": 30}}])

    records = forests._statistical_records(asset, territory, 2023, 2023, {
        "contentDateStart": "2023-01-01T00:00:00Z",
        "contentDateEnd": "2023-12-31T23:59:59Z",
        "signature": "s" * 64,
    }, "fake-token", "source-hash")

    assert response.closed
    assert [record["metric_id"] for record in records] == ["tree_cover_mean", "tree_cover_p25", "tree_cover_p50", "tree_cover_p75"]


def test_statistical_api_refreshes_expired_token_once(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code
            self.headers: dict[str, str] = {}
            self.closed = False

        def close(self) -> None:
            self.closed = True

    issued = iter(["expired", "fresh"])
    monkeypatch.setattr(forests, "_cdse_token", lambda _source: next(issued))
    tokens = forests._CdseTokenProvider(HRL)
    responses = [Response(401), Response(200)]
    authorizations: list[str] = []

    def post(*_args: object, **kwargs: object) -> Response:
        authorizations.append(kwargs["headers"]["Authorization"])  # type: ignore[index]
        return responses.pop(0)

    monkeypatch.setattr(forests.requests, "post", post)

    response = forests._post_statistics({"request": "payload"}, tokens)

    assert response.status_code == 200
    assert authorizations == ["Bearer expired", "Bearer fresh"]


def test_statistical_checkpoint_reuses_only_complete_matching_records(tmp_path: Path) -> None:
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density") | {"years": [2023]}
    territory = {"territory_id": "it:municipality:000001", "territory_version_id": "it:municipality:000001@2023-01-01"}
    source_hash = "a" * 64
    snapshot = {"signature": "s" * 64}
    records = [{"territory_version_id": territory["territory_version_id"], "source_asset_sha256": source_hash, "source_snapshot_signature": snapshot["signature"], "metric_id": metric} for metric in ("tree_cover_mean", "tree_cover_p25", "tree_cover_p50", "tree_cover_p75")]

    _write_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, 2023, 2023, snapshot, source_hash, records)

    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, 2023, 2023, snapshot, source_hash, force=False) == records
    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, 2023, 2023, snapshot, "b" * 64, force=False) is None
    assert _read_statistical_checkpoint(tmp_path / "zonal_statistics.parquet", asset, territory, 2023, 2023, snapshot, source_hash, force=True) is None


def test_catalog_preflight_is_read_only_and_run_regenerates_canonical_from_v2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_path = tmp_path / "raw" / HRL["source_id"] / "catalog.json"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(json.dumps({
        "source_id": HRL["source_id"], "signature": "1" * 64,
        "products": [{"Id": "v1", "Name": "V1"}], "checked_at": "2026-01-01T00:00:00Z",
    }))
    cached = tmp_path / "canonical" / "forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    cached.parent.mkdir(parents=True)
    pd.DataFrame({
        "derived_metric_id": ["v1"], "territory_level": ["region"], "reference_year": [2023],
        "source_asset_sha256": ["1" * 64],
    }).to_parquet(cached)
    products_v2 = [{
        "Id": "v2", "Name": "V2", "ContentDate": None, "Checksum": None,
        "S3Path": None, "OriginDate": None,
    }]
    monkeypatch.setattr(forests, "_catalog_products", lambda _source: products_v2)

    remote = _check_catalog(HRL)

    assert json.loads(catalog_path.read_text())["signature"] == "1" * 64
    persisted = _persist_catalog(tmp_path, remote)
    assert persisted["changed"] is True
    monkeypatch.setattr(forests, "_cdse_token", lambda _source: "token")
    asset = next(item for item in HRL["assets"] if item["kind"] == "tree_cover_density")
    territory = {
        "territory_id": "it:region:01", "territory_version_id": "it:region:01@2023-01-01",
        "level": "region",
    }
    snapshot = {
        "contentDateStart": "2023-01-01T00:00:00Z",
        "contentDateEnd": "2023-12-31T23:59:59Z",
        "signature": "s" * 64,
    }
    monkeypatch.setattr(forests, "_statistical_jobs", lambda *_: [(asset, 2023, 2023, snapshot, territory)])
    monkeypatch.setattr(forests, "_read_statistical_checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(forests, "_write_statistical_checkpoint", lambda *_args, **_kwargs: None)

    def records(asset: dict, territory: dict, start: int, end: int, source_snapshot: dict, _token: str, source_hash: str) -> list[dict]:
        return [{
            "derived_metric_id": asset["id"], "territory_id": territory["territory_id"],
            "territory_version_id": territory["territory_version_id"], "territory_level": territory["level"],
            "reference_year": end, "period_start": f"{start}-01-01", "period_end": f"{end}-12-31",
            "methodology_version": asset["id"], "source_asset_sha256": source_hash,
            "source_snapshot_signature": source_snapshot["signature"],
        }]

    monkeypatch.setattr(forests, "_statistical_records", records)
    result = forests.ingest_forests(
        tmp_path, tmp_path / "canonical", force=False, mode="statistical-api",
    )

    regenerated = pd.read_parquet(cached)
    assert result["changed"] is True
    assert set(regenerated["source_asset_sha256"]) == {remote["signature"]}


def test_h1h_enabled_periods_and_dynamic_territory_years(monkeypatch: pytest.MonkeyPatch) -> None:
    assets = {asset["id"]: asset for asset in HRL["assets"]}
    assert assets["hrl_tree_cover_density_100m"]["years"] == list(range(2018, 2025))
    assert assets["hrl_forest_type"]["years"] == [2018, 2021, 2024]
    assert assets["hrl_tree_cover_presence_change"]["periods"] == [[2018, 2021]]
    assert assets["hrl_dominant_leaf_type"]["statistical_api_enabled"] is False
    assert forests.forest_zonal_territory_years() == frozenset(range(2018, 2025))
    monkeypatch.setitem(HRL, "assets", [
        assets["hrl_tree_cover_density_100m"] | {"years": [2019, 2019]},
        assets["hrl_tree_cover_presence_change"],
        assets["hrl_dominant_leaf_type"] | {"years": [2099]},
    ])
    assert forests.forest_zonal_territory_years() == {2019, 2021}


@pytest.fixture
def forest_incremental_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Synthetic retained requests and old published inventory; no network/raster jobs."""
    import copy
    full_assets = copy.deepcopy(HRL["assets"])
    old_assets = [asset | {"years": [2018, 2021, 2023] if asset["kind"] == "tree_cover_density" else [2018, 2021]}
                  if asset["kind"] in {"tree_cover_density", "forest_type"} else asset for asset in full_assets]
    root = tmp_path / "data"
    canonical = root / "canonical"
    destination = canonical / "forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}" / "zonal_statistics.parquet"
    coverage = forests.forest_coverage_report_path(destination)
    calls = []
    geometry = Polygon([(12, 41), (12.1, 41), (12.1, 41.1), (12, 41.1)]).wkb

    def territories(_root, year):
        return pd.DataFrame([
            {"territory_id": f"it:{level}:{code}", "territory_version_id": f"it:{level}:{code}@{territory_reference_date(year)}",
             "level": level, "istat_code": code, "region_istat_code": "01", "geometry_wkb": geometry}
            for level, code in (("region", "01"), ("province", "001"), ("municipality", "001001"), ("municipality", "001002"))
        ])

    monkeypatch.setenv("FORESTS_RAW_RETENTION", "retain")
    monkeypatch.setenv(HRL["coverage_mode_environment"], "national")
    monkeypatch.setattr(forests, "_slice_territories_with_region_code", territories)
    monkeypatch.setattr(forests, "_expected_region_codes", lambda *_: {"01"})
    monkeypatch.setattr(forests, "_process_tile_grid", lambda *_: [((0, 0, 100, 100), 1, 1, 0, 0)])
    monkeypatch.setattr(forests.requests, "get", lambda *_a, **_k: pytest.fail("Live HTTP forbidden"))
    monkeypatch.setattr(forests.requests, "post", lambda *_a, **_k: pytest.fail("Live HTTP forbidden"))

    def process(asset, group, population):
        calls.append(f"{asset['id']}:{group['start_year']}-{group['end_year']}")
        records = []
        for territory in population.to_dict("records"):
            if territory["istat_code"] == "001002":
                continue
            for index, metric in enumerate(sorted(forests._FOREST_METRICS[asset["kind"]])):
                row = forests._record(asset | {"source_id": HRL["source_id"]}, "retained", group["source_hash"], territory,
                                      metric, float(group["end_year"] - 2000 + index), group["start_year"], group["end_year"])
                records.append(row | {"source_snapshot_signature": group["snapshot_signature"]})
        return records, ["it:municipality:001002"]
    monkeypatch.setattr(forests, "_process_raster_records", process)

    def retained(assets, changed=None):
        products = []
        for asset in assets:
            if not asset.get("statistical_api_enabled", True):
                continue
            for start, end in _asset_periods(asset):
                key = f"{asset['id']}:{start}-{end}"
                products.append({"asset_id": asset["id"], "period": [start, end], "items": [{
                    "Id": key + ("-updated" if key == changed else ""), "Name": key,
                    "ContentDate": {"Start": f"{start}-01-01T00:00:00Z", "End": f"{end}-12-31T23:59:59Z"},
                }]})
        catalog = {"products": products}
        path = root / "raw" / HRL["source_id"] / "catalog.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(catalog))
        for asset in assets:
            if not asset.get("statistical_api_enabled", True):
                continue
            for start, end in _asset_periods(asset):
                snapshot = _catalog_snapshot(catalog, asset, start, end)
                year = territory_reference_year_for_period(asset, start, end)
                path = forests._process_slice_path(root, asset, start, end, "01", 0, 0)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"synthetic-{asset['id']}-{start}-{end}".encode())
                _, request_hash, request = _process_request_contract(asset, (0, 0, 100, 100), 1, 1, snapshot, year, "01", start, end)
                digest = forests.sha256_file(path)
                path.with_suffix(path.suffix + ".metadata.json").write_text(json.dumps({"sha256": digest, "request": request, "processRequestSha256": request_hash}))
                entries = [{"path": path.name, "sha256": digest, "bytes": path.stat().st_size, "request": request}]
                payload = {"asset_id": asset["id"], "period": [start, end], "territory_reference_year": year,
                           "territory_geometry_reference": f"istat-region-{year}.pmtiles", "region_istat_code": "01",
                           "snapshot_signature": snapshot["signature"], "entries": entries}
                signature = forests.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                manifest = {"schemaVersion": 2, "source_id": HRL["source_id"], "asset_id": asset["id"], "period": [start, end],
                            "territoryReferenceYear": year, "territoryGeometryReference": f"istat-region-{year}.pmtiles",
                            "region_istat_code": "01", "source_signature": signature, "snapshot_signature": snapshot["signature"], "entries": entries}
                (path.parent / "slice-manifest.json").write_text(json.dumps(manifest))

    monkeypatch.setitem(HRL, "assets", old_assets)
    retained(old_assets)
    forests.ingest_forests(root, canonical, mode="raster")
    # Match the existing v3 production sidecar, without H1H's additive evidence.
    report = json.loads(coverage.read_text())
    report.pop("assetPeriodEvidence")
    coverage.write_text(json.dumps(report))
    monkeypatch.setitem(HRL, "assets", full_assets)
    retained(full_assets)
    calls.clear()
    return root, canonical, destination, coverage, calls, lambda changed=None: retained(full_assets, changed)


def test_forest_expansion_reuses_six_periods_processes_five_then_is_deterministic(forest_incremental_state) -> None:
    root, canonical, destination, coverage, calls, _ = forest_incremental_state
    active = (forests.sha256_file(destination), forests.sha256_file(coverage))
    report = forests.ingest_forests(root, canonical, mode="raster", active_canonical=active)
    expected_new = {f"hrl_tree_cover_density_100m:{year}-{year}" for year in (2019, 2020, 2022, 2024)} | {"hrl_forest_type:2024-2024"}
    expected_old = {f"hrl_tree_cover_density_100m:{year}-{year}" for year in (2018, 2021, 2023)} | {
        "hrl_forest_type:2018-2018", "hrl_forest_type:2021-2021", "hrl_tree_cover_presence_change:2018-2021",
    }
    assert set(calls) == set(report["asset_periods_processed"]) == expected_new
    assert set(report["asset_periods_reused"]) == expected_old
    assert report["changed"] is True
    final = pd.read_parquet(destination)
    assert not final.duplicated(["methodology_version", "period_start", "period_end", "territory_id", "metric_id"]).any()
    assert set(final.methodology_version) == {"hrl_tree_cover_density_100m", "hrl_forest_type", "hrl_tree_cover_presence_change"}
    sidecar = json.loads(coverage.read_text())
    assert len(sidecar["assetPeriodEvidence"]) == 11
    assert sum(entry["validNoDataCount"] for entry in sidecar["entries"]) == 11
    active = (forests.sha256_file(destination), forests.sha256_file(coverage))
    calls.clear()
    repeated = forests.ingest_forests(root, canonical, mode="raster", active_canonical=active)
    assert calls == repeated["asset_periods_processed"] == []
    assert len(repeated["asset_periods_reused"]) == 11
    assert repeated["changed"] is False
    assert (forests.sha256_file(destination), forests.sha256_file(coverage)) == active


@pytest.mark.parametrize("stale", ["snapshot", "metric", "duplicate", "version", "nodata", "source", "boundary"])
def test_forest_rebuilds_only_incompatible_existing_period(forest_incremental_state, stale) -> None:
    root, canonical, destination, coverage, calls, retained = forest_incremental_state
    forests.ingest_forests(root, canonical, mode="raster", active_canonical=(forests.sha256_file(destination), forests.sha256_file(coverage)))
    target = "hrl_tree_cover_density_100m:2021-2021"
    table = pd.read_parquet(destination)
    match = (table.methodology_version == "hrl_tree_cover_density_100m") & (table.period_start == "2021-01-01")
    if stale == "snapshot":
        retained(target)
    elif stale == "metric":
        table = table.drop(table[match].index[0])
    elif stale == "duplicate":
        table = pd.concat([table, table[match].iloc[:1]], ignore_index=True)
    elif stale == "version":
        table.loc[match, "territory_version_id"] = "it:region:01@2021-01-01"
    elif stale == "source":
        table.loc[match, "source_asset_sha256"] = "0" * 64
    elif stale == "nodata":
        report = json.loads(coverage.read_text())
        next(entry for entry in report["entries"] if entry["assetId"] == "hrl_tree_cover_density_100m" and entry["period"] == "2021-2021" and entry["territoryLevel"] == "municipality")["validNoDataTerritoryIds"] = []
        coverage.write_text(json.dumps(report))
    table.to_parquet(destination, index=False, compression="zstd")
    calls.clear()
    report = forests.ingest_forests(root, canonical, mode="raster", active_canonical=(forests.sha256_file(destination), forests.sha256_file(coverage)), changed_boundary_years={2019} if stale == "boundary" else None)
    assert calls == report["asset_periods_processed"] == (["hrl_tree_cover_density_100m:2019-2019"] if stale == "boundary" else [target])
    assert len(report["asset_periods_reused"]) == 10


def test_forest_does_not_reuse_unpublished_local_canonical(forest_incremental_state) -> None:
    root, canonical, _, _, calls, _ = forest_incremental_state
    report = forests.ingest_forests(root, canonical, mode="raster")
    assert len(calls) == len(report["asset_periods_processed"]) == 11
    assert report["asset_periods_reused"] == []


@pytest.mark.parametrize("invalid", ["request", "snapshot", "checksum", "missing_period"])
def test_forest_rejects_unverified_retained_inputs_before_replacing_canonical(forest_incremental_state, invalid) -> None:
    root, canonical, destination, coverage, _, _ = forest_incremental_state
    active = (forests.sha256_file(destination), forests.sha256_file(coverage))
    asset = next(asset for asset in HRL["assets"] if asset["kind"] == "tree_cover_density")
    path = forests._process_slice_path(root, asset, 2021, 2021, "01", 0, 0)
    if invalid == "request":
        sidecar = path.with_suffix(path.suffix + ".metadata.json")
        metadata = json.loads(sidecar.read_text())
        metadata["request"]["territory_reference_year"] = 2025
        sidecar.write_text(json.dumps(metadata))
    elif invalid == "snapshot":
        manifest_path = path.parent / "slice-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["snapshot_signature"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
    elif invalid == "checksum":
        path.write_bytes(b"corrupt raster")
    else:
        (path.parent / "slice-manifest.json").unlink()
    with pytest.raises(ValueError, match="CDSE Process API"):
        forests.ingest_forests(root, canonical, mode="raster", active_canonical=active)
    assert (forests.sha256_file(destination), forests.sha256_file(coverage)) == active
