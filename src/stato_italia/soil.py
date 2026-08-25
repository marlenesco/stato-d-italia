from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from .common import normalize_name, now_iso, stable_id
from .download import download
from .registry import load_source
from .territories import load_territory_index

SOIL_SOURCE = load_source("ispra-soil")
SOIL_URL = SOIL_SOURCE["download_url"]
PERIOD_RE = re.compile(r"^(Incremento netto|Incremento lordo|Ripristino) (\d{4})-(\d{4}) \[ettari\]$")
POINT_RE = re.compile(r"^Suolo consumato (\d{4}) \[(ettari|%)\]$")

CHANGE_METRIC = {
    "Incremento netto": "soil_net_consumption_hectares",
    "Incremento lordo": "soil_gross_consumption_hectares",
    "Ripristino": "soil_restoration_hectares",
}
POINT_METRIC = {"ettari": "soil_consumed_hectares", "%": "soil_consumed_share"}
POINT_UNIT = {"ettari": "ha", "%": "%"}
EXPECTED_PERIODS = {(2006, 2012), (2012, 2015), *{(year, year + 1) for year in range(2015, 2024)}}


def _cell(value: object) -> float | None:
    if pd.isna(value):
        return None
    result = float(value)
    if not pd.notna(result):
        return None
    return result


def _record(
    *, source_hash: str, level: str, territory: dict, metric_id: str,
    start_year: int, end_year: int, value: float, unit: str, row_locator: str, ingested_at: str,
) -> dict:
    period_start = date(start_year, 1, 1).isoformat()
    period_end = date(end_year, 12, 31).isoformat()
    observation_id = stable_id("ispra-soil-2025", source_hash, row_locator, metric_id, period_start, period_end)
    return {
        "observation_id": observation_id,
        "dataset_id": "ispra-soil-2025",
        "dataset_version": "2025-2024-observations",
        "source_asset_sha256": source_hash,
        "source_row_locator": row_locator,
        "metric_id": metric_id,
        "territory_id": territory["territory_id"],
        "territory_version_id": territory["territory_version_id"],
        "territory_level": level,
        "period_start": period_start,
        "period_end": period_end,
        "reference_year": end_year,
        "value_decimal": value,
        "unit_ucum": unit,
        "official_status": "unknown",
        "quality_flags": [],
        "methodology_version": "ispra-soil-2025",
        "ingested_at": ingested_at,
    }


def _lookup_by_name(index: dict[str, dict], level: str, name: str, region: str | None = None) -> dict:
    candidates = [entry for entry in index.values() if entry["level"] == level and entry["name_normalized"] == normalize_name(name)]
    if region:
        # Province names are unique in current reference geometry. Region retained
        # in source row to make any future ambiguous name a loud mapping failure.
        candidates = candidates
    if len(candidates) != 1:
        raise ValueError(f"{level} mapping failed for {name!r}: {len(candidates)} candidates")
    return candidates[0]


def _rows_from_sheet(frame: pd.DataFrame, level: str, index: dict[str, dict], source_hash: str, ingested_at: str) -> tuple[list[dict], list[dict]]:
    output: list[dict] = []
    mapping_issues: list[dict] = []
    for row_number, row in frame.iterrows():
        try:
            if level == "municipality":
                code = str(int(row["PRO_COM"])).zfill(6)
                territory = index.get(f"it:municipality:{code}")
                if territory is None:
                    raise ValueError(f"ISTAT municipality code {code} absent in 2024 boundaries")
            elif level == "province":
                territory = _lookup_by_name(index, level, str(row["Nome_Provincia"]), str(row["Nome_Regione"]))
            else:
                name = str(row["Nome_Regione"])
                territory = index["it:country:IT"] if normalize_name(name) == "italia" else _lookup_by_name(index, level, name)
        except Exception as exc:
            mapping_issues.append({"sheet_row": int(row_number) + 2, "level": level, "error": str(exc)})
            continue
        for column, raw in row.items():
            period = PERIOD_RE.match(str(column))
            point = POINT_RE.match(str(column))
            if not period and not point:
                continue
            value = _cell(raw)
            if value is None:
                continue
            if period:
                label, start, end = period.groups()
                output.append(_record(
                    source_hash=source_hash, level=territory["level"], territory=territory,
                    metric_id=CHANGE_METRIC[label], start_year=int(start), end_year=int(end),
                    value=value, unit="ha", row_locator=f"{level}:{row_number + 2}:{column}", ingested_at=ingested_at,
                ))
                continue
            if point:
                year, source_unit = point.groups()
                output.append(_record(
                    source_hash=source_hash, level=territory["level"], territory=territory,
                    metric_id=POINT_METRIC[source_unit], start_year=int(year), end_year=int(year),
                    value=value, unit=POINT_UNIT[source_unit], row_locator=f"{level}:{row_number + 2}:{column}", ingested_at=ingested_at,
                ))
    return output, mapping_issues


def _validate_contract(frame: pd.DataFrame, level: str) -> None:
    columns = {str(column) for column in frame.columns}
    required_identity = {
        "municipality": {"PRO_COM", "Nome_Comune", "Nome_Regione", "Nome_Provincia"},
        "province": {"Nome_Provincia", "Nome_Regione"},
        "region": {"Nome_Regione"},
    }[level]
    missing = required_identity - columns
    periods = {(int(match.group(2)), int(match.group(3))) for column in columns if (match := PERIOD_RE.match(column))}
    points = {(int(match.group(1)), match.group(2)) for column in columns if (match := POINT_RE.match(column))}
    if missing or periods != EXPECTED_PERIODS or points != {(2024, "ettari"), (2024, "%")}:
        raise ValueError(
            f"Unexpected ISPRA {level} contract: missing={sorted(missing)}, periods={sorted(periods)}, points={sorted(points)}"
        )


def _summarize(source: dict, destination: Path) -> dict:
    table = pd.read_parquet(destination)
    years = sorted({int(value) for value in table["reference_year"].unique()})
    periods = sorted({(str(start), str(end)) for start, end in zip(table["period_start"], table["period_end"], strict=True)})
    return {
        "source": source, "records": len(table), "records_by_level": table.groupby("territory_level").size().to_dict(),
        "records_by_metric": table.groupby("metric_id").size().to_dict(), "reference_years": years,
        "available_periods": [{"start": start, "end": end} for start, end in periods],
        "canonical_path": str(destination), "canonical_bytes": destination.stat().st_size, "mapping_issues": [],
    }


def ingest_soil(raw_root: Path, canonical_root: Path, force: bool = False) -> dict:
    workbook = raw_root / "raw" / "ispra-soil-2025" / "consumo-di-suolo-2025.xlsx"
    source = download(SOIL_URL, workbook, "ispra-soil-2025")
    destination = canonical_root / "soil" / "dataset_version=2025-2024-observations" / "observations.parquet"
    if source.get("unchanged") and destination.exists() and not force:
        current = pd.read_parquet(destination, columns=["territory_id", "territory_version_id"])
        country_version = set(current.loc[current["territory_id"] == "it:country:IT", "territory_version_id"])
        if country_version == {"it:country:IT@2025-01-01"}:
            return _summarize(source, destination) | {"changed": False, "skipped": True}
    # Workbook's three changed Veneto codes are present only in ISTAT 2025.
    # This factual join pins source geography to that boundary version.
    index = load_territory_index(canonical_root, 2025)
    records: list[dict] = []
    mapping_issues: list[dict] = []
    for level, sheet in (("municipality", "Comuni_2006_2024"), ("province", "Province_2006_2024"), ("region", "Regioni_2006_2024")):
        frame = pd.read_excel(workbook, sheet_name=sheet)
        _validate_contract(frame, level)
        current, issues = _rows_from_sheet(frame, level, index, source["sha256"], source["acquired_at"])
        records.extend(current)
        mapping_issues.extend(issues)
    if mapping_issues:
        raise RuntimeError(f"Territory mapping must be complete: {mapping_issues[:10]}")
    table = pd.DataFrame(records)
    if table.empty:
        raise ValueError("ISPRA workbook produced no canonical observations")
    if table.duplicated(["observation_id"]).any():
        raise ValueError("Duplicate canonical observation IDs")
    destination.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(destination, index=False, compression="zstd")
    return _summarize(source, destination) | {"changed": True}
