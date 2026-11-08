import { expect, it, vi } from 'vitest';
import { fetchHistory, parseHistory } from './forecast';
import { fixture, historyFixture, jsonResponse } from '../test/fixture';

it('preserves all quarters, independent missing outcomes, negative prices and inclusive coverage', () => {
  const forecast = fixture();
  const history = historyFixture(forecast);
  expect(parseHistory(history, forecast)).toEqual(history);
  expect(history.metrics.matched_price_count).toBe(3);
  expect(history.metrics.matched_direction_count).toBe(4);
  expect(history.metrics.coverage_p10_p90).toBe(2 / 3);
  expect(history.metrics.mae_p50).toBeCloseTo((14.469134 + 43.864198 + 195.876544) / 3, 10);
  expect(parseHistory(historyFixture(forecast, []), forecast).metrics.mae_p50).toBeNull();
});

it.each([
  ['origin', (v) => { v.forecast_origin_utc = '2026-09-06T22:00:00Z'; }],
  ['run', (v) => { v.run_id = '00000000-0000-4000-8000-000000000099'; }],
  ['revision', (v) => { v.engine_revision = `sha256:${'b'.repeat(64)}`; }],
  ['generation', (v) => { v.generated_at_utc = '2026-11-07T13:00:00Z'; }],
  ['fit cutoff', (v) => { v.fit_cutoff_utc = '2026-09-06T20:00:00Z'; }],
  ['model', (v) => { v.model_id = 'other'; }],
  ['predictor', (v) => { v.predictor_id = 'other'; }],
  ['missing row', (v) => { v.points.pop(); }],
  ['wrong timestamp', (v) => { v.points[0].delivery_start_utc = v.points[1].delivery_start_utc; }],
  ['wrong step', (v) => { v.points[0].step = 2; }],
  ['infinite price', (v) => { v.points[0].actual_imbalance_price = Infinity; }],
  ['bad direction', (v) => { Object.assign(v.points[0], { actual_direction: 'PRIVATE' }); }],
  ['private field', (v) => { Object.assign(v.points[0], { spot_price: 'INVENTED_RESTRICTED' }); }],
  ['extra envelope', (v) => { Object.assign(v, { private_path: 'PRIVATE' }); }],
  ['bad metrics', (v) => { v.metrics.mae_p50 = 0; }],
  ['incorrect counts', (v) => { v.metrics.missing_price_count = 0; }],
  ['incorrect coverage', (v) => { v.metrics.coverage_p10_p90 = .5; }],
  ['bad snapshot', (v) => { v.actuals_snapshot_id = 'PRIVATE'; }],
  ['naive loaded time', (v) => { v.actuals_loaded_at_utc = '2026-11-08T00:00:00'; }],
] satisfies [string, (value: ReturnType<typeof historyFixture>) => void][])(
  'rejects %s without displaying diagnostics', (_name, mutate) => {
    const value = historyFixture(); mutate(value);
    expect(() => parseHistory(value, fixture())).toThrow('incomplete or unsupported');
  },
);

it('retrieves only the selected history with no caching and sanitizes HTTP error bodies', async () => {
  const history = historyFixture();
  const json = vi.fn();
  const fetch = vi.fn().mockResolvedValueOnce(jsonResponse(history)).mockResolvedValueOnce({ ok: false, json });
  vi.stubGlobal('fetch', fetch);
  expect(await fetchHistory(fixture())).toEqual(history);
  expect(fetch).toHaveBeenCalledWith('/api/history?origin=2026-09-06T21%3A00%3A00Z', expect.objectContaining({ cache: 'no-store' }));
  await expect(fetchHistory(fixture())).rejects.toThrow('service is unavailable');
  expect(json).not.toHaveBeenCalled();
});
