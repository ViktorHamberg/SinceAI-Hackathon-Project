import type { ForecastResponse } from '../api/forecast';

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
