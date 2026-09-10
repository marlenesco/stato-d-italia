"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { WaterData, WaterOverview as WaterOverviewData } from "../lib/data";
import { retainTerritoryForLevel } from "../lib/explorer-model";
import { shouldRenderMap, shouldRenderTimeline } from "../lib/explorer-rendering";
import { resolveWaterExplorerModel, type WaterExplorerModel } from "../lib/water-explorer-model";
import { ExplorerToolbar } from "./explorer-toolbar";
import { WaterMap } from "./water-map";
import { WaterOverview } from "./water-overview";
import { TimelineControl } from "./timeline-control";

export function normalizedWaterPeriodQuery(queryString: string, model: WaterExplorerModel): string | undefined {
  const query = new URLSearchParams(queryString);
  const requestedPeriod = query.get("period");
  if (requestedPeriod === null || !model.periodKey || requestedPeriod === model.periodKey || model.features.map.status !== "available") return;
  query.set("period", model.periodKey);
  const requestedLevel = query.get("level");
  if (requestedLevel && requestedLevel !== model.level) query.delete("territory");
  return query.toString();
}

export function WaterWorkspace({ data, overview }: { data: WaterData; overview: WaterOverviewData }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedMetric = searchParams.get("metric");
  const requestedLevel = searchParams.get("level");
  const requestedPeriod = searchParams.get("period");
  const model = useMemo(() => resolveWaterExplorerModel({
    maps: data.maps,
    geometry: data.geometry,
    mapGeometry: data.mapGeometry,
    currentTerritoryIds: data.currentTerritoryIds,
    requestedMetric,
    requestedLevel,
    requestedPeriod,
  }), [data, requestedLevel, requestedMetric, requestedPeriod]);
  const requestedTerritory = searchParams.get("territory") ?? undefined;
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>(() => requestedTerritory ? { id: requestedTerritory } : undefined);

  useEffect(() => {
    setTerritory((current) => requestedTerritory ? current?.id === requestedTerritory ? current : { id: requestedTerritory } : undefined);
  }, [requestedTerritory]);

  useEffect(() => {
    const query = normalizedWaterPeriodQuery(searchParams.toString(), model);
    if (query !== undefined) router.replace(`${pathname}?${query}${window.location.hash}`, { scroll: false });
  }, [model, pathname, router, searchParams]);

  function update(next: WaterExplorerModel, nextTerritory?: string) {
    if (!next.level || !next.metricId || !next.periodKey) return;
    const query = new URLSearchParams({ level: next.level, metric: next.metricId, period: next.periodKey });
    if (nextTerritory) query.set("territory", nextTerritory);
    router.replace(`${pathname}?${query.toString()}`, { scroll: false });
  }

  const selectTerritory = useCallback((id: string, name?: string) => {
    setTerritory({ id, name });
    update(model, id);
  }, [model, pathname, router]);

  function nextModel(overrides: { metric?: string; level?: string; period?: string }) {
    return resolveWaterExplorerModel({
      maps: data.maps,
      geometry: data.geometry,
      mapGeometry: data.mapGeometry,
      currentTerritoryIds: data.currentTerritoryIds,
      requestedMetric: overrides.metric ?? model.metricId,
      requestedLevel: overrides.level ?? model.level,
      requestedPeriod: overrides.period ?? model.periodKey,
    });
  }

  function changeMetric(nextMetric: string) {
    const next = nextModel({ metric: nextMetric });
    const retained = retainTerritoryForLevel(model.level, next.level, territory?.id);
    if (!retained) setTerritory(undefined);
    update(next, retained);
  }

  function changeLevel(nextLevel: string) {
    const next = nextModel({ level: nextLevel });
    const retained = retainTerritoryForLevel(model.level, next.level, territory?.id);
    if (!retained) setTerritory(undefined);
    update(next, retained);
  }

  function changePeriod(period: string) {
    update(nextModel({ period }), territory?.id);
  }

  const level = model.level;
  const selected = model.selectedOption;
  const derived = level === "province";
  const levelLabel = level === "province" ? "Province" : "Regioni";
  const mapUnavailable = model.features.map.status === "not_supported"
    ? "La mappa non è supportata per questa combinazione."
    : "La mappa non è pubblicata nella release attiva con una geometria compatibile.";

  return <section className="water-site-layout explorer-layout" aria-label="Atlante idrico">
    <div className="water-site-content">
      <WaterOverview overview={overview} />
      <ExplorerToolbar
        label="Misura"
        value={model.metricId ?? ""}
        onChange={changeMetric}
        items={model.availableMetricFamilies.flatMap((family) => level ? [{ id: family.byLevel[level], label: family.label, meta: "mm" }] : [])}
        levels={model.availableLevels.map((item) => ({ id: item, label: item === "province" ? "Province" : "Regioni" }))}
        level={level}
        onLevelChange={changeLevel}
        context={`${model.periodKey ?? "—"} · ${levelLabel} italiane`}
      />
      <section id="atlante" className="water-workspace map-workspace-v2" tabIndex={-1} aria-label={`Mappa ${derived ? "provinciale" : "regionale"}`}>
        {selected && shouldRenderTimeline(model.features.timeline) && <TimelineControl periods={model.availablePeriods} value={selected.periodKey} onChange={changePeriod} />}
        {selected && shouldRenderMap(model.features.map) && level
          ? <WaterMap option={selected} metricLabel={model.metricFamily?.label ?? model.metricId ?? "Misura idrica"} geometryUrl={model.geometryUrl} territoryLevel={level} derived={derived} features={model.features} currentTerritoryIds={data.currentTerritoryIds?.[level]} selectedTerritoryId={territory?.id} seriesOptions={model.availablePeriods.map((period) => data.maps.find((option) => option.metricId === model.metricId && option.level === level && option.periodKey === period)).filter((option): option is NonNullable<typeof option> => Boolean(option))} onTerritorySelect={selectTerritory} />
          : <p className="state-copy" role="status">{mapUnavailable}</p>}
        <div className="map-reading-panel"><p>{derived ? "Elaborazione Stato d’Italia su raster ISPRA BIGBANG 10.0 · media zonale pesata per area. Non è dato ufficiale ISPRA." : "Stime ufficiali modellistiche BIGBANG 10.0. Nessun ranking “migliore/peggiore”."}</p></div>
        <section className="water-limit"><p className="eyebrow">Come leggere</p><p>{derived ? "Valori provinciali derivati da Stato d’Italia. Timeline con sole annualità e geometrie territoriali effettivamente disponibili." : "Valori BIGBANG 10.0: stime modellistiche annuali ufficiali. Scala colori relativa a metrica e anno selezionati."}</p></section>
        <details className="provenance"><summary>Fonte e metodo · release {data.releaseId}</summary><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
