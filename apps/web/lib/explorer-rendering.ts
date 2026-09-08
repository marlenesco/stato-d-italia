import type { ExplorerFeature, ExplorerFeatures } from "./explorer-model";

export function shouldRenderMap(feature: ExplorerFeature) {
  return feature.status === "available";
}

export function shouldRenderTimeline(feature: ExplorerFeature) {
  return feature.status === "available";
}

export function shouldRenderTerritorySeries(feature: ExplorerFeature) {
  return feature.status === "available";
}

export function shouldRenderComparison(status: ExplorerFeature["status"]) {
  return status === "available";
}

export function shouldRenderRanking(feature: ExplorerFeature) {
  return feature.status !== "not_supported";
}

export function shouldRenderProfileLink(features: ExplorerFeatures, href: string | undefined) {
  return features.profile.status === "available" ? href : undefined;
}

export function profileUnavailableCopy(feature: ExplorerFeature) {
  return feature.status === "not_published" ? "Profilo corrente non disponibile per questa versione territoriale." : undefined;
}
