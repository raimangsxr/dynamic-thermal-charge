/** Presentation-only temperature formatting. Calculation values stay untouched. */
export function truncateTemperature(value: number): number {
  return Math.trunc(value * 10) / 10;
}

export function formatTemperature(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'sin dato';
  return truncateTemperature(value).toFixed(1);
}
