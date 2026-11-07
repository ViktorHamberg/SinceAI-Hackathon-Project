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

const envelopeKeys = [
  'schema_version', 'run_id', 'model_id', 'predictor_id', 'engine_revision',
  'generated_at_utc', 'forecast_origin_utc', 'fit_cutoff_utc', 'points',
];
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

/** Fail closed on malformed v1 responses; no repairs, partial horizons or raw diagnostics. */
export function parseForecast(value: unknown): ForecastResponse {
  const envelope = objectWithKeys(value, envelopeKeys);
  requireValid(envelope.schema_version === '1.0');
  requireValid(typeof envelope.run_id === 'string' && uuid.test(envelope.run_id));
  requireValid(typeof envelope.model_id === 'string' && identifier.test(envelope.model_id));
  requireValid(typeof envelope.predictor_id === 'string' && identifier.test(envelope.predictor_id));
  requireValid(typeof envelope.engine_revision === 'string' && /^sha256:[0-9a-f]{64}$/.test(envelope.engine_revision));
  timestamp(envelope.generated_at_utc);
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

export async function fetchForecast(signal?: AbortSignal): Promise<ForecastResponse> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener('abort', cancel, { once: true });
  if (signal?.aborted) cancel();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 15_000);
  try {
    const response = await fetch('/api/forecast', {
      signal: controller.signal, cache: 'no-store', headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new ForecastRequestError('http');
    let value: unknown;
    try { value = await response.json(); }
    catch { throw new ForecastRequestError('invalid'); }
    return parseForecast(value);
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
