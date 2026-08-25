"use client";

import { useMemo } from "react";

type TimelineControlProps = { periods: string[]; value: string; onChange: (period: string) => void };

export function TimelineControl({ periods, value, onChange }: TimelineControlProps) {
  const orderedPeriods = useMemo(() => [...new Set(periods)], [periods]);
  return <fieldset className="timeline-control">
    <legend>Periodo di riferimento</legend>
    <p>I periodi pubblicati non sono intervalli equidistanti: la visualizzazione non interpola valori mancanti.</p>
    <div className="timeline-options" role="group" aria-label="Cambia periodo">
      {orderedPeriods.map((period) => <button type="button" key={period} onClick={() => onChange(period)} aria-pressed={period === value}>{period}</button>)}
    </div>
  </fieldset>;
}
