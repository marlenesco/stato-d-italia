type MapLevel = "country" | "municipality" | "province" | "region";
type MappedTerritoryLevel = Exclude<MapLevel, "country">;

type TerritoryIdentityIndex = {
  currentIdentityIds?: Partial<Record<MappedTerritoryLevel, string[]>>;
} | null | undefined;

export type CurrentTerritoryPopulation = Record<MappedTerritoryLevel, string[]>;

function territoryRoute(level: MapLevel) {
  return level === "municipality" ? "comuni" : level === "province" ? "province" : "regioni";
}

export function currentTerritoryPopulation(index: TerritoryIdentityIndex): CurrentTerritoryPopulation {
  return {
    municipality: index?.currentIdentityIds?.municipality ?? [],
    province: index?.currentIdentityIds?.province ?? [],
    region: index?.currentIdentityIds?.region ?? [],
  };
}

export function currentProfileHref(level: MapLevel, territoryId: string | undefined, istatCode: string | undefined, currentTerritoryIds: string[] | undefined) {
  if (!territoryId || !istatCode || (currentTerritoryIds && !currentTerritoryIds.includes(territoryId))) return undefined;
  return `/territori/${territoryRoute(level)}/${istatCode}`;
}
