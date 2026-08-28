from pathlib import Path

import mapbox_vector_tile
import pandas as pd
from pmtiles.reader import MmapSource, Reader
from shapely.geometry import box

from stato_italia.tiles import build_pmtiles, is_readable_pmtiles


def test_pmtiles_is_readable_as_mvt_vector_tiles(tmp_path: Path) -> None:
    source = tmp_path / "municipality.parquet"
    pd.DataFrame([{
        "territory_id": "it:municipality:000001",
        "level": "municipality",
        "istat_code": "000001",
        "parent_istat_code": "001",
        "name": "Comune di prova",
        "geometry_wkb": box(12.0, 42.0, 12.2, 42.2).wkb,
    }]).to_parquet(source)
    pd.DataFrame([{
        "territory_id": "it:province:001",
        "level": "province",
        "istat_code": "001",
        "parent_istat_code": "12",
        "name": "Provincia di prova",
        "geometry_wkb": box(12.0, 42.0, 12.2, 42.2).wkb,
    }]).to_parquet(source.parent / "province.parquet")
    pd.DataFrame([{
        "territory_id": "it:region:12",
        "level": "region",
        "istat_code": "12",
        "name": "Regione di prova",
        "geometry_wkb": box(12.0, 42.0, 12.2, 42.2).wkb,
    }]).to_parquet(source.parent / "region.parquet")
    destination = tmp_path / "territories.pmtiles"

    report = build_pmtiles(source, destination, max_zoom=2)

    assert report["tiles"] > 0
    assert is_readable_pmtiles(destination)
    with destination.open("rb") as handle:
        reader = Reader(MmapSource(handle))
        tile = reader.get(0, 0, 0)
    assert tile is not None
    decoded = mapbox_vector_tile.decode(tile)
    assert decoded["territories"]["features"][0]["properties"]["territory_id"] == "it:municipality:000001"
    assert decoded["territories"]["features"][0]["properties"]["name"] == "Comune di prova"
    assert decoded["territories"]["features"][0]["properties"]["parent_name"] == "Provincia di prova"
    assert decoded["territories"]["features"][0]["properties"]["region_name"] == "Regione di prova"


def test_pmtiles_readability_rejects_empty_or_invalid_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pmtiles"
    invalid = tmp_path / "invalid.pmtiles"
    empty.touch()
    invalid.write_bytes(b"not a pmtiles file")

    assert not is_readable_pmtiles(empty)
    assert not is_readable_pmtiles(invalid)
