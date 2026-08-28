from __future__ import annotations

from pathlib import Path

import mapbox_vector_tile
import mercantile
import pandas as pd
from pmtiles.reader import MmapSource, Reader
from pmtiles.tile import Compression, MagicNumberNotFound, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from shapely import wkb
from shapely.geometry import box

REQUIRED_TERRITORY_FIELDS = frozenset({"territory_id", "territory_level", "istat_code", "name"})


def is_readable_pmtiles(path: Path) -> bool:
    """Return false unless a local PMTiles has the fields needed by the map explorer."""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        with path.open("rb") as handle:
            reader = Reader(MmapSource(handle))
            reader.header()
            layers = reader.metadata().get("vector_layers", [])
    except (MagicNumberNotFound, OSError, ValueError):
        return False
    return any(
        layer.get("id") == "territories" and REQUIRED_TERRITORY_FIELDS <= set(layer.get("fields", {}))
        for layer in layers
    )


def build_pmtiles(territory_parquet: Path, destination: Path, max_zoom: int = 7) -> dict:
    """Build bounded, generalized MVT PMTiles without external map service/tooling."""
    tile_features: dict[tuple[int, int, int], list[dict]] = {}
    for feature in pd.read_parquet(territory_parquet).to_dict("records"):
        geometry = wkb.loads(feature["geometry_wkb"])
        west, south, east, north = geometry.bounds
        for zoom in range(max_zoom + 1):
            for tile in mercantile.tiles(west, south, east, north, [zoom]):
                tile_features.setdefault((zoom, tile.x, tile.y), []).append({
                    "geometry": geometry,
                    "properties": {
                        "territory_id": feature["territory_id"],
                        "territory_level": feature["level"],
                        "istat_code": feature["istat_code"],
                        "name": feature["name"],
                    },
                })
    destination.parent.mkdir(parents=True, exist_ok=True)
    wrote = 0
    with destination.open("wb") as output:
        writer = Writer(output)
        for zoom, x, y in sorted(tile_features):
            bounds = mercantile.bounds(x, y, zoom)
            clip = box(bounds.west, bounds.south, bounds.east, bounds.north)
            features = []
            for source in tile_features[(zoom, x, y)]:
                clipped = source["geometry"].intersection(clip)
                if not clipped.is_empty:
                    features.append({"geometry": clipped.__geo_interface__, "properties": source["properties"]})
            if not features:
                continue
            encoded = mapbox_vector_tile.encode(
                {"name": "territories", "features": features},
                default_options={"quantize_bounds": (bounds.west, bounds.south, bounds.east, bounds.north), "extents": 4096, "y_coord_down": False},
            )
            writer.write_tile(zxy_to_tileid(zoom, x, y), encoded)
            wrote += 1
        writer.finalize(
            {
                "version": 3,
                "tile_compression": Compression.NONE,
                "tile_type": TileType.MVT,
                "min_lon_e7": int(6.5 * 10_000_000),
                "min_lat_e7": int(35.0 * 10_000_000),
                "max_lon_e7": int(19.0 * 10_000_000),
                "max_lat_e7": int(48.0 * 10_000_000),
                "center_zoom": 5,
                "center_lon_e7": int(12.5 * 10_000_000),
                "center_lat_e7": int(42.8 * 10_000_000),
            },
            {
                "name": "ISTAT administrative boundaries",
                "format": "pbf",
                "type": "overlay",
                "version": "2024-01-01",
                "vector_layers": [{"id": "territories", "fields": {"territory_id": "String", "territory_level": "String", "istat_code": "String", "name": "String"}}],
            },
        )
    if wrote == 0:
        raise RuntimeError("PMTiles contained no tiles")
    return {"path": str(destination), "bytes": destination.stat().st_size, "tiles": wrote, "max_zoom": max_zoom}
