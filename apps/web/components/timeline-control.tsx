"use client";

import { useEffect, useId, useMemo, useState } from "react";

type TimelineControlProps = {
  periods: string[];
  value: string;
  onChange: (period: string) => void;
};

export function TimelineControl({ periods, value, onChange }: TimelineControlProps) {
  const inputId = useId();
  const [playing, setPlaying] = useState(false);
  const orderedPeriods = useMemo(() => [...new Set(periods)], [periods]);
  const currentIndex = Math.max(0, orderedPeriods.indexOf(value));
  const playable = orderedPeriods.length > 1;

  useEffect(() => {
    if (!playing || !playable) return;
    const timer = window.setInterval(() => {
      const index = orderedPeriods.indexOf(value);
      if (index < 0 || index >= orderedPeriods.length - 1) {
        setPlaying(false);
        return;
      }
      onChange(orderedPeriods[index + 1]);
    }, 900);
    return () => window.clearInterval(timer);
  }, [onChange, orderedPeriods, playable, playing, value]);

  useEffect(() => {
    if (!playable) setPlaying(false);
  }, [playable]);

  function togglePlayback() {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (currentIndex >= orderedPeriods.length - 1) onChange(orderedPeriods[0]);
    setPlaying(true);
  }

  return <fieldset className="timeline-control">
    <legend>Periodo</legend>
    <div className="timeline-readout">
      <output htmlFor={inputId} aria-live="polite"><span>Selezionato</span><strong>{value}</strong></output>
      <button type="button" onClick={togglePlayback} disabled={!playable} aria-pressed={playing}>
        {playing ? "Stop" : "Riproduci"}
      </button>
    </div>
    <input
      id={inputId}
      type="range"
      min="0"
      max={Math.max(0, orderedPeriods.length - 1)}
      value={currentIndex}
      disabled={!playable}
      aria-label="Cambia periodo"
      onChange={(event) => onChange(orderedPeriods[Number(event.target.value)])}
    />
    <div className="timeline-bounds" aria-hidden="true"><span>{orderedPeriods[0]}</span><span>{orderedPeriods.at(-1)}</span></div>
  </fieldset>;
}
