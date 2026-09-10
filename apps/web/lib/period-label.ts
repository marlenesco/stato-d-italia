/** Collapse equal annual endpoints for display without changing period keys. */
export function formatPeriodLabel(period: string | undefined): string {
  return period?.replace(/^(\d{4})[-–]\1$/, "$1") ?? "—";
}
