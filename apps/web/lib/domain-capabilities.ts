export type TerritoryLevel = "country" | "municipality" | "province" | "region";
export type DomainId = "soil" | "water" | "forests" | "emissions" | "risk";
export type DataKind = "official_observation" | "official_model" | "derived_metric" | "mixed";
export type TemporalMode = "annual_series" | "interval_series" | "sparse_series" | "snapshot" | "change_period" | "mixed";
export type ComparisonPolicy = "same_metric_unit" | "same_metric_unit_geometry" | "not_available";

export type DomainCapability = {
  id: DomainId;
  title: string;
  primarySource: string;
  dataKind: DataKind;
  levels: Partial<Record<TerritoryLevel, { dataKind: DataKind; temporal: TemporalMode }>>;
  comparison: ComparisonPolicy;
  ranking: boolean;
  summary: "numeric" | "availability";
};

// This registry states UI semantics. Coverage, metrics, periods and values stay delivery-driven.
export const DOMAIN_CAPABILITIES: Record<DomainId, DomainCapability> = {
  soil: { id: "soil", title: "Suolo", primarySource: "ISPRA / SNPA", dataKind: "official_observation", comparison: "same_metric_unit", ranking: true, summary: "numeric", levels: {
    country: { dataKind: "official_observation", temporal: "interval_series" }, municipality: { dataKind: "official_observation", temporal: "interval_series" }, province: { dataKind: "official_observation", temporal: "interval_series" }, region: { dataKind: "official_observation", temporal: "interval_series" },
  } },
  water: { id: "water", title: "Acqua", primarySource: "ISPRA BIGBANG 10.0", dataKind: "mixed", comparison: "same_metric_unit_geometry", ranking: false, summary: "numeric", levels: {
    country: { dataKind: "official_model", temporal: "annual_series" }, province: { dataKind: "derived_metric", temporal: "sparse_series" }, region: { dataKind: "official_model", temporal: "annual_series" },
  } },
  emissions: { id: "emissions", title: "Emissioni", primarySource: "ISPRA", dataKind: "mixed", comparison: "not_available", ranking: false, summary: "availability", levels: {
    country: { dataKind: "official_observation", temporal: "annual_series" }, province: { dataKind: "official_observation", temporal: "sparse_series" },
  } },
  risk: { id: "risk", title: "Dissesto", primarySource: "ISPRA IdroGEO", dataKind: "official_observation", comparison: "not_available", ranking: false, summary: "numeric", levels: {
    municipality: { dataKind: "official_observation", temporal: "snapshot" }, province: { dataKind: "official_observation", temporal: "snapshot" }, region: { dataKind: "official_observation", temporal: "snapshot" },
  } },
  forests: { id: "forests", title: "Foreste", primarySource: "INFC / Copernicus", dataKind: "mixed", comparison: "same_metric_unit_geometry", ranking: false, summary: "numeric", levels: {
    municipality: { dataKind: "derived_metric", temporal: "mixed" }, province: { dataKind: "derived_metric", temporal: "mixed" }, region: { dataKind: "mixed", temporal: "mixed" }, country: { dataKind: "official_observation", temporal: "snapshot" },
  } },
};
