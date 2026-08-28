import type { IControl } from "maplibre-gl";

/** Initial Italy framing. User remains free to pan and zoom afterwards. */
export const italyMapCamera = {
  bounds: [[6.45, 35.05], [19.05, 47.35]] as [[number, number], [number, number]],
  fitBoundsOptions: { padding: 27, duration: 0 },
  renderWorldCopies: false,
};

class RecenterControl implements IControl {
  private map?: import("maplibre-gl").Map;
  private container?: HTMLDivElement;

  onAdd(map: import("maplibre-gl").Map) {
    this.map = map;
    const document = map.getContainer().ownerDocument;
    const container = document.createElement("div");
    container.className = "maplibregl-ctrl maplibregl-ctrl-group";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "maplibregl-ctrl-recenter";
    button.setAttribute("aria-label", "Ricentra mappa sull'Italia");
    button.title = "Ricentra mappa sull'Italia";
    button.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M12 3v3m0 12v3M3 12h3m12 0h3M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0 2a2 2 0 1 1 0 4 2 2 0 0 1 0-4Z"/></svg>';
    button.addEventListener("click", () => this.map?.fitBounds(italyMapCamera.bounds, { ...italyMapCamera.fitBoundsOptions, padding: 40 }));
    container.append(button);
    this.container = container;
    return container;
  }

  onRemove() {
    this.container?.remove();
    this.map = undefined;
  }
}

export function configureItalyMapControls(map: import("maplibre-gl").Map, maplibregl: typeof import("maplibre-gl")) {
  map.scrollZoom.disable();
  map.touchZoomRotate.enable();
  map.dragPan.enable();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new RecenterControl(), "top-right");
}
