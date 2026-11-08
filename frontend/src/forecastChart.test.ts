import { expect, it } from 'vitest';
import { buildChartData, formatChartTick, quarterAtPosition, QUARTER_MS } from './forecastChart';
import { fixture, historyFixture } from './test/fixture';

it('includes actual extremes without clipping, filling gaps or changing any forecast value', () => {
  const forecast = fixture();
  const original = structuredClone(forecast);
  const history = historyFixture(forecast, [-500, null, 2000]);
  const chart = buildChartData(forecast.points, history.points);
  expect(chart.data).toHaveLength(40);
  expect(chart.data.slice(0, 4).map((row) => row.actual)).toEqual([-500, null, 2000, null]);
  expect(chart.priceDomain[0]).toBeLessThan(-500);
  expect(chart.priceDomain[1]).toBeGreaterThan(2000);
  expect(forecast).toEqual(original);
  expect(chart.end - chart.start).toBe(40 * QUARTER_MS);
});

it('uses evenly spaced round price ticks while keeping the entire interval visible', () => {
  const points = fixture().points.map((point) => ({ ...point, p10: -61, p50: .48, p90: 66 }));
  const { priceDomain, priceTicks } = buildChartData(points);
  expect(priceTicks).toEqual([-100, -50, 0, 50, 100]);
  expect(priceDomain).toEqual([-100, 100]);
});

it('retains the exact 40 intervals and all quantiles without mutating input', () => {
  const points = fixture().points;
  const original = structuredClone(points);
  const chart = buildChartData(points);
  expect(chart.data).toHaveLength(40);
  expect(chart.end - chart.start).toBe(10 * 60 * 60 * 1000);
  for (const [index, row] of chart.data.entries()) {
    expect(row.timestamp).toBe(chart.start + index * QUARTER_MS);
    expect(row.band).toEqual([points[index].p10, points[index].p90]);
    expect(row.p50).toBe(points[index].p50);
  }
  expect(points).toEqual(original);
});

it('maps actual delivery intervals, not nearest starts, and ignores axes/outside the plot', () => {
  expect(quarterAtPosition(58, 100, 900, 360, 40)).toBe(0);
  expect(quarterAtPosition(78, 100, 900, 360, 40)).toBe(0);
  expect(quarterAtPosition(79, 100, 900, 360, 40)).toBe(1);
  expect(quarterAtPosition(888, 100, 900, 360, 40)).toBe(39);
  expect(quarterAtPosition(20, 100, 900, 360, 40)).toBeNull();
  expect(quarterAtPosition(400, 350, 900, 360, 40)).toBeNull();
  expect(quarterAtPosition(40, 100, 50, 360, 40)).toBeNull();
  expect(quarterAtPosition(NaN, 100, 900, 360, 40)).toBeNull();
});

it.each([280, 580, 900])('keeps all 40 pointer intervals selectable at chart width %s', (width) => {
  const plotWidth = width - 58 - 12;
  for (let index = 0; index < 40; index++) {
    const center = 58 + plotWidth * (index + .5) / 40;
    expect(quarterAtPosition(center, 100, width, 310, 40)).toBe(index);
  }
});

it.each([
  [-90, -30, -10],
  [-70, 0, 50],
  [20, 40, 80],
  [0, 0, 0],
])('preserves negative, crossing-zero, positive and collapsed bands (%s,%s,%s)', (p10, p50, p90) => {
  const points = fixture().points.map((p) => ({ ...p, p10, p50, p90 }));
  const { data, priceDomain } = buildChartData(points);
  expect(data.every((p) => p.band[0] === p10 && p.band[1] === p90 && p.p50 === p50)).toBe(true);
  expect(priceDomain[0]).toBeLessThan(p10);
  expect(priceDomain[1]).toBeGreaterThan(p90);
});

it('retains the full final quarter and stable UTC ticks through midnight and DST', () => {
  const chart = buildChartData(fixture('2026-10-25T00:00:00Z').points);
  expect(new Date(chart.end).toISOString()).toBe('2026-10-25T10:00:00.000Z');
  expect(chart.end - chart.data[39].timestamp).toBe(QUARTER_MS);
  expect(chart.ticks[0]).toBe(chart.start);
  expect(chart.ticks.at(-1)).toBe(chart.end);
  expect(formatChartTick(chart.start, 'Europe/Helsinki')).toBe('03:00 UTC+3');
  expect(formatChartTick(chart.start + 3_600_000, 'Europe/Helsinki')).toBe('03:00 UTC+2');
  expect(formatChartTick(chart.start, 'UTC')).toBe('00:00 UTC');
});
