type TimelineControlProps = { periods: string[]; value: string; onChange: (period: string) => void };

export function TimelineControl({ periods, value, onChange }: TimelineControlProps) {
  const orderedPeriods = [...new Set(periods)];
  const index = Math.max(0, orderedPeriods.indexOf(value));

  if (orderedPeriods.length < 2) return null;

  return <fieldset className="timeline-control">
    <legend>Timeline dati pubblicati</legend>
    <div className="timeline-toolbar">
      <button type="button" className="timeline-step" onClick={() => onChange(orderedPeriods[index - 1])} disabled={index === 0} aria-label="Periodo precedente">←</button>
      <output aria-live="polite">{value}</output>
      <button type="button" className="timeline-step" onClick={() => onChange(orderedPeriods[index + 1])} disabled={index === orderedPeriods.length - 1} aria-label="Periodo successivo">→</button>
      <p>Solo periodi realmente disponibili.</p>
    </div>
    {orderedPeriods.length <= 14 ? <div className="timeline-options" role="group" aria-label="Cambia periodo">
      {orderedPeriods.map((period) => <button type="button" key={period} onClick={() => onChange(period)} aria-pressed={period === value}>{period}</button>)}
    </div> : <div className="timeline-slider">
      <input type="range" min="0" max={orderedPeriods.length - 1} value={index} onChange={(event) => onChange(orderedPeriods[Number(event.target.value)])} aria-label="Cambia anno" />
      <div aria-hidden="true"><span>{orderedPeriods[0]}</span><span>{orderedPeriods[Math.floor(orderedPeriods.length / 2)]}</span><span>{orderedPeriods.at(-1)}</span></div>
    </div>}
  </fieldset>;
}
