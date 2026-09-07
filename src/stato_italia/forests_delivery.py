from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .common import sha256_file
from .forests import INFC, ZONAL_ALGORITHM_VERSION, forest_coverage_report_path
from .registry import load_source

DELIVERY_ALGORITHM_VERSION = "forests-delivery-v8"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")


def _ranking_scope(source_kind: str, level: str, coverage: dict | None = None) -> str:
    if source_kind == "derived":
        if not coverage:
            raise ValueError("Derived Forest ranking lacks declared coverage")
        return (
            "Confronto nazionale tra i territori con valore raster pubblicato: "
            f"{coverage['numericCount']} numerici, {coverage['validNoDataCount']} NoData validi, "
            f"su {coverage['expectedCount']} attesi."
        )
    return "Confronto fra le Regioni per cui INFC pubblica la statistica ufficiale."


def _ranking_rows(rows: pd.DataFrame, territory_root: Path, reference_year: int, level: str) -> list[dict]:
    territories = pd.read_parquet(territory_root / "territories" / f"reference_year={reference_year}" / f"{level}.parquet")
    lookup = territories.set_index("territory_id")[["name", "istat_code"]].to_dict("index")
    ranked = rows.sort_values(["value_decimal", "territory_id"], ascending=[False, True]).reset_index(drop=True)
    denominator = max(len(ranked) - 1, 1)
    result: list[dict] = []
    for position, row in enumerate(ranked.itertuples(), start=1):
        territory = lookup.get(row.territory_id)
        if territory is None:
            raise ValueError(f"Forest ranking territory absent from ISTAT reference: {row.territory_id}")
        result.append({"territoryId": row.territory_id, "name": territory["name"], "istatCode": territory["istat_code"], "value": float(row.value_decimal), "rank": position, "percentile": round((len(ranked) - position) / denominator * 100, 1) if len(ranked) > 1 else None})
    return result


def _coverage_for_map(report: dict, asset_id: str, period: str, level: str, reference_year: int) -> dict:
    geometry_reference = f"istat-{level}-{reference_year}.pmtiles"
    entries = [item for item in report.get("entries", []) if item.get("assetId") == asset_id and item.get("period") == period and item.get("territoryLevel") == level and item.get("territoryReferenceYear") == reference_year and item.get("territoryGeometryReference") == geometry_reference]
    if not entries:
        raise ValueError(f"Forest delivery lacks coverage for {asset_id}/{period}/{level}/{reference_year}")
    numeric = set().union(*(set(item["numericTerritoryIds"]) for item in entries))
    nodata = set().union(*(set(item["validNoDataTerritoryIds"]) for item in entries))
    expected = set().union(*(set(item["expectedTerritoryIds"]) for item in entries))
    if numeric & nodata or numeric | nodata != expected:
        raise ValueError(f"Forest delivery has incomplete coverage for {asset_id}/{period}/{level}/{reference_year}")
    return {"expectedCount": len(expected), "numericCount": len(numeric), "validNoDataCount": len(nodata), "territoryReferenceYear": reference_year, "territoryGeometryReference": geometry_reference}


def generate_forests_delivery(zonal_path: Path | None, infc_path: Path, territory_root: Path, destination: Path, release_id: str, geometry: dict[str, Path], force: bool = False, coverage_path: Path | None = None) -> dict:
    index_path = destination / "foreste" / "index.json"
    resolved_coverage_path = coverage_path or (forest_coverage_report_path(zonal_path) if zonal_path else None)
    canonical_signature = {
        "zonal": sha256_file(zonal_path) if zonal_path and zonal_path.exists() else None,
        "infc": sha256_file(infc_path),
        "coverage": sha256_file(resolved_coverage_path) if resolved_coverage_path and resolved_coverage_path.exists() else None,
    }
    if index_path.exists() and not force and (prior := json.loads(index_path.read_text())).get("algorithmVersion") == DELIVERY_ALGORITHM_VERSION and prior.get("canonicalSignature") == canonical_signature:
        files = sorted((destination / "foreste").rglob("*.json"))
        return {"changed": False, "files": files, "bytes": sum(path.stat().st_size for path in files)}
    for generated in (destination / "foreste").rglob("*.json"):
        generated.unlink()
    zonal = pd.read_parquet(zonal_path) if zonal_path and zonal_path.exists() else pd.DataFrame()
    coverage_report = None
    if not zonal.empty:
        if not resolved_coverage_path or not resolved_coverage_path.exists():
            raise ValueError("Derived Forest delivery requires a verified coverage report")
        coverage_report = json.loads(resolved_coverage_path.read_text())
        if coverage_report.get("coverageMode") != "national":
            raise ValueError("Development-slice Forest coverage cannot be promoted to delivery")
    infc = pd.read_parquet(infc_path)
    required = {"metric_id", "territory_id", "territory_version_id", "territory_level", "period_start", "period_end", "value_decimal", "official_status"}
    if required - set(infc.columns) or (not zonal.empty and required - set(zonal.columns)): raise ValueError("Forest canonical contract missing delivery fields")
    root = destination / "foreste"
    _write(root / "provenance.json", {
        "schemaVersion": 1, "releaseId": release_id, "theme": "foreste",
        "datasets": [load_source("copernicus-forests"), load_source("copernicus-corine-forests"), INFC],
        "officialVsDerived": {
            "official_observation": "Statistiche INFC2015 ufficiali pubblicate per Italia e Regioni.",
            "derived_metric": "Elaborazioni Stato d’Italia: statistiche zonali su raster Copernicus/CLC e poligoni ISTAT della data di riferimento.",
        },
        "methodology": "CORINE e HRL restano serie e metriche separate. ‘tree_cover_loss’ significa perdita di copertura arborea, non deforestazione.",
        "algorithmVersion": ZONAL_ALGORITHM_VERSION,
    })
    maps: list[str] = []
    rankings: list[str] = []
    map_geometry: dict[str, str] = {}
    for source_kind, table in (("derived", zonal), ("official", infc)):
        if table.empty: continue
        for (metric, start, end, level), rows in table[table["territory_level"].isin(("municipality", "province", "region"))].groupby(["metric_id", "period_start", "period_end", "territory_level"], sort=True):
            if rows.duplicated(["territory_id"]).any(): raise ValueError(f"Forest delivery duplicate territory metric={metric} period={start}/{end} level={level}")
            reference_dates = sorted(rows["territory_version_id"].str.rsplit("@", n=1).str[-1].unique().tolist())
            if len(reference_dates) != 1: raise ValueError(f"Forest map has mixed ISTAT references: {metric}/{level}")
            expected_geometry = f"istat-{level}-{reference_dates[0][:4]}.pmtiles"
            if not any(path.name == expected_geometry for path in geometry.values()):
                raise ValueError(f"Forest map lacks exact ISTAT geometry: {metric}/{level}/{reference_dates[0]}")
            period_key = f"{start[:4]}-{end[:4]}"
            if source_kind == "derived" and "methodology_version" not in rows.columns:
                raise ValueError("Derived Forest canonical contract lacks methodology_version")
            reference_year = int(reference_dates[0][:4])
            coverage = _coverage_for_map(coverage_report, str(rows.iloc[0].methodology_version), period_key, level, reference_year) if source_kind == "derived" and coverage_report else None
            logical = f"delivery/foreste/maps/{metric}/{period_key}/{level}.json"
            _write(destination / logical.removeprefix("delivery/"), {
                "schemaVersion": 1, "releaseId": release_id, "theme": "foreste", "kind": f"{source_kind}_snapshot_map_values",
                "metricId": metric, "unit": rows.iloc[0].unit_ucum, "periodStart": start, "periodEnd": end, "territoryLevel": level, "territoryReferenceDate": reference_dates[0], "territoryReferenceYear": reference_year,
                "territoryGeometryReference": f"istat-{level}-{reference_dates[0][:4]}.pmtiles", "coverage": coverage,
                "columns": ["territoryId", "value"], "values": [[row.territory_id, float(row.value_decimal)] for row in rows.itertuples()], "provenanceRef": "delivery/foreste/provenance.json",
            })
            maps.append(logical)
            map_geometry[logical] = f"delivery/foreste/geometry/{expected_geometry}"
            ranking_logical = f"delivery/foreste/rankings/{metric}/{period_key}/{level}.json"
            _write(destination / ranking_logical.removeprefix("delivery/"), {
                "schemaVersion": 1, "releaseId": release_id, "theme": "foreste", "kind": "derived_slice_comparison",
                "algorithmVersion": "forests-slice-ranking-v2", "scopeLabel": _ranking_scope(source_kind, level, coverage),
                "metricId": metric, "periodStart": start, "periodEnd": end, "territoryLevel": level,
                "rows": _ranking_rows(rows, territory_root, int(reference_dates[0][:4]), level), "provenanceRef": "delivery/foreste/provenance.json",
            })
            rankings.append(ranking_logical)
    geometry_paths = [f"delivery/foreste/geometry/{path.name}" for path in geometry.values()]
    _write(index_path, {"schemaVersion": 1, "releaseId": release_id, "theme": "foreste", "algorithmVersion": DELIVERY_ALGORITHM_VERSION, "canonicalSignature": canonical_signature, "provenance": "delivery/foreste/provenance.json", "maps": maps, "rankings": rankings, "geometry": geometry_paths, "mapGeometry": map_geometry})
    files = sorted(root.rglob("*.json"))
    return {"changed": True, "files": files, "maps": len(maps), "bytes": sum(path.stat().st_size for path in files)}
