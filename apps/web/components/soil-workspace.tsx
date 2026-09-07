"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { SoilData } from "../lib/data";
import type { MenuGroup, MenuItem } from "./map-sidebar";
import { ExplorerToolbar } from "./explorer-toolbar";
import { ForestMetricCompanion, type ForestMetricCompanionConfig } from "./forest-metric-companion";
import { SoilMap } from "./soil-map";
import { TimelineControl } from "./timeline-control";
import type { DomainColorName } from "../lib/domain-colors";
import { resolveExplorerModel, retainTerritoryForLevel, type ExplorerSelectionPreferences, type MappableLevel } from "../lib/explorer-model";
import { shouldRenderMap, shouldRenderTimeline, shouldRenderTerritorySeries } from "../lib/explorer-rendering";

const metricLabels: Record<string, string> = {
  soil_net_consumption_hectares: "Incremento netto di suolo consumato",
  soil_gross_consumption_hectares: "Incremento lordo di suolo consumato",
  soil_restoration_hectares: "Ripristino di suolo",
  soil_consumed_hectares: "Suolo consumato (ha)",
  soil_consumed_share: "Suolo consumato (%)",
};

const metricUnits: Record<string, string> = { soil_net_consumption_hectares: "ha", soil_gross_consumption_hectares: "ha", soil_restoration_hectares: "ha", soil_consumed_hectares: "ha", soil_consumed_share: "%" };

function periodLabel(period: string | undefined) {
  if (!period) return "—";
  const [start, end] = period.split("-");
  return start === end ? start : period;
}

function levelLabel(level: MappableLevel) {
  return level === "municipality" ? "Comuni" : level === "province" ? "Province" : "Regioni";
}

type MetricGuide = {
  family: string;
  reading: string;
  source: string;
  sourceNote?: string;
  mapStatusNote?: string;
  seriesStatusNote?: string;
};
type MetricMenuGroup = { id: string; label: string; meta?: string; metricIds: string[] };
type WorkspaceConfig = { title?: string; eyebrow?: string; description?: string; metricLabels?: Record<string, string>; metricUnits?: Record<string, string>; metricGuides?: Record<string, MetricGuide>; hiddenMetricIds?: string[]; metricGroups?: MetricMenuGroup[]; forestCompanions?: ForestMetricCompanionConfig[]; colorRamp?: DomainColorName; sourceNote?: string; mapStatusNote?: string; seriesStatusNote?: string; provenanceSummary?: string; availabilityNote?: string; comparisonNote?: string; sharedTemporalScale?: boolean; domainClass?: string; coverage?: string };

export function ThemeWorkspace({ data, themeLabel, domain, selectionPreferences, config = {} }: { data: SoilData; themeLabel: string; domain: "soil" | "forests"; selectionPreferences?: ExplorerSelectionPreferences; config?: WorkspaceConfig }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const visibleMaps = useMemo(() => data.maps.filter((item) => !config.hiddenMetricIds?.includes(item.metricId)), [config.hiddenMetricIds, data.maps]);
  const requestedMetric = searchParams.get("metric");
  const requestedLevel = searchParams.get("level");
  const requestedPeriod = searchParams.get("period");
  const modelFor = (requested: { metric?: string | null; level?: string | null; period?: string | null } = {}) => resolveExplorerModel({
    domain, maps: visibleMaps, geometry: data.geometry, mapGeometry: data.mapGeometry, rankings: data.rankings, currentTerritoryIds: data.currentTerritoryIds,
    requestedMetric: requested.metric ?? requestedMetric, requestedLevel: requested.level ?? requestedLevel, requestedPeriod: requested.period ?? requestedPeriod,
    preferences: selectionPreferences,
  });
  const model = modelFor();
  const metric = model.metricId;
  const level = model.level;
  const selected = model.selectedOption;
  const metrics = model.availableMetrics;
  const levels = model.availableLevels;
  const available = selected && level ? visibleMaps.filter((item) => item.metricId === selected.metricId && item.level === level && model.availablePeriods.includes(item.periodKey)) : [];
  const periods = model.availablePeriods;
  const requestedTerritory = searchParams.get("territory") ?? undefined;
  const [territory, setTerritory] = useState<{ id: string; name?: string } | undefined>(() => requestedTerritory ? { id: requestedTerritory } : undefined);

  useEffect(() => {
    setTerritory((current) => requestedTerritory ? current?.id === requestedTerritory ? current : { id: requestedTerritory } : undefined);
  }, [requestedTerritory]);

  function update(params: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams.toString());
    Object.entries(params).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key));
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  const selectTerritory = useCallback((id: string, name?: string) => {
    setTerritory({ id, name });
    update({ territory: id });
  }, [pathname, router, searchParams]);

  function changeMetric(nextMetric: string) {
    const next = modelFor({ metric: nextMetric, level, period: null });
    const retainedTerritory = retainTerritoryForLevel(level, next.level, territory?.id ?? requestedTerritory);
    if (!retainedTerritory) setTerritory(undefined);
    update({ metric: next.metricId, level: next.level, period: next.periodKey, territory: retainedTerritory });
  }

  function changeLevel(nextLevel: MappableLevel) {
    const next = modelFor({ level: nextLevel, period: null });
    setTerritory(undefined);
    update({ level: next.level, period: next.periodKey, territory: undefined });
  }

  const labels = config.metricLabels ?? metricLabels;
  const units = config.metricUnits ?? metricUnits;
  const menuItems: MenuItem[] = metrics.map((id) => ({ id, label: labels[id] ?? id, meta: config.metricGuides?.[id]?.family ?? units[id] }));
  const groupedMetricIds = new Set(config.metricGroups?.flatMap((group) => group.metricIds) ?? []);
  const menuGroups: MenuGroup[] | undefined = config.metricGroups?.map((group) => ({ id: group.id, label: group.label, meta: group.meta, items: group.metricIds.flatMap((metricId) => {
    const item = menuItems.find((candidate) => candidate.id === metricId);
    return item ? [{ ...item, meta: undefined }] : [];
  }) })).filter((group) => group.items.length);
  const ungroupedItems = menuItems.filter((item) => !groupedMetricIds.has(item.id));
  if (ungroupedItems.length) menuGroups?.push({ id: "other", label: "Altre misure", meta: undefined, items: ungroupedItems });
  const title = config.title ?? "Consumo di suolo";
  const guide = metric ? config.metricGuides?.[metric] : undefined;
  const sourceNote = guide?.sourceNote ?? config.sourceNote ?? "valori ufficiali ISPRA/SNPA.";
  const mapStatusNote = guide?.mapStatusNote ?? config.mapStatusNote ?? "Mappa: osservazioni ufficiali. Confronto e percentile solo quando pubblicati.";
  const provenanceSummary = config.provenanceSummary ?? "Valori in mappa: osservazioni ufficiali. Ranking e percentili: elaborazioni riproducibili del progetto.";
  const availabilityNote = config.availabilityNote ?? "Solo periodi ufficialmente pubblicati.";
  const coverage = config.coverage ?? ["municipality", "province", "region"].filter((item) => levels.includes(item as MappableLevel)).map((item) => levelLabel(item as MappableLevel)).join(" · ");
  return <section className={`soil-site-layout explorer-layout ${config.domainClass ?? ""}`} aria-label={`Esplorazione ${themeLabel}`}>
    <div className="soil-site-content">
      <header className="workspace-header">
        <div><p className="eyebrow">{guide?.source ?? config.eyebrow ?? "ISPRA / SNPA"}</p><h1>{title}</h1></div>
        <p>{config.description ?? "Valori ufficiali per periodo. Analisi, ranking e percentili sono elaborazioni riproducibili del progetto."}</p>
        <dl><div><dt>Copertura</dt><dd>{coverage}</dd></div><div><dt>Misure</dt><dd>{metrics.length}</dd></div><div><dt>Release</dt><dd>{data.releaseId}</dd></div></dl>
      </header>
      <ExplorerToolbar label="Misura" value={metric ?? ""} onChange={changeMetric} items={menuItems} groups={menuGroups} levels={levels.map((item) => ({ id: item, label: levelLabel(item) }))} level={level ?? ""} onLevelChange={(id) => changeLevel(id as MappableLevel)} context={`${periodLabel(selected?.periodKey)} · ${sourceNote}`} />
      {guide && metric && <section className="metric-reading" aria-live="polite"><div><p className="eyebrow">Come leggere</p><h2>{labels[metric] ?? metric}</h2></div><p>{guide.reading}</p><p><strong>{guide.family}</strong><br />{guide.source}</p></section>}
      <section id="mappa" className="soil-workspace map-workspace-v2" tabIndex={-1} aria-label={`Mappa ${title.toLowerCase()}`}>
        {selected && shouldRenderTimeline(model.features.timeline) && <TimelineControl periods={periods} value={selected.periodKey} onChange={(period) => update({ period })} />}
        {selected && shouldRenderMap(model.features.map) ? <SoilMap option={selected} metricLabel={labels[selected.metricId] ?? selected.metricId} geometryUrl={model.geometryUrl} rankingUrl={model.rankingUrl} features={model.features} selectedTerritoryId={territory?.id} seriesOptions={shouldRenderTerritorySeries(model.features.territorySeries) ? available : undefined} seriesStatusNote={guide?.seriesStatusNote ?? config.seriesStatusNote} colorRamp={config.colorRamp} comparisonNote={config.comparisonNote} sharedTemporalScale={config.sharedTemporalScale} currentTerritoryIds={data.currentTerritoryIds?.[selected.level]} onTerritorySelect={selectTerritory} /> : <p role={model.features.map.status === "not_supported" ? "status" : "alert"}>{model.features.map.status === "not_supported" ? "Mappa non supportata per questo dominio." : "Mappa non disponibile nella release attiva."}</p>}
        <div className="map-reading-panel"><p>{mapStatusNote}</p></div>
        {selected && config.forestCompanions && <ForestMetricCompanion activeMetricId={selected.metricId} selectedOption={selected} selectedTerritoryId={territory?.id} selectedTerritoryName={territory?.name} maps={data.maps} metricLabels={labels} companions={config.forestCompanions} />}
        <details className="provenance"><summary>Fonte, metodo, limiti</summary><p>{provenanceSummary} {availabilityNote}</p><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
