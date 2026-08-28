export type TerritoryHierarchy = {
  parentName?: string;
  parentLevel?: string;
  parentIstatCode?: string;
  regionName?: string;
  regionIstatCode?: string;
};

const labels: Record<string, string> = { municipality: "Comune", province: "Provincia", region: "Regione" };

export function hierarchyFromProperties(properties?: Record<string, unknown>): TerritoryHierarchy | undefined {
  const text = (key: string) => typeof properties?.[key] === "string" && properties[key] ? properties[key] : undefined;
  const parentName = text("parent_name");
  const regionName = text("region_name");
  if (!parentName && !regionName) return undefined;
  return { parentName, parentLevel: text("parent_level"), parentIstatCode: text("parent_istat_code"), regionName, regionIstatCode: text("region_istat_code") };
}

export function TerritoryContext({ level, hierarchy }: { level: string; hierarchy?: TerritoryHierarchy }) {
  const parentLabel = hierarchy?.parentLevel ? labels[hierarchy.parentLevel] ?? "Territorio padre" : "Territorio padre";
  const showRegion = hierarchy?.regionName && hierarchy.regionName !== hierarchy.parentName;
  return <dl className="territory-context">
    <div><dt>Scala</dt><dd>{labels[level] ?? "Territorio"}</dd></div>
    {hierarchy?.parentName && <div><dt>{parentLabel}</dt><dd>{hierarchy.parentName}{hierarchy.parentIstatCode && <small>ISTAT {hierarchy.parentIstatCode}</small>}</dd></div>}
    {showRegion && <div><dt>Regione</dt><dd>{hierarchy.regionName}{hierarchy.regionIstatCode && <small>ISTAT {hierarchy.regionIstatCode}</small>}</dd></div>}
  </dl>;
}
