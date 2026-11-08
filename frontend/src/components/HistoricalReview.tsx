import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { fetchHistory, ForecastRequestError } from '../api/forecast';
import type { ForecastResponse, HistoryResponse } from '../api/forecast';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import { formatThreeDecimals } from '../format';
import './HistoricalReview.css';

type State = { status: 'loading' } | { status: 'error'; message: string } |
  { status: 'ready'; history: HistoryResponse; forecast: ForecastResponse };
const directionLabels = { up: 'Up regulation', down: 'Down regulation', none: 'No dominating mFRR direction' };

function errorMessage(error: unknown): string {
  if (error instanceof ForecastRequestError && error.kind === 'invalid') {
    return 'The outcomes did not match this forecast or had an invalid response. Reload the forecast if the backend was restarted.';
  }
  return 'Could not load actual outcomes. Check that the backend and validation outcomes are available, then retry.';
}

export default function HistoricalReview({ forecast, enabled, onEnabled, zone, selectedIndex, children }: {
  forecast: ForecastResponse; enabled: boolean; onEnabled: (enabled: boolean) => void;
  zone: DisplayZone; selectedIndex: number;
  children: (history: HistoryResponse | undefined, control: ReactNode) => ReactNode;
}) {
  const [state, setState] = useState<State>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const controller = new AbortController();
    setState({ status: 'loading' });
    fetchHistory(forecast, controller.signal).then(
      (history) => { if (active) setState({ status: 'ready', history, forecast }); },
      (error: unknown) => { if (active && !controller.signal.aborted) setState({ status: 'error', message: errorMessage(error) }); },
    );
    return () => { active = false; controller.abort(); };
  }, [enabled, forecast, attempt]);
  const history = enabled && state.status === 'ready' && state.forecast === forecast ? state.history : undefined;
  const selected = history?.points[selectedIndex];
  const control = <button className="history-toggle" type="button" aria-pressed={enabled}
    onClick={() => { setState({ status: 'loading' }); onEnabled(!enabled); }}>Show actual outcomes</button>;
  return <>
    {children(history, control)}
    {enabled && <section className="historical-review" aria-labelledby="history-heading">
      <h3 id="history-heading">Retrospective comparison</h3>
      <p>Actual outcomes were revealed after the forecast issue time. They do not change this forecast.</p>
      {state.status === 'error' ? <div role="alert"><p>{state.message}</p>
        <button type="button" onClick={() => { setState({ status: 'loading' }); setAttempt((value) => value + 1); }}>Retry actual outcomes</button></div>
        : !history ? <p role="status">Loading actual outcomes for this forecast.</p>
        : <>
          <dl className="history-metrics">
            <div><dt>P50 MAE</dt><dd>{history.metrics.mae_p50 === null ? 'Unavailable' : `${formatThreeDecimals(history.metrics.mae_p50)} EUR/MWh`}</dd></div>
            <div><dt>P10–P90 coverage</dt><dd>{history.metrics.coverage_p10_p90 === null ? 'Unavailable' : `${formatThreeDecimals(history.metrics.coverage_p10_p90 * 100)}%`}</dd></div>
            <div><dt>Matched actual prices</dt><dd>{history.metrics.matched_price_count} of 40 quarters</dd></div>
          </dl>
          {history.metrics.matched_price_count === 0 && <p>No actual prices are available for this window. All 40 forecast quarters remain visible.</p>}
          <p className="history-definition">MAE is the mean absolute error of P50. Coverage counts prices within P10–P90, including the boundaries. Both use matched actual prices only; {history.metrics.missing_price_count} prices are missing. These describe this ten-hour window, not the overall model score.</p>
          {selected && <div className="history-selected" role="status" aria-live="polite" aria-atomic="true">
            <p>Observed quarter {selected.step} · <time dateTime={selected.delivery_start_utc}>{formatTimestamp(selected.delivery_start_utc, zone)}</time></p>
            <dl><div><dt>Actual imbalance price</dt><dd>{selected.actual_imbalance_price === null ? 'Unavailable' : `${formatThreeDecimals(selected.actual_imbalance_price)} EUR/MWh`}</dd></div>
              <div><dt>Actual balancing direction</dt><dd>{selected.actual_direction === null ? 'Unavailable' : directionLabels[selected.actual_direction]}</dd></div></dl>
          </div>}
        </>}
    </section>}
  </>;
}
