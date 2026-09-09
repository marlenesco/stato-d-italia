from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
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

BOUNDARY_SOURCE_ID = "istat-administrative-boundaries"
SOURCE_YEARS = (
    2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010,
    2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020,
    2021, 2022, 2023, 2024, 2025, 2026,
)
TERRITORY_CANONICAL_CONTRACT_VERSION = 3
_SPECIAL_REFERENCE_DATES = {2011: "2011-10-09", 2021: "2021-12-31"}
_OFFICIAL_MUNICIPALITY_COUNTS = {2021: 7904}
_H1E_SOURCE_YEARS = frozenset({2002, 2003, 2004, 2005, 2007, 2008, 2009, 2010, 2013, 2014, 2026})


def territory_reference_date(year: int) -> str:
    """Return the official ISTAT reference date for a source snapshot year."""
    return _SPECIAL_REFERENCE_DATES.get(year, date(year, 1, 1).isoformat())


def boundary_url(year: int) -> str:
    base = "https://www.istat.it/storage/cartografia/confini_amministrativi/generalizzati"
    if year == 2011:
        return f"{base}/Limiti2011_g.zip"
    if year == 2021:
        return f"{base}/Limiti2021_g.zip"
    if year >= 2022:
        return f"{base}/{year}/Limiti0101{year}_g.zip"
    return f"{base}/Limiti0101{year}_g.zip"


def boundary_asset_path(year: int) -> str:
    return f"{BOUNDARY_SOURCE_ID}/{year}/limiti-{year}-generalized.zip"


def _shape_file(root: Path, prefix: str | tuple[str, ...]) -> Path:
    prefixes = (prefix,) if isinstance(prefix, str) else prefix
    matches = list({candidate for current in prefixes for candidate in root.rglob(f"{current}*.shp")})
    if len(matches) != 1:
        raise ValueError(f"Expected one {prefix} shapefile, found {len(matches)} in {root}")
    return matches[0]


_ADMINISTRATIVE_CODE_FIELDS = {
    "cod_uts": "COD_UTS",
    "cod_prov": "COD_PROV",
    "cod_cm": "COD_CM",
    "cod_pcm": "COD_PCM",
}


@dataclass(frozen=True)
class _BoundarySourceSchema:
    name: str
    municipality_fields: frozenset[str]
    province_fields: frozenset[str]
    province_code_field: str
    municipality_parent_field: str
    province_name_field: str


_LEGACY_SCHEMA = _BoundarySourceSchema(
    name="legacy_cod_prov_2002_2014",
    municipality_fields=frozenset({"COD_REG", "COD_PROV", "PRO_COM_T", "COMUNE"}),
    province_fields=frozenset({"COD_REG", "COD_PROV", "DEN_PROV"}),
    province_code_field="COD_PROV",
    municipality_parent_field="COD_PROV",
    province_name_field="DEN_PROV",
)
_PCM_SCHEMA = _BoundarySourceSchema(
    name="province_metropolitan_city_cod_pcm_2015_2018",
    municipality_fields=frozenset({
        "COD_REG", "COD_PROV", "COD_CM", "COD_PCM", "PRO_COM_T", "COMUNE",
    }),
    province_fields=frozenset({
        "COD_REG", "COD_PROV", "COD_CM", "COD_PCM", "DEN_PCM",
    }),
    province_code_field="COD_PROV",
    municipality_parent_field="COD_PROV",
    province_name_field="DEN_PCM",
)
_UTS_LEGACY_IDENTITY_SCHEMA = _BoundarySourceSchema(
    name="uts_fields_with_legacy_province_identity",
    municipality_fields=frozenset({
        "COD_REG", "COD_PROV", "COD_CM", "COD_UTS", "PRO_COM_T", "COMUNE",
    }),
    province_fields=frozenset({
        "COD_REG", "COD_PROV", "COD_CM", "COD_UTS", "DEN_UTS",
    }),
    province_code_field="COD_PROV",
    municipality_parent_field="COD_PROV",
    province_name_field="DEN_UTS",
)
_UTS_2021_SCHEMA = _BoundarySourceSchema(
    name="uts_2021",
    municipality_fields=frozenset({"COD_REG", "COD_UTS", "PRO_COM_T", "COMUNE"}),
    province_fields=frozenset({
        "COD_REG", "COD_PROV", "COD_CM", "COD_UTS", "DEN_UTS",
    }),
    province_code_field="COD_UTS",
    municipality_parent_field="COD_UTS",
    province_name_field="DEN_UTS",
)
_UTS_2026_SCHEMA = _BoundarySourceSchema(
    name="uts_2026_sardinia_reform",
    municipality_fields=frozenset({
        "COD_REG", "COD_PROV", "COD_CM", "COD_UTS", "PRO_COM_T", "COMUNE",
    }),
    province_fields=frozenset({
        "COD_REG", "COD_PROV", "COD_CM", "COD_UTS", "DEN_UTS",
    }),
    province_code_field="COD_UTS",
    municipality_parent_field="COD_UTS",
    province_name_field="DEN_UTS",
)


def _boundary_source_schema(year: int) -> _BoundarySourceSchema:
    if 2002 <= year <= 2014:
        return _LEGACY_SCHEMA
    if 2015 <= year <= 2018:
        return _PCM_SCHEMA
    if year in {2019, 2020, 2022, 2023, 2024, 2025}:
        return _UTS_LEGACY_IDENTITY_SCHEMA
    if year == 2021:
        return _UTS_2021_SCHEMA
    if year == 2026:
        return _UTS_2026_SCHEMA
    raise ValueError(f"Unsupported ISTAT boundary source schema year: {year}")


def _optional_code(row: dict, field: str, width: int = 3) -> str | None:
    value = row.get(field)
    return None if value in (None, "", "-") else str(value).zfill(width)


def _source_administrative_codes(row: dict) -> dict[str, str | None]:
    """Keep each official source field distinct; they are not interchangeable."""
    return {name: _optional_code(row, field) for name, field in _ADMINISTRATIVE_CODE_FIELDS.items()}


def _required_source_code(feature: dict, field: str, schema: _BoundarySourceSchema) -> str:
    key = field.lower()
    if code := feature["source_codes"].get(key):
        return code
    raise ValueError(f"ISTAT schema {schema.name} lacks {field}: {feature['name']}")


def resolve_province_uts_code(feature: dict, year: int) -> str:
    """Resolve a canonical Province/UTS identity from its year-specific schema."""
    schema = _boundary_source_schema(year)
    return _required_source_code(feature, schema.province_code_field, schema)


def resolve_municipality_parent_code(feature: dict, year: int) -> str:
    """Resolve a municipality parent without conflating legacy and UTS fields."""
    schema = _boundary_source_schema(year)
    return _required_source_code(feature, schema.municipality_parent_field, schema)


def _source_features(shp: Path, level: str, year: int) -> list[dict]:
    """Read source attributes without choosing municipality/province hierarchy."""
    schema = _boundary_source_schema(year)
    reader = shapefile.Reader(str(shp))
    source_fields = {field[0] for field in reader.fields[1:]}
    required_fields = {
        "municipality": schema.municipality_fields,
        "province": schema.province_fields,
        "region": frozenset({"COD_REG", "DEN_REG"}),
    }.get(level)
    if required_fields is None:
        raise ValueError(f"Unsupported ISTAT boundary level: {level}")
    if missing := required_fields - source_fields:
        raise ValueError(
            f"ISTAT schema {schema.name}/{level} lacks required fields: {sorted(missing)}"
        )
    source_crs = CRS.from_wkt(shp.with_suffix(".prj").read_text())
    target_crs = CRS.from_epsg(4326)
    reproject = None if source_crs.equals(target_crs) else Transformer.from_crs(source_crs, target_crs, always_xy=True).transform
    output: list[dict] = []
    for item in reader.iterShapeRecords():
        row = item.record.as_dict()
        if level == "municipality":
            code = str(row["PRO_COM_T"]).zfill(6)
            name = str(row["COMUNE"])
            source_identity: str | tuple[str, ...] = code
        elif level == "province":
            code = None
            name = str(row[schema.province_name_field])
            source_identity = tuple(
                f"{name}={value}" for name, value in _source_administrative_codes(row).items()
            )
        else:
            code = str(row["COD_REG"]).zfill(2)
            name = str(row["DEN_REG"])
            source_identity = code
        source_codes = _source_administrative_codes(row) if level != "region" else {}
        output.append({
            "level": level,
            "source_identity": source_identity,
            "istat_code": code,
            "name": name,
            "name_normalized": normalize_name(name),
            "source_codes": source_codes,
            "region_code": str(row["COD_REG"]).zfill(2),
            "geometry": transform(reproject, shape(item.shape.__geo_interface__)).__geo_interface__ if reproject else item.shape.__geo_interface__,
        })
    return output


def _dissolve_source_features(features: list[dict]) -> list[dict]:
    grouped: dict[str | tuple[str, ...], list[dict]] = {}
    for feature in features:
        grouped.setdefault(feature["source_identity"], []).append(feature)
    dissolved = []
    for source_identity, pieces in grouped.items():
        first = pieces[0].copy()
        for piece in pieces[1:]:
            for key in ("level", "istat_code", "name", "name_normalized", "source_codes", "region_code"):
                if piece[key] != first[key]:
                    raise ValueError(f"Inconsistent ISTAT source attributes while dissolving {first['level']} {source_identity}")
        first["source_feature_count"] = len(pieces)
        first["geometry"] = unary_union([shape(piece["geometry"]) for piece in pieces]).__geo_interface__
        dissolved.append(first)
    return dissolved


def _canonical_feature(feature: dict, level: str, code: str, reference_date: str, parent_code: str | None) -> dict:
    territory_id = f"it:{level}:{code}"
    return {
        "territory_id": territory_id,
        "territory_version_id": f"{territory_id}@{reference_date}",
        "canonical_contract_version": TERRITORY_CANONICAL_CONTRACT_VERSION,
        "level": level,
        "istat_code": code,
        "name": feature["name"],
        "name_normalized": feature["name_normalized"],
        "parent_istat_code": parent_code,
        "reference_date": reference_date,
        "source_feature_count": feature["source_feature_count"],
        **{f"source_{field}": feature.get("source_codes", {}).get(field) for field in _ADMINISTRATIVE_CODE_FIELDS},
        "geometry": feature["geometry"],
    }


def validate_territory_hierarchy(frames: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Fail closed if a canonical snapshot is not a closed ISTAT hierarchy."""
    required = {"region", "province", "municipality"}
    if set(frames) != required:
        raise ValueError(f"Territory hierarchy has unexpected levels: {sorted(frames)}")
    for level, frame in frames.items():
        if frame.empty or frame["istat_code"].isna().any() or frame["istat_code"].astype(str).duplicated().any():
            raise ValueError(f"Invalid canonical {level} population")
    regions = set(frames["region"]["istat_code"].astype(str))
    provinces = set(frames["province"]["istat_code"].astype(str))
    orphan_provinces = sorted(set(frames["province"]["parent_istat_code"].astype(str)) - regions)
    orphan_municipalities = sorted(set(frames["municipality"]["parent_istat_code"].astype(str)) - provinces)
    if orphan_provinces:
        raise ValueError(f"Canonical territory hierarchy has orphan provinces: {orphan_provinces[:10]}")
    if orphan_municipalities:
        raise ValueError(f"Canonical territory hierarchy has orphan municipalities: {orphan_municipalities[:10]}")
    return {
        "regions": len(regions), "provinces": len(provinces), "municipalities": len(frames["municipality"]),
        "orphan_provinces": 0, "orphan_municipalities": 0,
    }


def normalize_boundary_features(source_features: dict[str, list[dict]], reference_date: str) -> dict[str, list[dict]]:
    """Resolve source identities using the field semantics documented for each year."""
    expected = {"region", "province", "municipality"}
    if set(source_features) != expected:
        raise ValueError(f"ISTAT source lacks expected levels: {sorted(source_features)}")
    regions = _dissolve_source_features(source_features["region"])
    provinces = _dissolve_source_features(source_features["province"])
    municipalities = _dissolve_source_features(source_features["municipality"])
    region_codes = {str(item["istat_code"]) for item in regions}
    if len(region_codes) != len(regions):
        raise ValueError("ISTAT source has duplicate region codes")
    year = int(reference_date[:4])
    normalized_provinces: list[dict] = []
    for item in provinces:
        code = resolve_province_uts_code(item, year)
        if item["region_code"] not in region_codes:
            raise ValueError(f"ISTAT province has an unknown region parent: {item['name']} {item['region_code']}")
        normalized_provinces.append(_canonical_feature(item, "province", code, reference_date, item["region_code"]))
    province_codes = {item["istat_code"] for item in normalized_provinces}
    if len(province_codes) != len(normalized_provinces):
        raise ValueError("ISTAT source resolves multiple province features to one canonical code")
    normalized_municipalities: list[dict] = []
    for item in municipalities:
        parent_code = resolve_municipality_parent_code(item, year)
        if parent_code not in province_codes:
            raise ValueError(f"ISTAT municipality parent does not exist in canonical Province/UTS population: {item['name']} {parent_code}")
        normalized_municipalities.append(_canonical_feature(item, "municipality", str(item["istat_code"]), reference_date, parent_code))
    normalized_regions = [_canonical_feature(item, "region", str(item["istat_code"]), reference_date, None) for item in regions]
    result = {"region": normalized_regions, "province": normalized_provinces, "municipality": normalized_municipalities}
    frames = {level: pd.DataFrame(records) for level, records in result.items()}
    validate_territory_hierarchy(frames)
    return result


def _canonical_snapshot_is_current(existing: Path, year: int) -> bool:
    paths = {level: existing / f"{level}.parquet" for level in ("municipality", "province", "region")}
    if not all(path.is_file() for path in paths.values()):
        return False
    if year not in _H1E_SOURCE_YEARS and year != 2021:
        return True
    try:
        frames = {level: pd.read_parquet(path) for level, path in paths.items()}
        reference_date = territory_reference_date(year)
        if any(
            "canonical_contract_version" not in frame
            or set(frame["canonical_contract_version"].astype(int)) != {TERRITORY_CANONICAL_CONTRACT_VERSION}
            or set(frame["reference_date"].astype(str)) != {reference_date}
            or not frame["territory_version_id"].astype(str).str.endswith(f"@{reference_date}").all()
            for frame in frames.values()
        ):
            return False
        counts = validate_territory_hierarchy(frames)
        if year in _OFFICIAL_MUNICIPALITY_COUNTS:
            return counts["municipalities"] == _OFFICIAL_MUNICIPALITY_COUNTS[year]
        return True
    except (KeyError, TypeError, ValueError):
        return False


def ingest_boundaries(
    raw_root: Path, canonical_root: Path, years: Iterable[int] = SOURCE_YEARS,
    force: bool = False, offline: bool = False,
) -> dict:
    """Archive official ZIPs, retain every source geometry version as canonical GeoJSON."""
    run = {"source_id": "istat-administrative-boundaries", "years": [], "errors": [], "changed": False}
    for year in years:
        url = boundary_url(year)
        archive = raw_root / "raw" / boundary_asset_path(year)
        try:
            metadata = download(url, archive, BOUNDARY_SOURCE_ID, offline=offline)
            existing = canonical_root / "territories" / f"reference_year={year}"
            existing_files = [existing / f"{level}.parquet" for level in ("municipality", "province", "region")]
            if metadata.get("unchanged") and not force and _canonical_snapshot_is_current(existing, year):
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
                reference_date = territory_reference_date(year)
                source_features = {
                    level: _source_features(_shape_file(extract_root, prefix), level, year)
                    for level, prefix in (("municipality", "Com"), ("province", ("ProvCM", "Prov")), ("region", "Reg"))
                }
                features_by_level = normalize_boundary_features(source_features, reference_date)
                if year in _OFFICIAL_MUNICIPALITY_COUNTS and len(features_by_level["municipality"]) != _OFFICIAL_MUNICIPALITY_COUNTS[year]:
                    raise ValueError(
                        f"ISTAT {year} canonical municipality count is {len(features_by_level['municipality'])}, "
                        f"expected {_OFFICIAL_MUNICIPALITY_COUNTS[year]}"
                    )
                record = {"year": year, "referenceDate": reference_date, "raw": metadata, "levels": {}}
                for level in ("municipality", "province", "region"):
                    features = features_by_level[level]
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
        "territory_version_id": f"it:country:IT@{territory_reference_date(year)}",
        "level": "country",
        "istat_code": "IT",
        "name": "Italia",
        "name_normalized": "italia",
        "parent_istat_code": None,
        "reference_date": territory_reference_date(year),
    }
    return index
