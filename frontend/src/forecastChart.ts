import type { ForecastPoint, HistoryPoint } from './api/forecast';
import type { DisplayZone } from './time';

export const QUARTER_MS = 15 * 60 * 1000;
export const CHART_MARGIN = { top: 12, right: 12, bottom: 8, left: 0 };
export const PRICE_AXIS_WIDTH = 58;
export const TIME_AXIS_HEIGHT = 48;
const tickFormatters = new Map<DisplayZone, Intl.DateTimeFormat>();

export function quarterAtPosition(x: number, y: number, width: number, height: number, count: number): number | null {
  if (![x, y, width, height].every(Number.isFinite) || count < 1) return null;
  const left = CHART_MARGIN.left + PRICE_AXIS_WIDTH;
  const right = width - CHART_MARGIN.right;
  const bottom = height - CHART_MARGIN.bottom - TIME_AXIS_HEIGHT;
  if (right <= left || bottom <= CHART_MARGIN.top || x < left || x > right || y < CHART_MARGIN.top || y > bottom) return null;
  return Math.min(count - 1, Math.floor((x - left) / (right - left) * count));
}

export function buildChartData(points: ForecastPoint[], outcomes?: HistoryPoint[]) {
  const data = points.map((point, index) => ({
    timestamp: Date.parse(point.delivery_start_utc),
    band: [point.p10, point.p90] as [number, number],
    p50: point.p50,
    actual: outcomes?.[index].actual_imbalance_price ?? null,
    point,
  }));
  const start = data[0].timestamp;
  const end = data[data.length - 1].timestamp + QUARTER_MS;
  const actualPrices = data.flatMap((row) => row.actual === null ? [] : [row.actual]);
  const low = Math.min(...points.map((point) => point.p10), ...actualPrices);
  const high = Math.max(...points.map((point) => point.p90), ...actualPrices);
  const padding = Math.max((high - low) * .08, 1);
  const targetStep = (high - low + 2 * padding) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(targetStep));
  const step = [1, 2, 5, 10].find((factor) => factor * magnitude >= targetStep)! * magnitude;
  const firstTick = Math.floor((low - padding) / step);
  const lastTick = Math.ceil((high + padding) / step);
  const priceTicks = Array.from({ length: lastTick - firstTick + 1 }, (_, index) =>
    Number(((firstTick + index) * step).toPrecision(12)));
  return {
    data, start, end,
    ticks: Array.from({ length: 6 }, (_, index) => start + index * 2 * 60 * 60 * 1000),
    priceDomain: [priceTicks[0], priceTicks[priceTicks.length - 1]] as [number, number],
    priceTicks,
  };
}

export function formatChartTick(timestamp: number, zone: DisplayZone): string {
  let formatter = tickFormatters.get(zone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-GB', {
      timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'shortOffset',
    });
    tickFormatters.set(zone, formatter);
  }
  return formatter.format(new Date(timestamp)).replace('GMT', 'UTC');
}
