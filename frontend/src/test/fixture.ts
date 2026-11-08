import type { ForecastResponse, HistoryResponse, OriginsResponse } from '../api/forecast';

/** Invented values only. Never replace this with exported challenge data. */
export function fixture(origin = '2026-09-06T21:00:00Z'): ForecastResponse {
  return {
    schema_version: '1.0', run_id: '00000000-0000-4000-8000-000000000001',
    model_id: 'persistence-v1', predictor_id: 'persistence', engine_revision: `sha256:${'a'.repeat(64)}`,
    generated_at_utc: '2026-11-07T12:00:00Z', forecast_origin_utc: origin, fit_cutoff_utc: origin,
    points: Array.from({ length: 40 }, (_, index) => ({
      forecast_origin_utc: origin,
      delivery_start_utc: new Date(Date.parse(origin) + index * 900_000).toISOString().replace('.000Z', 'Z'),
      step: index + 1, p10: -12.345678 + index, p50: 2.123456 + index, p90: 45.987654 + index,
      p_up: .4, p_down: .5, p_none: .1, p_spike_high: .2, p_spike_low: .1,
      data_cutoff_utc: null, top_drivers: null,
    })),
  };
}

export function jsonResponse(value: unknown = fixture()): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

export function originsFixture(origins = ['2026-09-06T21:00:00Z', '2026-09-06T22:00:00Z', '2026-10-03T21:00:00Z']): OriginsResponse {
  const { forecast_origin_utc: _origin, points: _points, ...identity } = fixture();
  return { ...identity, default_origin_utc: origins[0], origins };
}

export function selectedFixture(origin: string): ForecastResponse {
  return { ...fixture(origin), fit_cutoff_utc: fixture().fit_cutoff_utc };
}

export function historyFixture(forecast = fixture(), prices: (number | null)[] =
  [forecast.points[0].p10, forecast.points[1].p90, 200]): HistoryResponse {
  const points = forecast.points.map((point, index) => ({
    delivery_start_utc: point.delivery_start_utc, step: point.step,
    actual_imbalance_price: prices[index] ?? null,
    actual_direction: index < 4 ? (['up', 'down', 'none'] as const)[index % 3] : null,
  }));
  const matched = points.filter((point) => point.actual_imbalance_price !== null);
  const covered = matched.filter((point) => forecast.points[point.step - 1].p10 <= point.actual_imbalance_price! &&
    point.actual_imbalance_price! <= forecast.points[point.step - 1].p90).length;
  return {
    ...forecast, comparison_mode: 'retrospective',
    actuals_snapshot_id: '00000000-0000-4000-8000-000000000002', actuals_loaded_at_utc: '2026-11-08T00:00:00Z',
    metrics: {
      total_quarters: 40, matched_price_count: matched.length, missing_price_count: 40 - matched.length,
      matched_direction_count: 4, missing_direction_count: 36, covered_price_count: covered,
      mae_p50: matched.length ? matched.reduce((sum, point) => sum + Math.abs(point.actual_imbalance_price! - forecast.points[point.step - 1].p50), 0) / matched.length : null,
      coverage_p10_p90: matched.length ? covered / matched.length : null,
    }, points,
  };
}
