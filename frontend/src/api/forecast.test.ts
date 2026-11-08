import { describe, expect, it, vi } from 'vitest';
import { fetchForecast, fetchOrigins, fetchSelectedForecast, parseForecast, parseOrigins, requestErrorMessage } from './forecast';
import { fixture, jsonResponse, originsFixture, selectedFixture } from '../test/fixture';

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

describe('origin catalog and selected snapshots', () => {
  it('preserves the exact sorted catalog and rejects malformed or restricted fields', () => {
    const catalog = originsFixture();
    expect(parseOrigins(catalog)).toEqual(catalog);
    const mutations = [
      { origins: [] }, { origins: [...catalog.origins].reverse() },
      { origins: [catalog.origins[0], catalog.origins[0]] },
      { origins: ['2026-09-06T21:15:00Z'] }, { origins: ['2026-09-06T21:00:00'] },
      { default_origin_utc: catalog.origins[1] }, { fit_cutoff_utc: '2026-09-07T00:00:00Z' },
      { spot_price: 'SYNTHETIC_PRIVATE' }, { run_id: 'private source text' },
      { origins: Array.from({ length: 29 }, (_, i) => new Date(Date.parse(catalog.origins[0]) + i * 3600_000).toISOString().replace('.000Z', 'Z')) },
    ];
    for (const mutation of mutations) expect(() => parseOrigins({ ...catalog, ...mutation })).toThrow('incomplete or unsupported');
  });

  it('accepts the full daily replay catalog', () => {
    const origins = Array.from({ length: 28 }, (_, day) =>
      new Date(Date.parse('2026-09-06T21:00:00Z') + day * 86_400_000).toISOString().replace('.000Z', 'Z'));
    const catalog = originsFixture(origins);
    expect(parseOrigins(catalog).origins).toEqual(origins);
  });

  it('fetches the catalog and URL-encoded selected forecast without altering prices', async () => {
    const catalog = originsFixture();
    const origin = catalog.origins[1];
    const forecast = selectedFixture(origin);
    const mock = vi.fn().mockResolvedValueOnce(jsonResponse(catalog)).mockResolvedValueOnce(jsonResponse(forecast));
    vi.stubGlobal('fetch', mock);
    expect(await fetchOrigins()).toEqual(catalog);
    expect(await fetchSelectedForecast(catalog, origin)).toEqual(forecast);
    expect(mock.mock.calls.map((call) => call[0])).toEqual(['/api/origins', '/api/forecast?origin=2026-09-06T22%3A00%3A00Z']);
  });

  it('rejects a wrong origin or changed run identity and never requests an uncached origin', async () => {
    const catalog = originsFixture();
    const origin = catalog.origins[1];
    const forecast = selectedFixture(origin);
    for (const mutation of [{ ...fixture() }, { ...forecast, run_id: '00000000-0000-4000-8000-000000000002' },
      { ...forecast, engine_revision: `sha256:${'b'.repeat(64)}` }, { ...forecast, generated_at_utc: '2026-11-07T12:01:00Z' }]) {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(mutation)));
      await expect(fetchSelectedForecast(catalog, origin)).rejects.toThrow('incomplete or unsupported');
    }
    const mock = vi.fn();
    vi.stubGlobal('fetch', mock);
    await expect(fetchSelectedForecast(catalog, '2026-09-08T00:00:00Z')).rejects.toThrow('incomplete or unsupported');
    expect(mock).not.toHaveBeenCalled();
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
