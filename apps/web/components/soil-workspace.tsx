"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { MapOption, SoilData } from "../lib/data";
import type { MenuGroup, MenuItem } from "./map-sidebar";
import { ExplorerToolbar } from "./explorer-toolbar";
import { ForestMetricCompanion, type ForestMetricCompanionConfig } from "./forest-metric-companion";
import { SoilMap } from "./soil-map";
import { TimelineControl } from "./timeline-control";
import type { DomainColorName } from "../lib/domain-colors";

type MappableLevel = Exclude<MapOption["level"], "country">;

const metricLabels: Record<string, string> = {
  soil_net_consumption_hectares: "Incremento netto di suolo consumato",
  soil_gross_consumption_hectares: "Incremento lordo di suolo consumato",
  soil_restoration_hectares: "Ripristino di suolo",
  soil_consumed_hectares: "Suolo consumato (ha)",
  soil_consumed_share: "Suolo consumato (%)",
};

const metricUnits: Record<string, string> = { soil_net_consumption_hectares: "ha", soil_gross_consumption_hectares: "ha", soil_restoration_hectares: "ha", soil_consumed_hectares: "ha", soil_consumed_share: "%" };

function rankingPath(option: MapOption, root: string) {
  return `delivery/${root}/rankings/${option.metricId}/${option.periodKey}/${option.level}.json`;
}

function comparePeriods(left: string, right: string) {
  return Number(left.slice(0, 4)) - Number(right.slice(0, 4)) || left.localeCompare(right);
}

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
type WorkspaceConfig = { title?: string; eyebrow?: string; description?: string; metricLabels?: Record<string, string>; metricUnits?: Record<string, string>; metricGuides?: Record<string, MetricGuide>; defaultMetric?: string; hiddenMetricIds?: string[]; metricAliases?: Record<string, string>; metricGroups?: MetricMenuGroup[]; forestCompanions?: ForestMetricCompanionConfig[]; dataRoot?: string; colorRamp?: DomainColorName; sourceNote?: string; mapStatusNote?: string; seriesStatusNote?: string; provenanceSummary?: string; availabilityNote?: string; comparisonNote?: string; domainClass?: string; coverage?: string };

export function ThemeWorkspace({ data, themeLabel, config = {} }: { data: SoilData; themeLabel: string; config?: WorkspaceConfig }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const publishedMetrics = useMemo(() => [...new Set(data.maps.map((item) => item.metricId))], [data.maps]);
  const metrics = useMemo(() => publishedMetrics.filter((metricId) => !config.hiddenMetricIds?.includes(metricId)), [config.hiddenMetricIds, publishedMetrics]);
  const requestedMetric = searchParams.get("metric");
  const resolvedRequestedMetric = requestedMetric ? config.metricAliases?.[requestedMetric] ?? requestedMetric : null;
  // Start on a metric with a real published time series, so the timeline and
  // its period-on-period comparison are useful without an extra choice.
  const defaultMetric = config.defaultMetric && metrics.includes(config.defaultMetric) ? config.defaultMetric : (metrics.includes("soil_net_consumption_hectares") ? "soil_net_consumption_hectares" : metrics[0]);
  const metric = resolvedRequestedMetric && metrics.includes(resolvedRequestedMetric) ? resolvedRequestedMetric : defaultMetric;
  const levels = useMemo(() => Array.from(new Set(data.maps.filter((item) => item.metricId === metric).map((item) => item.level))).filter((item): item is MappableLevel => item !== "country"), [data.maps, metric]);
  const requestedLevel = searchParams.get("level") as MappableLevel | null;
  const level = requestedLevel && levels.includes(requestedLevel) ? requestedLevel : (levels.includes("municipality") ? "municipality" : levels[0]);
  const available = data.maps.filter((item) => item.metricId === metric && item.level === level).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
  const requestedPeriod = searchParams.get("period");
  const selected = available.find((item) => item.periodKey === requestedPeriod) ?? available.at(-1);
  const periods = available.map((item) => item.periodKey);
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
    const nextLevels = Array.from(new Set(data.maps.filter((item) => item.metricId === nextMetric && item.level !== "country").map((item) => item.level))) as MappableLevel[];
    const nextLevel = nextLevels.includes(level) ? level : (nextLevels.includes("municipality") ? "municipality" : nextLevels[0]);
    const nextPeriods = data.maps.filter((item) => item.metricId === nextMetric && item.level === nextLevel).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
    const retainedTerritory = nextLevel === level ? territory?.id ?? requestedTerritory : undefined;
    if (!retainedTerritory) setTerritory(undefined);
    update({ metric: nextMetric, level: nextLevel, period: nextPeriods.at(-1)?.periodKey, territory: retainedTerritory });
  }

  function changeLevel(nextLevel: MappableLevel) {
    const nextPeriod = data.maps.filter((item) => item.metricId === metric && item.level === nextLevel).sort((left, right) => comparePeriods(left.periodKey, right.periodKey)).at(-1)?.periodKey;
    setTerritory(undefined);
    update({ level: nextLevel, period: nextPeriod, territory: undefined });
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
  const guide = config.metricGuides?.[metric];
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
      <ExplorerToolbar label="Misura" value={metric} onChange={changeMetric} items={menuItems} groups={menuGroups} levels={levels.map((item) => ({ id: item, label: levelLabel(item) }))} level={level} onLevelChange={(id) => changeLevel(id as MappableLevel)} context={`${periodLabel(selected?.periodKey)} · ${sourceNote}`} />
      {guide && <section className="metric-reading" aria-live="polite"><div><p className="eyebrow">Come leggere</p><h2>{labels[metric] ?? metric}</h2></div><p>{guide.reading}</p><p><strong>{guide.family}</strong><br />{guide.source}</p></section>}
      <section id="mappa" className="soil-workspace map-workspace-v2" tabIndex={-1} aria-label={`Mappa ${title.toLowerCase()}`}>
        {selected && <TimelineControl periods={periods} value={selected.periodKey} onChange={(period) => update({ period })} />}
        {selected ? <SoilMap option={selected} metricLabel={labels[selected.metricId] ?? selected.metricId} geometryUrl={data.mapGeometry?.[selected.logicalPath] ?? data.geometry[level]} rankingUrl={data.rankings[rankingPath(selected, config.dataRoot ?? "soil")]} selectedTerritoryId={territory?.id} seriesOptions={available} seriesStatusNote={guide?.seriesStatusNote ?? config.seriesStatusNote} colorRamp={config.colorRamp} comparisonNote={config.comparisonNote} onTerritorySelect={selectTerritory} /> : <p role="alert">Combinazione non disponibile nella release attiva.</p>}
        <div className="map-reading-panel"><p>{mapStatusNote}</p></div>
        {selected && config.forestCompanions && <ForestMetricCompanion activeMetricId={metric} selectedOption={selected} selectedTerritoryId={territory?.id} selectedTerritoryName={territory?.name} maps={data.maps} metricLabels={labels} companions={config.forestCompanions} />}
        <details className="provenance"><summary>Fonte, metodo, limiti</summary><p>{provenanceSummary} {availabilityNote}</p><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
      </section>
    </div>
  </section>;
}
