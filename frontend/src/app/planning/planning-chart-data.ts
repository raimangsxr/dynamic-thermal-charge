import type { PlanningTimelineSlotDto } from '../core/api.types';

export function boundaryLabels(
  slots: PlanningTimelineSlotDto[],
  format: (value: string) => string,
): string[] {
  if (!slots.length) return [];
  return [...slots.map((slot) => format(slot.start)), format(slots[slots.length - 1].end)];
}

export function boundarySeries(
  slots: PlanningTimelineSlotDto[],
  startValue: (slot: PlanningTimelineSlotDto) => number | null | undefined,
  endValue: (slot: PlanningTimelineSlotDto) => number | null | undefined,
): Array<number | null> {
  if (!slots.length) return [];
  return [...slots.map((slot) => startValue(slot) ?? null), endValue(slots[slots.length - 1]) ?? null];
}

export function discreteSeries(
  slots: PlanningTimelineSlotDto[],
  value: (slot: PlanningTimelineSlotDto, index: number) => number,
): number[] {
  if (!slots.length) return [];
  const values = slots.map(value);
  return [...values, values[values.length - 1]];
}

export function discreteBoundarySeries(
  slots: PlanningTimelineSlotDto[],
  startValue: (index: number) => number | null,
  endValue: (index: number) => number | null,
): Array<number | null> {
  if (!slots.length) return [];
  return [...slots.map((_slot, index) => startValue(index)), endValue(slots.length - 1)];
}

export function temperatureAxisRange(
  series: Array<Array<number | null>>,
): { min: number; max: number } | undefined {
  const values = series.flat().filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  if (!values.length) return undefined;
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const padding = Math.max(0.5, (maximum - minimum) * 0.1);
  return { min: minimum - padding, max: maximum + padding };
}
