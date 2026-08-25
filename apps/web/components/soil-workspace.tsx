"use client";

import { useMemo, useState } from "react";
import type { MapOption, SoilData } from "../lib/data";
import { SoilMap } from "./soil-map";
import { TimelineControl } from "./timeline-control";

type MappableLevel = Exclude<MapOption["level"], "country">;

const metricLabels: Record<string, string> = {
  soil_net_consumption_hectares: "Incremento netto di suolo consumato",
  soil_gross_consumption_hectares: "Incremento lordo di suolo consumato",
  soil_restoration_hectares: "Ripristino di suolo",
  soil_consumed_hectares: "Suolo consumato (ha)",
  soil_consumed_share: "Suolo consumato (%)",
  water_total_precipitation_mm: "Precipitazione totale",
  water_actual_evapotranspiration_mm: "Evapotraspirazione effettiva",
  water_internal_flow_mm: "Risorsa idrica rinnovabile",
  water_aquifer_recharge_mm: "Ricarica acquiferi",
  water_surface_runoff_mm: "Ruscellamento superficiale",
};

function rankingPath(option: MapOption) {
  return `delivery/soil/rankings/${option.metricId}/${option.periodKey}/${option.level}.json`;
}

function comparePeriods(left: string, right: string) {
  return Number(left.slice(0, 4)) - Number(right.slice(0, 4)) || left.localeCompare(right);
}

export function ThemeWorkspace({ data, themeLabel }: { data: SoilData; themeLabel: string }) {
  const metrics = useMemo(() => [...new Set(data.maps.map((item) => item.metricId))], [data.maps]);
  const [metric, setMetric] = useState(metrics[0]);
  const levels = useMemo(() => Array.from(new Set(data.maps.map((item) => item.level))).filter((item): item is MappableLevel => item !== "country"), [data.maps]);
  const [level, setLevel] = useState<MappableLevel>(data.maps.some((item) => item.level === "municipality") ? "municipality" : "region");
  const available = data.maps.filter((item) => item.metricId === metric && item.level === level).sort((left, right) => comparePeriods(left.periodKey, right.periodKey));
  const [period, setPeriod] = useState("");
  const selected = available.find((item) => item.periodKey === period) ?? available.at(-1);
  const periods = available.map((item) => item.periodKey);

  return <section className="workspace" aria-label={`Esplorazione ${themeLabel}`}>
    <div className="controls" aria-label="Filtri mappa">
      <label>Metrica<select value={metric} onChange={(event) => { setMetric(event.target.value); setPeriod(""); }}>
        {metrics.map((item) => <option key={item} value={item}>{metricLabels[item] ?? item}</option>)}
      </select></label>
      <label>Livello<select value={level} onChange={(event) => { setLevel(event.target.value as MappableLevel); setPeriod(""); }}>
        {levels.map((item) => <option key={item} value={item}>{item === "municipality" ? "Comuni" : item === "province" ? "Province" : "Regioni"}</option>)}
      </select></label>
      {level === "municipality" && <a href="/territori/comuni/roma-058091">Profilo Roma</a>}
    </div>
    {selected && <TimelineControl periods={periods} value={selected.periodKey} onChange={setPeriod} />}
    {selected ? <SoilMap option={selected} geometryUrl={data.geometry[level]} rankingUrl={data.rankings[rankingPath(selected)]} /> : <p role="alert">Combinazione non disponibile.</p>}
    <details className="provenance"><summary>Fonte, metodo, limiti</summary><pre>{JSON.stringify(data.provenance, null, 2)}</pre></details>
  </section>;
}
