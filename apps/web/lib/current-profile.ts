import type { MapOption } from "./data";

function territoryRoute(level: MapOption["level"]) {
  return level === "municipality" ? "comuni" : level === "province" ? "province" : "regioni";
}

export function currentProfileHref(level: MapOption["level"], territoryId: string | undefined, istatCode: string | undefined, currentTerritoryIds: string[] | undefined) {
  if (!territoryId || !istatCode || (currentTerritoryIds && !currentTerritoryIds.includes(territoryId))) return undefined;
  return `/territori/${territoryRoute(level)}/${istatCode}`;
}
