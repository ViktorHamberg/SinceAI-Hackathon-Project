import type { ForecastPoint } from './api/forecast';

export const directionSeries = [
  { key: 'p_up', label: 'Up regulation', color: '#945209', dash: undefined },
  { key: 'p_down', label: 'Down regulation', color: '#303432', dash: '6 3' },
  { key: 'p_none', label: 'No dominating mFRR direction', color: '#60665f', dash: '1 4' },
] as const;
export const spikeSeries = [
  { key: 'p_spike_high', label: 'Above spot + €50/MWh', color: '#945209', dash: undefined },
  { key: 'p_spike_low', label: 'Below spot − €50/MWh', color: '#303432', dash: '6 3' },
] as const;
export type ProbabilityKey = typeof directionSeries[number]['key'] | typeof spikeSeries[number]['key'];

// Treat only floating-point arithmetic noise as a tie, not a business threshold.
function equal(a: number, b: number): boolean {
  return Math.abs(a - b) <= 8 * Number.EPSILON * Math.max(1, Math.abs(a), Math.abs(b));
}

function maximum(values: number[]) {
  const value = Math.max(...values);
  return { value, indices: values.flatMap((candidate, index) => equal(candidate, value) ? [index] : []) };
}

export function summarizeForecast(points: ForecastPoint[]) {
  return {
    high: maximum(points.map((point) => point.p_spike_high)),
    low: maximum(points.map((point) => point.p_spike_low)),
    width: maximum(points.map((point) => point.p90 - point.p10)),
  };
}
export type ForecastSummary = ReturnType<typeof summarizeForecast>;

export function highestDirections(point: ForecastPoint): string[] {
  const value = Math.max(...directionSeries.map((series) => point[series.key]));
  return directionSeries.filter((series) => equal(point[series.key], value)).map((series) => series.label);
}

export function probabilitiesAreFlat(points: ForecastPoint[], keys: readonly ProbabilityKey[]): boolean {
  return keys.every((key) => points.every((point) => equal(point[key], points[0][key])));
}

const percentFormat = new Intl.NumberFormat('en-GB', { style: 'percent', maximumFractionDigits: 2 });
export function formatProbability(value: number): string {
  if (value > 0 && value < .0001) return '<0.01%';
  if (value < 1 && value > .9999) return '>99.99%';
  return percentFormat.format(value);
}
