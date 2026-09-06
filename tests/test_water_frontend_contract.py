from pathlib import Path


def test_water_frontend_distinguishes_official_regions_and_derived_provinces() -> None:
    repository = Path(__file__).parents[1]
    workspace = (repository / "apps/web/components/water-workspace.tsx").read_text()
    loader = (repository / "apps/web/lib/data.ts").read_text()
    series = (repository / "apps/web/components/territory-map-series.tsx").read_text()
    capabilities = (repository / "apps/web/lib/domain-capabilities.ts").read_text()
    profile = (repository / "apps/web/components/territory-profile.tsx").read_text()

    assert 'type WaterLevel = "region" | "province"' in workspace
    assert 'official: "water_total_precipitation_mm"' in workspace
    assert 'derived: "water_total_precipitation_mm_zonal_mean"' in workspace
    assert 'searchParams.get("level") === "province"' in workspace
    assert 'data.mapGeometry?.[selected.logicalPath]' in workspace
    assert 'data.mapGeometry?.[selected.logicalPath] ?? data.geometry.region' in workspace
    assert ': data.mapGeometry?.[selected.logicalPath]' in workspace
    assert "Elaborazione Stato d’Italia su raster ISPRA BIGBANG 10.0 · media zonale pesata per area." in workspace
    assert 'mapGeometry: Object.fromEntries(Object.entries(index.mapGeometry ?? {})' in loader
    assert "territoryGeometryReference?: string" in series
    assert "function geometricallyComparable" in series
    assert "Geometrie territoriali differenti: confronto non comparabile" in series
    assert "DOMAIN_CAPABILITIES" in capabilities
    assert "same_metric_unit_method_geometry" in capabilities
    assert 'rankingPolicy: "allowed_when_published"' in capabilities
    assert 'province: { dataKind: "derived_metric", temporal: "sparse_series" }' in capabilities
    assert all(f"{domain}: {{" in capabilities for domain in ("soil", "water", "forests", "emissions", "risk"))
    assert all(mode in capabilities for mode in ("annual_series", "interval_series", "sparse_series", "snapshot", "mixed"))
    assert "Copertura e natura dei dati" in profile
    assert "Elaborazione Stato d’Italia su raster ISPRA BIGBANG 10.0" in profile
    assert "Alluvioni 2020 e Frane 2024 non sono una serie" in profile
    assert "async function loadTerritoryIdentity" in loader
    assert '"delivery/territories/index.json"' in loader
    assert "TerritoryIdentity" in loader
    identity_loader = loader.split("async function loadTerritoryIdentity", 1)[1].split("async function loadSoilTerritoryProfile", 1)[0]
    assert "delivery/soil" not in identity_loader
    assert "loadSoilTerritoryProfile" in loader
    assert "loadWaterTerritoryProfile" in loader
    assert "TerritoryProfile" in loader
    assert "Alluvioni" in profile
    assert "Frane" in profile
    assert "function ForestDetail" in profile
    assert "group.metrics.map" in profile
    assert "Confronti, delta e trend sono ammessi solo" in profile
