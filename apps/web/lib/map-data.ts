import type { MapOption } from "./data";

export type MapDataset = {
  values: [string, number][];
  unit: string;
  periodStart: string;
  periodEnd: string;
  territoryGeometryReference?: string;
};

export type SnapshotMapDataset = MapDataset & {
  snapshots?: Array<{ sourceDimensions: { snap_code: string }; unit: string; values: [string, number][] }>;
};

export type TemporalScaleDomain = { min: number; mid: number; max: number };

export function resolvePeriodOption(options: MapOption[], period: string | null | undefined): MapOption | undefined {
  return options.find((option) => option.periodKey === period) ?? options.at(-1);
}

export function resolveMapDataset(raw: SnapshotMapDataset, url: string): MapDataset {
  const snapshotCode = url.split("#", 2)[1];
  const snapshot = snapshotCode ? raw.snapshots?.find((item) => item.sourceDimensions.snap_code === snapshotCode) : undefined;
  return snapshot ? {
    values: snapshot.values,
    unit: snapshot.unit,
    periodStart: raw.periodStart,
    periodEnd: raw.periodEnd,
    territoryGeometryReference: raw.territoryGeometryReference,
  } : raw;
}

export function resolveTemporalScale(datasets: MapDataset[], shared: boolean): TemporalScaleDomain | undefined {
  const scope = shared ? datasets : datasets.slice(0, 1);
  const values = scope.flatMap((dataset) => dataset.values.map(([, value]) => value).filter(Number.isFinite));
  if (!values.length) return undefined;
  const min = Math.min(...values);
  const max = Math.max(...values);
  return { min, mid: min + (max - min) / 2, max };
}
