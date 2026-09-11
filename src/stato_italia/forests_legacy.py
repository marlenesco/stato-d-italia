"""CLMS legacy ZIP acquisition and validation; no CDSE or implicit auth exchange."""
from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
import zipfile
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import jwt
import pandas as pd
import rasterio
import requests

from .common import json_dump, sha256_file
from .registry import load_source

LEGACY = load_source("copernicus-forests-legacy")


def legacy_enabled() -> bool:
    value = os.getenv(LEGACY["enabled_environment"], "0")
    if value not in {"0", "1"}:
        raise ValueError("FOREST_LEGACY_ENABLED must be 0 or 1")
    return value == "1"


def environment_token() -> str:
    """Operational bridge: the caller provisions/refreshes the CLMS bearer."""
    token = os.getenv(LEGACY["token_environment"], "")
    if not token or any(c.isspace() for c in token):
        raise ValueError("CLMS bearer unavailable; configure a token provider")
    return token


class ClmsTokenProvider:
    """CLMS service-key JWT exchange; credentials and bearer stay in memory."""

    def __init__(self, client, *, clock=time.time, monotonic=time.monotonic):
        self.client = client
        self.clock = clock
        self.monotonic = monotonic
        self._token = None
        self._expires = 0.0

    def invalidate(self) -> bool:
        self._token = None
        return not bool(os.getenv(LEGACY["token_environment"]))

    def __call__(self) -> str:
        if os.getenv(LEGACY["token_environment"]):
            return environment_token()
        if self._token is not None and self.monotonic() < self._expires:
            return self._token
        response = None
        try:
            key = json.loads(os.environ["CLMS_SERVICE_KEY"])
            if (not isinstance(key, dict)
                    or any(not isinstance(key.get(field), str) or not key[field] for field in
                           ("client_id", "user_id", "private_key", "token_uri"))
                    or key["token_uri"] != "https://land.copernicus.eu/@@oauth2-token"):
                raise ValueError()
            issued = int(self.clock())
            grant = jwt.encode({"iss": key["client_id"], "sub": key["user_id"], "aud": key["token_uri"],
                                "iat": issued, "exp": issued + 3600}, key["private_key"], algorithm="RS256")
            started = self.monotonic()
            response = self.client.request(
                "POST", key["token_uri"], headers={"Accept": "application/json"},
                data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": grant},
                timeout=30, allow_redirects=False, verify=True,
            )
            if response.status_code != 200:
                raise ValueError()
            payload = response.json()
            token, lifetime = payload["access_token"], payload["expires_in"]
            if (payload.get("token_type") != "Bearer" or not isinstance(token, str) or not token
                    or any(c.isspace() for c in token) or type(lifetime) is not int or lifetime <= 0):
                raise ValueError()
            expires = started + lifetime - min(30, lifetime / 10)
            if self.monotonic() >= expires:
                raise ValueError()
            self._token, self._expires = token, expires
            return token
        except Exception:
            raise ValueError("CLMS service-key authentication unavailable or rejected") from None
        finally:
            if response is not None:
                response.close()


def product_contract(asset: dict, year: int) -> dict:
    if year not in (2012, 2015) or year not in asset["years"]:
        raise ValueError("Unsupported legacy Forest period")
    product = asset["products"][year]
    return {
        "source_id": LEGACY["source_id"], "asset_id": asset["id"],
        "methodology_family": LEGACY["methodology_family"], "reference_year": year,
        "territory_reference_year": year, "native_resolution_m": asset["native_resolution_m"],
        "resolution_m": asset["resolution_m"], "crs": LEGACY["crs"],
        "product": product, "series_break_to_modern": LEGACY["series_break_to_modern"],
    }


def raw_path(root: Path, asset: dict, year: int) -> Path:
    return root / "raw" / LEGACY["source_id"] / asset["id"] / str(year) / "product.zip"


def contract_signature(asset: dict, year: int) -> str:
    payload = json.dumps(product_contract(asset, year), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode()).hexdigest()


def expected_legacy_assets() -> dict[str, tuple[dict, int]]:
    """Exact asset paths relative to the raw root, as stored in source-state."""
    return {
        raw_path(Path(), asset, year).relative_to("raw").as_posix(): (asset, year)
        for asset in LEGACY["assets"] for year in asset["years"]
    }


def legacy_state_complete(state: dict | None) -> bool:
    entries = [entry for entry in (state or {}).get("sources", [])
               if entry.get("source_id") == LEGACY["source_id"] and entry.get("kind") != "catalog"]
    paths = [entry.get("asset_path") for entry in entries]
    return all(isinstance(path, str) for path in paths) and len(paths) == len(set(paths)) and set(paths) == set(expected_legacy_assets())


def _identifier(value: object) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= 256 and not any(c.isspace() for c in value)


def _json_request(client, method: str, url: str, token_provider, *, expected_status: int, request_timeout=30, **kwargs):
    response = None
    try:
        for attempt in range(2):
            token = token_provider()
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ValueError()
            response = client.request(method, url, headers={"Authorization": f"Bearer {token}"},
                                      timeout=request_timeout, allow_redirects=False, verify=True, **kwargs)
            if response.status_code == expected_status:
                return response.json()
            if response.status_code == 401 and attempt == 0 and isinstance(token_provider, ClmsTokenProvider) and token_provider.invalidate():
                response.close()
                response = None
                continue
            raise ValueError()
    except Exception:
        raise ValueError("CLMS authenticated request failed or returned invalid JSON") from None
    finally:
        if response is not None:
            response.close()


def request_download_url(asset: dict, year: int, *, client, token_provider=environment_token,
                         timeout: float = 600, max_polls: int = 60,
                         clock=time.monotonic, sleep=time.sleep) -> tuple[str, str]:
    if not math.isfinite(timeout) or timeout <= 0 or max_polls <= 0:
        raise ValueError("Invalid CLMS polling limits")
    product = product_contract(asset, year)["product"]
    payload = _json_request(client, "POST", LEGACY["request_url"], token_provider,
                            expected_status=201,
                            json={"Datasets": [{key: product[key] for key in ("DatasetID", "FileID")}]})
    # A single submitted dataset must resolve to exactly one task.
    if (not isinstance(payload, dict) or payload.get("ErrorTaskIds") != []
            or not isinstance(payload.get("TaskIds"), list) or len(payload["TaskIds"]) != 1
            or not isinstance(payload["TaskIds"][0], dict)
            or not _identifier(payload["TaskIds"][0].get("TaskID"))):
        raise ValueError("CLMS submission lacks one unambiguous TaskID")
    task_id = payload["TaskIds"][0]["TaskID"]
    deadline = clock() + timeout
    for attempt in range(max_polls):
        if clock() >= deadline:
            break
        payload = _json_request(client, "GET", LEGACY["search_url"], token_provider,
                                expected_status=200,
                                params={"status": "Finished_ok"}, request_timeout=min(30, max(0.001, deadline - clock())))
        if clock() >= deadline:
            break
        if not isinstance(payload, dict):
            raise ValueError("CLMS completed-task response is malformed")
        if task_id in payload:
            item = payload[task_id]
            if not isinstance(item, dict) or item.get("Status") != "Finished_ok":
                raise ValueError("CLMS target task is malformed or not successfully completed")
            url = item.get("DownloadURL")
            try:
                parsed = urlsplit(url) if isinstance(url, str) and not any(c.isspace() for c in url) else None
                valid = parsed and parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("CLMS completed task lacks a valid HTTPS download URL")
            return task_id, url
        remaining = deadline - clock()
        if remaining > 0 and attempt + 1 < max_polls:
            sleep(min(2 ** min(attempt, 5), remaining))
    raise TimeoutError("CLMS completion polling timed out")


def validate_raster(path: Path, asset: dict) -> None:
    """Validate every source cell, including cells masked by source metadata."""
    try:
        with rasterio.open(path) as dataset:
            resolution = asset["resolution_m"]
            if (dataset.crs != rasterio.crs.CRS.from_epsg(3035) or dataset.count != 1
                    or dataset.transform.b != 0 or dataset.transform.d != 0
                    or not math.isclose(dataset.transform.a, resolution, abs_tol=1e-8, rel_tol=0)
                    or not math.isclose(dataset.transform.e, -resolution, abs_tol=1e-8, rel_tol=0)
                    or dataset.nodata not in (None, 254, 255)
                    or dataset.scales != (1.0,) or dataset.offsets != (0.0,)
                    or not np.issubdtype(np.dtype(dataset.dtypes[0]), np.integer)):
                raise ValueError()
            allowed = list(range(101)) + [254, 255] if asset["kind"] == "tree_cover_density" else [0, 1, 2, 3, 254, 255]
            for _, window in dataset.block_windows(1):
                if not np.isin(dataset.read(1, window=window, masked=False), allowed).all():
                    raise ValueError()
    except Exception:
        raise ValueError("Legacy Forest raster violates CRS, resolution, band, NoData or value contract") from None


def extract_validated_raster(archive: Path, destination: Path, asset: dict) -> str:
    try:
        with zipfile.ZipFile(archive) as bundle:
            rasters = [info for info in bundle.infolist() if not info.is_dir() and Path(info.filename).suffix.lower() in {".tif", ".tiff"}]
            if len(rasters) != 1:
                raise ValueError()
            # Fixed destination: ZIP paths are never extracted into the filesystem.
            with bundle.open(rasters[0]) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        validate_raster(destination, asset)
        return sha256_file(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise ValueError("Legacy Forest ZIP/raster is invalid or ambiguous") from None


def retained_product(root: Path, asset: dict, year: int) -> dict:
    path = raw_path(root, asset, year)
    metadata_path = path.with_suffix(".zip.metadata.json")
    try:
        metadata = json.loads(metadata_path.read_text())
        if (metadata["contract"] != product_contract(asset, year)
                or metadata.get("source_signature") != contract_signature(asset, year)
                or metadata["sha256"] != sha256_file(path)
                or metadata["bytes"] != path.stat().st_size):
            raise ValueError()
    except Exception:
        raise ValueError("Legacy Forest retained ZIP provenance is missing or incompatible") from None
    return {"local_path": str(path), "metadata_path": str(metadata_path), "changed": False, **metadata}


def acquire_product(root: Path, asset: dict, year: int, *, offline: bool = False,
                    token_provider=None, client=None) -> dict:
    path = raw_path(root, asset, year)
    if path.exists():
        return retained_product(root, asset, year)
    if offline:
        raise FileNotFoundError("Legacy Forest ZIP unavailable offline")
    owned_client = client is None
    if owned_client:
        client = requests.Session()
        client.trust_env = False
    response = None
    temporary = None
    try:
        task_id, url = request_download_url(asset, year, client=client, token_provider=token_provider or ClmsTokenProvider(client))
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as output:
            temporary = Path(output.name)
            # A signed DownloadURL is sufficient; never forward the CLMS bearer.
            response = client.request("GET", url, timeout=60, stream=True, allow_redirects=False)
            if response.status_code != 200:
                raise ValueError()
            digest = sha256()
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
        with tempfile.TemporaryDirectory() as directory:
            raster_hash = extract_validated_raster(temporary, Path(directory) / "raster.tif", asset)
        metadata = {"source_id": LEGACY["source_id"], "sha256": digest.hexdigest(),
                    "source_signature": contract_signature(asset, year),
                    "bytes": temporary.stat().st_size, "contract": product_contract(asset, year),
                    "raster_sha256": raster_hash, "TaskID": task_id,
                    "dataset_version": asset["products"][year]["version"], "period": [year, year],
                    "resolved_url": LEGACY["request_url"]}
        temporary.rename(path)
        json_dump(path.with_suffix(".zip.metadata.json"), metadata)
        return retained_product(root, asset, year) | {"changed": True}
    except Exception:
        raise ValueError("CLMS legacy acquisition failed; no credentials or download URL retained") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if response is not None:
            response.close()
        if owned_client:
            client.close()


def fetch_legacy_forests(root: Path, *, offline: bool = False) -> list[dict]:
    return [acquire_product(root, asset, year, offline=offline)
            for asset in LEGACY["assets"] for year in asset["years"]]


def validate_bootstrap_candidate(root: Path, source_state: dict, modern_baseline: pd.DataFrame) -> dict:
    """Read-only evidence gate before a candidate can be declared validated."""
    from . import forests
    from .territories import territory_reference_date

    if not legacy_state_complete(source_state):
        raise ValueError("Legacy bootstrap requires exactly four persisted raw entries")
    zonal = root / "canonical/forests" / f"algorithm_version={forests.ZONAL_ALGORITHM_VERSION}/zonal_statistics.parquet"
    table = pd.read_parquet(zonal)
    modern = table[table.dataset_id == forests.HRL["source_id"]]
    baseline = modern_baseline[modern_baseline.dataset_id == forests.HRL["source_id"]]
    expected_modern = {(asset["id"], start, end) for asset in forests.HRL["assets"]
                       if asset.get("statistical_api_enabled", True) for start, end in forests._asset_periods(asset)}
    actual_modern = set(zip(modern.methodology_version, modern.period_start.str[:4].astype(int), modern.period_end.str[:4].astype(int)))
    if actual_modern != expected_modern or baseline.empty:
        raise ValueError("Legacy bootstrap lacks the complete active modern Forest baseline")
    try:
        pd.testing.assert_frame_equal(
            baseline.sort_values("derived_metric_id").reset_index(drop=True),
            modern[baseline.columns].sort_values("derived_metric_id").reset_index(drop=True), check_dtype=False,
        )
    except AssertionError:
        raise ValueError("Legacy bootstrap changed active modern Forest rows") from None
    coverage = json.loads(forests.forest_coverage_report_path(zonal).read_text())
    if coverage.get("coverageMode") != "national":
        raise ValueError("Legacy bootstrap requires national coverage")
    index = json.loads((root / "delivery/foreste/index.json").read_text())
    states = {entry["asset_path"]: entry for entry in source_state["sources"] if entry["source_id"] == LEGACY["source_id"]}
    legacy_rows = table[table.dataset_id == LEGACY["source_id"]]
    expected_periods = {(asset["id"], year) for asset, year in expected_legacy_assets().values()}
    if set(zip(legacy_rows.methodology_version, legacy_rows.reference_year)) != expected_periods:
        raise ValueError("Legacy bootstrap canonical lacks the four configured asset-periods")
    products, counts, map_count = [], [], 0
    populations = {year: forests._slice_territories(root / "canonical", year)
                   for year in {year for _, year in expected_legacy_assets().values()}}
    for path, (asset, year) in expected_legacy_assets().items():
        metadata = retained_product(root, asset, year)
        if any(states[path].get(key) != metadata[key] for key in ("sha256", "bytes", "source_signature")):
            raise ValueError("Legacy bootstrap source-state differs from retained ZIP provenance")
        rows = legacy_rows[(legacy_rows.methodology_version == asset["id"]) & (legacy_rows.reference_year == year)]
        contract = product_contract(asset, year)
        if (set(rows.source_asset_sha256) != {metadata["sha256"]}
                or set(rows.methodology_family) != {LEGACY["methodology_family"]}
                or set(rows.native_resolution_m) != {asset["native_resolution_m"]}
                or set(rows.input_resolution_m) != {asset["resolution_m"]}
                or not rows.territory_version_id.str.endswith("@" + territory_reference_date(year)).all()
                or set(rows.period_start) != {f"{year}-01-01"} or set(rows.period_end) != {f"{year}-12-31"}
                or any(json.loads(value) != contract for value in rows.source_product_json)):
            raise ValueError("Legacy bootstrap canonical source or exact territory contract differs")
        period = f"{year}-{year}"
        for level in forests.MAPPABLE_LEVELS:
            expected, numeric, nodata = forests._coverage_state(coverage["entries"], asset["id"], period, level)
            if (forests._coverage_reference_year(coverage["entries"], asset["id"], period, level) != year
                    or forests._coverage_geometry_reference(coverage["entries"], asset["id"], period, level) != f"istat-{level}-{year}.pmtiles"):
                raise ValueError("Legacy bootstrap coverage has the wrong geometry reference")
            population = populations[year]
            if expected != set(population.loc[population.level == level, "territory_id"]):
                raise ValueError("Legacy bootstrap coverage differs from the exact ISTAT population")
            level_rows = rows[rows.territory_level == level]
            for metric in forests._FOREST_METRICS[asset["kind"]]:
                metric_rows = level_rows[level_rows.metric_id == metric]
                if set(metric_rows.territory_id) != numeric or metric_rows.territory_id.duplicated().any():
                    raise ValueError("Legacy bootstrap numeric coverage differs from canonical rows")
                if numeric:
                    logical = f"delivery/foreste/maps/{metric}/{period}/{level}.json"
                    if logical not in index["maps"]:
                        raise ValueError("Legacy bootstrap delivery map missing")
                    payload = json.loads((root / logical).read_text())
                    if payload.get("sourceContract") != contract or payload.get("territoryReferenceYear") != year:
                        raise ValueError("Legacy bootstrap delivery lost its source contract")
                    map_count += 1
                counts.append({"asset": asset["id"], "year": year, "level": level, "metric": metric, "rows": len(metric_rows)})
        products.append({"asset": asset["id"], "year": year, "zipBytes": metadata["bytes"],
                         "sha256": metadata["sha256"], "sourceSignature": metadata["source_signature"], "rows": len(rows)})
    for snapshot in coverage.get("snapshotDiagnostics", []):
        previous = snapshot.get("comparisonWithPrevious", {}).get("period")
        if previous and int(previous[:4]) <= 2015 < int(snapshot["period"][:4]):
            raise ValueError("Legacy bootstrap must not compare across the 2015 to 2018 break")
    return {"assets": products, "legacyRows": len(legacy_rows), "rowsByAssetYearLevelMetric": counts,
            "coverage": [{key: entry[key] for key in ("assetId", "period", "territoryLevel", "expectedCount", "numericCount", "validNoDataCount")}
                         for entry in coverage["entries"] if entry["assetId"] in {a["id"] for a in LEGACY["assets"]}],
            "legacyDeliveryMaps": map_count, "modernRowsUnchanged": len(modern),
            "seriesBreakToModern": LEGACY["series_break_to_modern"]}


def legacy_zonal_records(root: Path, canonical_root: Path) -> tuple[list[dict], list[dict], dict[int, set[str]]]:
    """Validate ZIPs, then reuse the Forest zonal engine on exact ISTAT populations."""
    from . import forests
    from .territories import territory_reference_date

    records, coverage, regions_by_year = [], [], {}
    for asset in LEGACY["assets"]:
        for year in asset["years"]:
            metadata = retained_product(root, asset, year)
            territories = forests._slice_territories_with_region_code(canonical_root, year)
            if not territories["territory_version_id"].str.endswith("@" + territory_reference_date(year)).all():
                raise ValueError("Legacy Forest requires the exact ISTAT territory version")
            regions_by_year[year] = forests._expected_region_codes(canonical_root, year)
            contract = product_contract(asset, year)
            signature = sha256(json.dumps({"contract": contract, "sha256": metadata["sha256"]}, sort_keys=True).encode()).hexdigest()
            archive = Path(metadata["local_path"])
            with tempfile.TemporaryDirectory() as directory:
                raster = Path(directory) / "raster.tif"
                if extract_validated_raster(archive, raster, asset) != metadata["raster_sha256"]:
                    raise ValueError("Legacy Forest extracted raster checksum mismatch")
                for region in sorted(regions_by_year[year]):
                    group = {"region_istat_code": region, "paths": [raster], "manifest_path": archive,
                             "source_hash": metadata["sha256"], "snapshot_signature": signature,
                             "start_year": year, "end_year": year}
                    rows, nodata = forests._process_raster_records(asset | {"source_id": LEGACY["source_id"]}, group, territories)
                    for row in rows:
                        row.update({"methodology_family": LEGACY["methodology_family"],
                                    "native_resolution_m": asset["native_resolution_m"],
                                    "input_resolution_m": asset["resolution_m"],
                                    "source_product_json": json.dumps(contract, sort_keys=True),
                                    "derived_metric_id": forests.stable_id(forests.ZONAL_ALGORITHM_VERSION, signature,
                                        row["territory_version_id"], row["metric_id"], year, year)})
                    records.extend(rows)
                    subset = territories[territories["region_istat_code"] == region]
                    for level in forests.MAPPABLE_LEVELS:
                        expected = set(subset.loc[subset.level == level, "territory_id"])
                        numeric = {row["territory_id"] for row in rows if row["territory_level"] == level}
                        coverage.append({"assetId": asset["id"], "period": f"{year}-{year}",
                            "territoryLevel": level, "territoryReferenceYear": year,
                            "territoryGeometryReference": f"istat-{level}-{year}.pmtiles",
                            "expectedTerritoryIds": sorted(expected), "numericTerritoryIds": sorted(numeric),
                            "validNoDataTerritoryIds": sorted(expected & set(nodata))})
    return records, coverage, regions_by_year
