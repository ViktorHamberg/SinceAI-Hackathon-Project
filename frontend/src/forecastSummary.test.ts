import { expect, it } from 'vitest';
import { directionSeries, formatProbability, highestDirections, probabilitiesAreFlat, summarizeForecast } from './forecastSummary';
import { fixture } from './test/fixture';

it('computes separate per-quarter maxima and exact P90-minus-P10 widths without mutation', () => {
  const points = fixture().points;
  points[3].p_spike_high = .8;
  points[8].p_spike_low = .7;
  points[12].p10 = -100;
  points[12].p90 = 200;
  const original = structuredClone(points);
  const summary = summarizeForecast(points);
  expect(summary.high).toEqual({ value: .8, indices: [3] });
  expect(summary.low).toEqual({ value: .7, indices: [8] });
  expect(summary.width).toEqual({ value: 300, indices: [12] });
  expect(points).toEqual(original);
});

it('reports every tied maximum and recognizes flat outputs despite arithmetic noise', () => {
  const points = fixture().points;
  const summary = summarizeForecast(points);
  expect(summary.high.indices).toHaveLength(40);
  expect(summary.low.indices).toHaveLength(40);
  expect(summary.width.indices).toHaveLength(40);
  points[1].p_spike_high = .5;
  points[8].p_spike_high = .5;
  expect(summarizeForecast(points).high).toEqual({ value: .5, indices: [1, 8] });
  expect(probabilitiesAreFlat(points, directionSeries.map((series) => series.key))).toBe(true);
  points[39].p_up = .41;
  expect(probabilitiesAreFlat(points, directionSeries.map((series) => series.key))).toBe(false);
});

it('identifies direction winners and ties without interpreting them as price movements', () => {
  const point = fixture().points[0];
  expect(highestDirections(point)).toEqual(['Down regulation']);
  expect(highestDirections({ ...point, p_up: .5, p_down: .5, p_none: 0 })).toEqual(['Up regulation', 'Down regulation']);
  expect(highestDirections({ ...point, p_up: 1 / 3, p_down: 1 / 3, p_none: 1 / 3 })).toHaveLength(3);
  expect(highestDirections({ ...point, p_up: 0, p_down: 0, p_none: 1 })).toEqual(['No dominating mFRR direction']);
});

it.each([[0, '0%'], [1, '100%'], [.4, '40%'], [.123456, '12.35%'], [.000001, '<0.01%'], [.999999, '>99.99%']])('formats probability %s honestly as %s', (value, expected) => {
  expect(formatProbability(value as number)).toBe(expected);
});
