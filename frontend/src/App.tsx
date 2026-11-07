import { useEffect, useState } from 'react';
import { fetchForecast, requestErrorMessage } from './api/forecast';
import type { ForecastResponse } from './api/forecast';
import ForecastTable from './components/ForecastTable';
import { deliveryWindowEnd, formatTimestamp } from './time';
import type { DisplayZone } from './time';
import './App.css';

type LoadState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; forecast: ForecastResponse };

function Timestamp({ value, zone }: { value: string; zone: DisplayZone }) {
  return <time dateTime={value}>{formatTimestamp(value, zone)}</time>;
}

export default function App() {
  const [attempt, setAttempt] = useState(0);
  const [zone, setZone] = useState<DisplayZone>('Europe/Helsinki');
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setState({ status: 'loading' });
    fetchForecast(controller.signal).then(
      (forecast) => { if (active) setState({ status: 'ready', forecast }); },
      (error: unknown) => {
        if (active && !controller.signal.aborted) setState({ status: 'error', message: requestErrorMessage(error) });
      },
    );
    return () => { active = false; controller.abort(); };
  }, [attempt]);

  function reload() {
    if (state.status === 'loading') return;
    setState({ status: 'loading' });
    setAttempt((value) => value + 1);
  }

  return (
    <>
      <a className="skip-link" href="#forecast-content">Skip to forecast</a>
      <header className="app-header">
        <div className="header-inner">
          <div className="brand-name">Turku Energia<span>Since AI 2026 challenge</span></div>
          <span className="workspace-name">Finnish electricity markets</span>
        </div>
      </header>

      <main id="forecast-content" className="workspace" tabIndex={-1}>
        <div className="workspace-heading">
          <div>
            <p className="workspace-context">Historical replay / Finland</p>
            <h1>Imbalance price forecast</h1>
          </div>
          <button className="reload-button" type="button" aria-disabled={state.status === 'loading'} onClick={reload}>
            {state.status === 'error' ? 'Retry connection' : 'Reload forecast'}
          </button>
        </div>

        <div className="view-toolbar">
          <p>10-hour horizon <span aria-hidden="true">/</span> 15-minute resolution</p>
          <div className="time-controls" role="group" aria-labelledby="time-label">
            <span id="time-label">Display time</span>
            <div className="time-buttons">
              <button type="button" aria-pressed={zone === 'Europe/Helsinki'} onClick={() => setZone('Europe/Helsinki')}>Helsinki</button>
              <button type="button" aria-pressed={zone === 'UTC'} onClick={() => setZone('UTC')}>UTC</button>
            </div>
          </div>
        </div>

        {state.status === 'loading' && <section className="feedback" role="status" aria-live="polite">
          <span className="feedback-label">Forecast service</span>
          <h2>Loading forecast</h2>
          <p>Retrieving the prepared forecast from the local service.</p>
        </section>}

        {state.status === 'error' && <section className="feedback feedback-error" role="alert">
          <span className="feedback-label">Connection needs attention</span>
          <h2>Forecast unavailable</h2>
          <p>{state.message}</p>
          <p className="feedback-help">Use Retry connection above when the service is ready.</p>
        </section>}

        {state.status === 'ready' && <>
          <section className="forecast-overview" aria-label="Forecast context">
            <dl>
              <div><dt>Forecast origin</dt><dd><Timestamp value={state.forecast.forecast_origin_utc} zone={zone} /></dd></div>
              <div><dt>Delivery window ends</dt><dd><Timestamp value={deliveryWindowEnd(state.forecast.forecast_origin_utc)} zone={zone} /></dd></div>
              <div className="model-context"><dt>Model</dt><dd>{state.forecast.model_id === 'persistence-v1' ? 'Persistence baseline' : state.forecast.model_id}</dd></div>
            </dl>
          </section>

          <ForecastTable points={state.forecast.points} zone={zone} />

          <details className="run-details">
            <summary>Model and run details</summary>
            <div className="run-details-content">
              <dl>
                <div><dt>Model recipe</dt><dd><code>{state.forecast.model_id}</code></dd></div>
                <div><dt>Predictor</dt><dd><code>{state.forecast.predictor_id}</code></dd></div>
                <div><dt>Run ID</dt><dd><code>{state.forecast.run_id}</code></dd></div>
                <div><dt>Prepared at</dt><dd><Timestamp value={state.forecast.generated_at_utc} zone={zone} /></dd></div>
                <div><dt>Fitting cutoff</dt><dd><Timestamp value={state.forecast.fit_cutoff_utc} zone={zone} /></dd></div>
                <div><dt>Engine source</dt><dd><code>{state.forecast.engine_revision}</code></dd></div>
              </dl>
              <p>Preparation time identifies this application run. The forecast origin identifies the historical moment being reviewed.</p>
            </div>
          </details>
        </>}
      </main>
      <footer className="app-footer"><span>Historical forecasts. Actual outcomes are not displayed.</span><span>Challenge demonstration · No live market feed</span></footer>
    </>
  );
}
