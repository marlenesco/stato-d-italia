from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import date
from pathlib import Path
from typing import Iterable

import shapefile
import pandas as pd
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from .common import normalize_name
from .download import download

SOURCE_YEARS = (2006, 2012, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025)


def boundary_url(year: int) -> str:
    base = "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati"
    if year == 2011:
        return f"{base}/Limiti2011_g.zip"
    if year == 2021:
        return f"{base}/Limiti2021_g.zip"
    if year >= 2022:
        return f"{base}/{year}/Limiti0101{year}_g.zip"
    return f"{base}/Limiti0101{year}_g.zip"


def _shape_file(root: Path, prefix: str | tuple[str, ...]) -> Path:
    prefixes = (prefix,) if isinstance(prefix, str) else prefix
    matches = list({candidate for current in prefixes for candidate in root.rglob(f"{current}*.shp")})
    if len(matches) != 1:
        raise ValueError(f"Expected one {prefix} shapefile, found {len(matches)} in {root}")
    return matches[0]


def _first_present(row: dict, *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value not in (None, "", "-"):
            return str(value)
    raise KeyError(f"None of expected fields exists: {names}")


def _features(shp: Path, level: str, reference_date: str) -> list[dict]:
    reader = shapefile.Reader(str(shp))
    source_crs = CRS.from_wkt(shp.with_suffix(".prj").read_text())
    target_crs = CRS.from_epsg(4326)
    reproject = None if source_crs.equals(target_crs) else Transformer.from_crs(source_crs, target_crs, always_xy=True).transform
    output: list[dict] = []
    for item in reader.iterShapeRecords():
        row = item.record.as_dict()
        if level == "municipality":
            code = str(row["PRO_COM_T"]).zfill(6)
            name = str(row["COMUNE"])
            parent_code = _first_present(row, "COD_PROV", "COD_UTS").zfill(3)
        elif level == "province":
            code = _first_present(row, "COD_PROV", "COD_UTS", "COD_PCM").zfill(3)
            name = _first_present(row, "DEN_UTS", "DEN_PCM", "DEN_PROV", "DEN_CM")
            parent_code = str(row["COD_REG"]).zfill(2)
        else:
            code = str(row["COD_REG"]).zfill(2)
            name = str(row["DEN_REG"])
            parent_code = None
        territory_id = f"it:{level}:{code}"
        output.append({
            "territory_id": territory_id,
            "territory_version_id": f"{territory_id}@{reference_date}",
            "level": level,
            "istat_code": code,
            "name": name,
            "name_normalized": normalize_name(name),
            "parent_istat_code": parent_code,
            "reference_date": reference_date,
            "geometry": transform(reproject, shape(item.shape.__geo_interface__)).__geo_interface__ if reproject else item.shape.__geo_interface__,
        })
    grouped: dict[str, list[dict]] = {}
    for feature in output:
        grouped.setdefault(feature["territory_id"], []).append(feature)
    dissolved = []
    for territory_id, pieces in grouped.items():
        first = pieces[0].copy()
        first["source_feature_count"] = len(pieces)
        first["geometry"] = unary_union([shape(piece["geometry"]) for piece in pieces]).__geo_interface__
        dissolved.append(first)
    return dissolved


def ingest_boundaries(
    raw_root: Path, canonical_root: Path, years: Iterable[int] = SOURCE_YEARS,
    force: bool = False, offline: bool = False,
) -> dict:
    """Archive official ZIPs, retain every source geometry version as canonical GeoJSON."""
    run = {"source_id": "istat-administrative-boundaries", "years": [], "errors": [], "changed": False}
    for year in years:
        url = boundary_url(year)
        archive = raw_root / "raw" / "istat-administrative-boundaries" / str(year) / f"limiti-{year}-generalized.zip"
        try:
            metadata = download(url, archive, "istat-administrative-boundaries", offline=offline)
            existing = canonical_root / "territories" / f"reference_year={year}"
            existing_files = [existing / f"{level}.parquet" for level in ("municipality", "province", "region")]
            if metadata.get("unchanged") and not force and all(path.exists() for path in existing_files):
                run["years"].append({
                    "year": year,
                    "raw": metadata,
                    "skipped": True,
                    "levels": {level: len(pd.read_parquet(path)) for level, path in zip(("municipality", "province", "region"), existing_files, strict=True)},
                })
                continue
            run["changed"] = True
            with tempfile.TemporaryDirectory(prefix=f"stato-italia-istat-{year}-") as workdir:
                extract_root = Path(workdir)
                with zipfile.ZipFile(archive) as source:
                    source.extractall(extract_root)
                reference_date = date(year, 1, 1).isoformat()
                record = {"year": year, "raw": metadata, "levels": {}}
                for level, prefix in (("municipality", "Com"), ("province", ("ProvCM", "Prov")), ("region", "Reg")):
                    features = _features(_shape_file(extract_root, prefix), level, reference_date)
                    attributes = pd.DataFrame([
                        {k: v for k, v in feature.items() if k not in {"geometry", "name_normalized"}} | {
                            "geometry_wkb": shape(feature["geometry"]).wkb
                        }
                        for feature in features
                    ])
                    parquet = canonical_root / "territories" / f"reference_year={year}" / f"{level}.parquet"
                    parquet.parent.mkdir(parents=True, exist_ok=True)
                    attributes.to_parquet(parquet, index=False, compression="zstd")
                    record["levels"][level] = len(features)
                run["years"].append(record)
        except Exception as exc:  # Source changes must remain visible, never skipped.
            run["errors"].append({"year": year, "error": f"{type(exc).__name__}: {exc}"})
    if run["errors"]:
        raise RuntimeError(json.dumps(run, ensure_ascii=False))
    return run


def load_territory_index(canonical_root: Path, year: int = 2024) -> dict[str, dict]:
    index: dict[str, dict] = {}
    source = canonical_root / "territories" / f"reference_year={year}"
    for path in source.glob("*.parquet"):
        frame = pd.read_parquet(path)
        for properties in frame.drop(columns=["geometry_wkb"]).to_dict("records"):
            properties["name_normalized"] = normalize_name(properties["name"])
            index[properties["territory_id"]] = properties
    index["it:country:IT"] = {
        "territory_id": "it:country:IT",
        "territory_version_id": f"it:country:IT@{year}-01-01",
        "level": "country",
        "istat_code": "IT",
        "name": "Italia",
        "name_normalized": "italia",
        "parent_istat_code": None,
        "reference_date": f"{year}-01-01",
    }
    return index
