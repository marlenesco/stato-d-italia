import type { RefObject } from "react";

export function focusMapForInspector(map: import("maplibre-gl").Map, center: import("maplibre-gl").LngLat, inspector: RefObject<HTMLElement | null>) {
  if (!window.matchMedia("(min-width: 821px)").matches) return;
  window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
    const width = inspector.current?.getBoundingClientRect().width;
    if (!width) return;
    // Positive horizontal offset follows the requested rightward map pan.
    map.easeTo({ center, offset: [width / 2, 0], duration: 340, essential: true });
  }));
}
