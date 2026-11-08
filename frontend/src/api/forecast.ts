/** Public application JSON contract. Never import source datasets into the client. */
export interface ForecastPoint {
  forecast_origin_utc: string;
  delivery_start_utc: string;
  step: number;
  p10: number;
  p50: number;
  p90: number;
  p_up: number;
  p_down: number;
  p_none: number;
  p_spike_high: number;
  p_spike_low: number;
  data_cutoff_utc: string | null;
  top_drivers: string | null;
}

export interface ForecastResponse {
  schema_version: '1.0';
  run_id: string;
  model_id: string;
  predictor_id: string;
  engine_revision: string;
  generated_at_utc: string;
  forecast_origin_utc: string;
  fit_cutoff_utc: string;
  points: ForecastPoint[];
}

export interface OriginsResponse extends Omit<ForecastResponse, 'forecast_origin_utc' | 'points'> {
  default_origin_utc: string;
  origins: string[];
}

export interface HistoryPoint {
  delivery_start_utc: string;
  step: number;
  actual_imbalance_price: number | null;
  actual_direction: 'up' | 'down' | 'none' | null;
}

export interface HistoryResponse extends Omit<ForecastResponse, 'points'> {
  comparison_mode: 'retrospective';
  actuals_snapshot_id: string;
  actuals_loaded_at_utc: string;
  metrics: {
    total_quarters: number;
    matched_price_count: number;
    missing_price_count: number;
    matched_direction_count: number;
    missing_direction_count: number;
    mae_p50: number | null;
    coverage_p10_p90: number | null;
    covered_price_count: number;
  };
  points: HistoryPoint[];
}

type FailureKind = 'network' | 'http' | 'invalid' | 'timeout';
const messages: Record<FailureKind, string> = {
  network: 'Could not connect to the forecast service. Check that the backend is running, then retry.',
  http: 'The forecast service is unavailable. Wait for backend startup to finish, then retry.',
  invalid: 'The service returned an incomplete or unsupported forecast. No forecast has been displayed.',
  timeout: 'The forecast request timed out. Check the backend, then retry.',
};

export class ForecastRequestError extends Error {
  readonly kind: FailureKind;
  constructor(kind: FailureKind) {
    super(messages[kind]);
    this.name = 'ForecastRequestError';
    this.kind = kind;
  }
}

export function requestErrorMessage(error: unknown): string {
  return error instanceof ForecastRequestError ? messages[error.kind] : messages.network;
}

const identityKeys = [
  'schema_version', 'run_id', 'model_id', 'predictor_id', 'engine_revision',
  'generated_at_utc', 'fit_cutoff_utc',
];
const envelopeKeys = [...identityKeys, 'forecast_origin_utc', 'points'];
const pointKeys = [
  'forecast_origin_utc', 'delivery_start_utc', 'step', 'p10', 'p50', 'p90',
  'p_up', 'p_down', 'p_none', 'p_spike_high', 'p_spike_low', 'data_cutoff_utc', 'top_drivers',
];
const identifier = /^[a-z][a-z0-9_-]{0,63}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const utc = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

function requireValid(condition: boolean): asserts condition {
  if (!condition) throw new ForecastRequestError('invalid');
}

function objectWithKeys(value: unknown, keys: string[]): Record<string, unknown> {
  requireValid(value !== null && typeof value === 'object' && !Array.isArray(value));
  const object = value as Record<string, unknown>;
  requireValid(Object.keys(object).length === keys.length && keys.every((key) => Object.hasOwn(object, key)));
  return object;
}

function timestamp(value: unknown): number {
  requireValid(typeof value === 'string' && utc.test(value));
  const milliseconds = Date.parse(value);
  requireValid(Number.isFinite(milliseconds) && new Date(milliseconds).toISOString().replace('.000Z', 'Z') === value);
  return milliseconds;
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function validateIdentity(envelope: Record<string, unknown>): void {
  requireValid(envelope.schema_version === '1.0');
  requireValid(typeof envelope.run_id === 'string' && uuid.test(envelope.run_id));
  requireValid(typeof envelope.model_id === 'string' && identifier.test(envelope.model_id));
  requireValid(typeof envelope.predictor_id === 'string' && identifier.test(envelope.predictor_id));
  requireValid(typeof envelope.engine_revision === 'string' && /^sha256:[0-9a-f]{64}$/.test(envelope.engine_revision));
  timestamp(envelope.generated_at_utc);
  requireValid(timestamp(envelope.fit_cutoff_utc) % 3_600_000 === 0);
}

/** Fail closed on malformed v1 responses; no repairs, partial horizons or raw diagnostics. */
export function parseForecast(value: unknown): ForecastResponse {
  const envelope = objectWithKeys(value, envelopeKeys);
  validateIdentity(envelope);
  const origin = timestamp(envelope.forecast_origin_utc);
  requireValid(origin % 3_600_000 === 0 && timestamp(envelope.fit_cutoff_utc) <= origin);
  requireValid(Array.isArray(envelope.points) && envelope.points.length === 40);

  for (const [index, value] of envelope.points.entries()) {
    const point = objectWithKeys(value, pointKeys);
    requireValid(point.forecast_origin_utc === envelope.forecast_origin_utc);
    requireValid(point.step === index + 1 && timestamp(point.delivery_start_utc) === origin + index * 900_000);
    requireValid(finite(point.p10) && finite(point.p50) && finite(point.p90));
    requireValid(point.p10 <= point.p50 && point.p50 <= point.p90);
    const probabilities = [point.p_up, point.p_down, point.p_none, point.p_spike_high, point.p_spike_low];
    requireValid(probabilities.every((p) => finite(p) && p >= 0 && p <= 1));
    const [up, down, none, high, low] = probabilities as number[];
    requireValid(Math.abs(up + down + none - 1) <= .001 + 1e-12 && high + low <= 1.001 + 1e-12);
    requireValid(point.data_cutoff_utc === null || timestamp(point.data_cutoff_utc) <= origin);
    requireValid(point.top_drivers === null || typeof point.top_drivers === 'string');
  }
  // Only the exact allowlisted JSON structure reaches application state.
  return envelope as unknown as ForecastResponse;
}

export function parseOrigins(value: unknown): OriginsResponse {
  const catalog = objectWithKeys(value, [...identityKeys, 'default_origin_utc', 'origins']);
  validateIdentity(catalog);
  requireValid(Array.isArray(catalog.origins) && catalog.origins.length >= 1 && catalog.origins.length <= 28);
  let previous = -Infinity;
  for (const origin of catalog.origins) {
    const time = timestamp(origin);
    requireValid(time % 3_600_000 === 0 && time >= timestamp(catalog.fit_cutoff_utc) && time > previous);
    previous = time;
  }
  requireValid(catalog.default_origin_utc === catalog.origins[0]);
  return catalog as unknown as OriginsResponse;
}

export async function fetchForecast(signal?: AbortSignal): Promise<ForecastResponse> {
  return fetchValidated('/api/forecast', parseForecast, signal);
}

export async function fetchOrigins(signal?: AbortSignal): Promise<OriginsResponse> {
  return fetchValidated('/api/origins', parseOrigins, signal);
}

export async function fetchSelectedForecast(catalog: OriginsResponse, origin: string, signal?: AbortSignal): Promise<ForecastResponse> {
  requireValid(catalog.origins.includes(origin));
  const forecast = await fetchValidated(`/api/forecast?${new URLSearchParams({ origin })}`, parseForecast, signal);
  requireValid(forecast.forecast_origin_utc === origin);
  requireValid(identityKeys.every((key) => forecast[key as keyof ForecastResponse] === catalog[key as keyof OriginsResponse]));
  return forecast;
}

export function parseHistory(value: unknown, forecast: ForecastResponse): HistoryResponse {
  const history = objectWithKeys(value, [...envelopeKeys, 'comparison_mode', 'actuals_snapshot_id', 'actuals_loaded_at_utc', 'metrics']);
  validateIdentity(history);
  requireValid([...identityKeys, 'forecast_origin_utc'].every((key) => history[key] === forecast[key as keyof ForecastResponse]));
  requireValid(history.comparison_mode === 'retrospective');
  requireValid(typeof history.actuals_snapshot_id === 'string' && uuid.test(history.actuals_snapshot_id));
  timestamp(history.actuals_loaded_at_utc);
  requireValid(Array.isArray(history.points) && history.points.length === 40);
  let matchedPrices = 0, matchedDirections = 0, covered = 0, errorSum = 0;
  for (const [index, value] of history.points.entries()) {
    const point = objectWithKeys(value, ['delivery_start_utc', 'step', 'actual_imbalance_price', 'actual_direction']);
    const predicted = forecast.points[index];
    requireValid(point.step === predicted.step && point.delivery_start_utc === predicted.delivery_start_utc);
    requireValid(point.actual_imbalance_price === null || finite(point.actual_imbalance_price));
    requireValid(point.actual_direction === null || ['up', 'down', 'none'].includes(point.actual_direction as string));
    if (point.actual_imbalance_price !== null) {
      const price = point.actual_imbalance_price as number;
      matchedPrices++;
      errorSum += Math.abs(price - predicted.p50);
      covered += Number(predicted.p10 <= price && price <= predicted.p90);
    }
    matchedDirections += Number(point.actual_direction !== null);
  }
  const metrics = objectWithKeys(history.metrics, ['total_quarters', 'matched_price_count', 'missing_price_count',
    'matched_direction_count', 'missing_direction_count', 'mae_p50', 'coverage_p10_p90', 'covered_price_count']);
  requireValid(metrics.total_quarters === 40 && metrics.matched_price_count === matchedPrices && metrics.missing_price_count === 40 - matchedPrices);
  requireValid(metrics.matched_direction_count === matchedDirections && metrics.missing_direction_count === 40 - matchedDirections);
  requireValid(metrics.covered_price_count === covered);
  if (matchedPrices === 0) {
    requireValid(metrics.mae_p50 === null && metrics.coverage_p10_p90 === null);
  } else {
    const expectedMae = errorSum / matchedPrices;
    requireValid(finite(metrics.mae_p50) && Number.isFinite(expectedMae) &&
      Math.abs(metrics.mae_p50 - expectedMae) <= 32 * Number.EPSILON * Math.max(1, expectedMae));
    requireValid(finite(metrics.coverage_p10_p90) && Math.abs(metrics.coverage_p10_p90 - covered / matchedPrices) <= Number.EPSILON);
  }
  return history as unknown as HistoryResponse;
}

export async function fetchHistory(forecast: ForecastResponse, signal?: AbortSignal): Promise<HistoryResponse> {
  return fetchValidated(`/api/history?${new URLSearchParams({ origin: forecast.forecast_origin_utc })}`,
    (value) => parseHistory(value, forecast), signal);
}

async function fetchValidated<T>(path: string, parse: (value: unknown) => T, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 15_000);
  try {
    const response = await fetch(path, {
      signal: controller.signal, cache: 'no-store', headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new ForecastRequestError('http');
    let value: unknown;
    try { value = await response.json(); }
    catch { throw new ForecastRequestError('invalid'); }
    return parse(value);
  } catch (error) {
    if (signal?.aborted) throw error;
    if (timedOut) throw new ForecastRequestError('timeout');
    if (error instanceof ForecastRequestError) throw error;
    throw new ForecastRequestError('network');
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', cancel);
  }
}
