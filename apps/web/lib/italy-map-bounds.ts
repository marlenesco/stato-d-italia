/**
 * Shared MapLibre camera limits. The pan buffer is five times the original
 * Italy margin, while world copies remain disabled.
 */
export const italyMapCamera = {
  bounds: [[6.45, 35.05], [19.05, 47.35]] as [[number, number], [number, number]],
  fitBoundsOptions: { padding: 18, duration: 0 },
  minZoom: 1.75,
  maxBounds: [[5.2, 33.3], [20.3, 52.1]] as [[number, number], [number, number]],
  maxBoundsViscosity: 1,
  renderWorldCopies: false,
};
