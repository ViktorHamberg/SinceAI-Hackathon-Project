import { describe, expect, it, vi } from 'vitest';
import { fetchForecast, parseForecast, requestErrorMessage } from './forecast';
import { fixture, jsonResponse } from '../test/fixture';

describe('v1 response boundary', () => {
  it('preserves every value, including negative prices and optional nulls', () => {
    const response = fixture();
    expect(parseForecast(response)).toEqual(response);
    expect(parseForecast(fixture('2026-10-25T00:00:00Z')).points).toHaveLength(40);
  });

  const invalidCases: [string, (value: ReturnType<typeof fixture>) => void][] = [
    ['incomplete horizon', (v) => v.points.pop()],
    ['out-of-order quarters', (v) => v.points.reverse()],
    ['wrong step', (v) => { v.points[0].step = 2; }],
    ['wrong delivery', (v) => { v.points[0].delivery_start_utc = v.points[1].delivery_start_utc; }],
    ['naive origin', (v) => { v.forecast_origin_utc = '2026-09-06T21:00:00'; }],
    ['rolled calendar date', (v) => { v.generated_at_utc = '2026-02-30T00:00:00Z'; }],
    ['future fit', (v) => { v.fit_cutoff_utc = '2026-09-07T00:00:00Z'; }],
    ['future data cutoff', (v) => { v.points[0].data_cutoff_utc = '2026-09-07T00:00:00Z'; }],
    ['non-finite price', (v) => { v.points[0].p10 = NaN; }],
    ['crossed quantiles', (v) => { v.points[0].p10 = 100; }],
    ['invalid probability', (v) => { v.points[0].p_up = 1.1; }],
    ['direction total', (v) => { v.points[0].p_none = .9; }],
    ['overlapping spike total', (v) => { v.points[0].p_spike_high = .95; }],
    ['unexpected source field', (v) => { Object.assign(v.points[0], { spot_price: 'SYNTHETIC_RESTRICTED_SENTINEL' }); }],
    ['unexpected envelope field', (v) => { Object.assign(v, { actuals: [] }); }],
    ['missing identity', (v) => { v.engine_revision = ''; }],
  ];
  it.each(invalidCases)('rejects %s without exposing diagnostics', (_, mutate) => {
    const value = fixture();
    mutate(value);
    expect(() => parseForecast(value)).toThrow('incomplete or unsupported forecast');
  });
  it.each([null, [], {}, 'raw server diagnostics'])('rejects non-envelope %j', (value) => {
    expect(() => parseForecast(value)).toThrow();
  });
});

describe('HTTP retrieval', () => {
  it('uses only the relative forecast endpoint without caching', async () => {
    const mock = vi.fn().mockResolvedValue(jsonResponse());
    vi.stubGlobal('fetch', mock);
    expect(await fetchForecast()).toEqual(fixture());
    expect(mock).toHaveBeenCalledWith('/api/forecast', expect.objectContaining({ cache: 'no-store', signal: expect.any(AbortSignal) }));
  });
  it('does not read or display error bodies', async () => {
    const json = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json }));
    await expect(fetchForecast()).rejects.toThrow('service is unavailable');
    expect(json).not.toHaveBeenCalled();
    expect(requestErrorMessage(new Error('PRIVATE PATH / secret'))).not.toContain('PRIVATE');
  });
  it('sanitizes network and JSON failures', async () => {
    const mock = vi.fn().mockRejectedValueOnce(new Error('PRIVATE NETWORK DETAIL'))
      .mockResolvedValueOnce(new Response('PRIVATE INVALID JSON', { status: 200 }));
    vi.stubGlobal('fetch', mock);
    await expect(fetchForecast()).rejects.toThrow('Could not connect');
    await expect(fetchForecast()).rejects.toThrow('incomplete or unsupported');
  });
  it('times out and aborts a stalled request', async () => {
    vi.useFakeTimers();
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      requestSignal = options.signal as AbortSignal;
      requestSignal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const assertion = expect(fetchForecast()).rejects.toThrow('timed out');
    await vi.advanceTimersByTimeAsync(15_000);
    await assertion;
    expect(requestSignal?.aborted).toBe(true);
  });
  it('propagates caller cancellation to fetch', async () => {
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise((_resolve, reject) => {
      requestSignal = options.signal as AbortSignal;
      requestSignal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const controller = new AbortController();
    const assertion = expect(fetchForecast(controller.signal)).rejects.toThrow('Aborted');
    controller.abort();
    await assertion;
    expect(requestSignal?.aborted).toBe(true);
  });
});
