from pathlib import Path


def test_water_frontend_distinguishes_official_regions_and_derived_provinces() -> None:
    repository = Path(__file__).parents[1]
    workspace = (repository / "apps/web/components/water-workspace.tsx").read_text()
    loader = (repository / "apps/web/lib/data.ts").read_text()

    assert 'type WaterLevel = "region" | "province"' in workspace
    assert 'official: "water_total_precipitation_mm"' in workspace
    assert 'derived: "water_total_precipitation_mm_zonal_mean"' in workspace
    assert 'searchParams.get("level") === "province"' in workspace
    assert 'data.mapGeometry?.[selected.logicalPath]' in workspace
    assert "Elaborazione Stato d’Italia su raster ISPRA BIGBANG 10.0 · media zonale pesata per area." in workspace
    assert 'mapGeometry: Object.fromEntries(Object.entries(index.mapGeometry ?? {})' in loader
