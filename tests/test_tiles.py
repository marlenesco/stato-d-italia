from pathlib import Path

import mapbox_vector_tile
import pandas as pd
from pmtiles.reader import MmapSource, Reader
from shapely.geometry import box

from stato_italia.tiles import build_pmtiles


def test_pmtiles_is_readable_as_mvt_vector_tiles(tmp_path: Path) -> None:
    source = tmp_path / "municipality.parquet"
    pd.DataFrame([{
        "territory_id": "it:municipality:000001",
        "level": "municipality",
        "istat_code": "000001",
        "geometry_wkb": box(12.0, 42.0, 12.2, 42.2).wkb,
    }]).to_parquet(source)
    destination = tmp_path / "territories.pmtiles"

    report = build_pmtiles(source, destination, max_zoom=2)

    assert report["tiles"] > 0
    with destination.open("rb") as handle:
        reader = Reader(MmapSource(handle))
        tile = reader.get(0, 0, 0)
    assert tile is not None
    decoded = mapbox_vector_tile.decode(tile)
    assert decoded["territories"]["features"][0]["properties"]["territory_id"] == "it:municipality:000001"
