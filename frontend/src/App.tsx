import { useEffect, useState } from 'react';
import type { MouseEvent } from 'react';
import { fetchOrigins, fetchSelectedForecast, requestErrorMessage } from './api/forecast';
import type { ForecastResponse, OriginsResponse } from './api/forecast';
import ForecastTable from './components/ForecastTable';
import ForecastAnalysis from './components/ForecastAnalysis';
import OriginSelector from './components/OriginSelector';
import { deliveryWindowEnd, formatTimestamp } from './time';
import type { DisplayZone } from './time';
import './App.css';

type LoadState = { status: 'loading' } | { status: 'error'; message: string } | { status: 'ready'; forecast: ForecastResponse };
type CatalogState = { status: 'loading' } | { status: 'error' } | { status: 'ready'; catalog: OriginsResponse };
const views = ['forecast', 'view-2', 'view-3', 'view-4', 'view-5'] as const;
type View = typeof views[number];

function currentView(): View {
  const route = new URLSearchParams(window.location.search).get('view');
  return views.find((view) => view === route) ?? 'forecast';
}

function Timestamp({ value, zone }: { value: string; zone: DisplayZone }) {
  return <time dateTime={value}>{formatTimestamp(value, zone)}</time>;
}

export default function App() {
  const [view, setView] = useState<View>(currentView);
  const [attempt, setAttempt] = useState(0);
  const [zone, setZone] = useState<DisplayZone>('Europe/Helsinki');
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [catalogState, setCatalogState] = useState<CatalogState>({ status: 'loading' });
  const [selectedOrigin, setSelectedOrigin] = useState<string | null>(null);
  const [comparisonEnabled, setComparisonEnabled] = useState(false);
  useEffect(() => {
    const updateView = () => setView(currentView());
    window.addEventListener('popstate', updateView);
    return () => window.removeEventListener('popstate', updateView);
  }, []);

  function navigateView(event: MouseEvent<HTMLAnchorElement>, target: View) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (target === view) return;
    const url = new URL(window.location.href);
    url.searchParams.set('view', target);
    url.hash = '';
    window.history.pushState({}, '', url);
    setView(target);
  }
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setState({ status: 'loading' });
    setCatalogState({ status: 'loading' });
    fetchOrigins(controller.signal).then(
      (catalog) => {
        if (!active) return;
        setSelectedOrigin((previous) => previous !== null && catalog.origins.includes(previous) ? previous : catalog.default_origin_utc);
        setCatalogState({ status: 'ready', catalog });
      },
      (error: unknown) => {
        if (active && !controller.signal.aborted) {
          setCatalogState({ status: 'error' });
          setState({ status: 'error', message: requestErrorMessage(error) });
        }
      },
    );
    return () => { active = false; controller.abort(); };
  }, [attempt]);

  useEffect(() => {
    if (catalogState.status !== 'ready' || selectedOrigin === null) return;
    let active = true;
    const controller = new AbortController();
    setState({ status: 'loading' });
    fetchSelectedForecast(catalogState.catalog, selectedOrigin, controller.signal).then(
      (forecast) => { if (active) setState({ status: 'ready', forecast }); },
      (error: unknown) => {
        if (active && !controller.signal.aborted) setState({ status: 'error', message: requestErrorMessage(error) });
      },
    );
    return () => { active = false; controller.abort(); };
  }, [catalogState, selectedOrigin]);

  function selectOrigin(origin: string) {
    if (origin === selectedOrigin) return;
    setState({ status: 'loading' });
    setSelectedOrigin(origin);
  }

  function reload() {
    if (state.status === 'loading') return;
    setState({ status: 'loading' });
    setCatalogState({ status: 'loading' });
    setAttempt((value) => value + 1);
  }

  return (
    <>
      <a className="skip-link" href="#forecast-content">Skip to content</a>
      <header className="app-header">
        <div className="header-inner">
          <div className="brand-name">Turku Energia<span>Since AI 2026 challenge</span></div>
          <nav className="view-navigation" aria-label="Application views">
            {views.map((item, index) => <a key={item} href={`?view=${item}`} onClick={(event) => navigateView(event, item)} aria-current={view === item ? 'page' : undefined}>
              {item === 'forecast' ? 'Forecast' : item === 'view-2' ? 'Price Drivers' : item === 'view-3' ? 'Raw Data' : `View ${index + 1}`}
            </a>)}
          </nav>
          <span className="workspace-name">Finnish electricity markets</span>
        </div>
      </header>

      <main id="forecast-content" className="workspace" tabIndex={-1}>
        {view !== 'forecast' && view !== 'view-3' && <section className="empty-view" aria-labelledby="empty-view-heading">
          <p className="workspace-context">Historical replay / Finland</p>
          <h1 id="empty-view-heading">{view === 'view-2' ? 'Price Drivers' : `View ${views.indexOf(view) + 1}`}</h1>
          <p>This view is ready for future features.</p>
        </section>}
        <div hidden={view !== 'forecast' && view !== 'view-3'}>
        <div className="workspace-heading">
          <div>
            <p className="workspace-context">Historical replay / Finland</p>
            <h1>{view === 'view-3' ? 'Raw Data' : 'Imbalance price forecast'}</h1>
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

        {catalogState.status === 'ready' && selectedOrigin !== null && <OriginSelector
          key={catalogState.catalog.run_id} origins={catalogState.catalog.origins} selectedOrigin={selectedOrigin}
          displayedOrigin={state.status === 'ready' ? state.forecast.forecast_origin_utc : null}
          loading={state.status === 'loading'} zone={zone} onSelect={selectOrigin} />}

        {state.status === 'loading' && <section className="feedback" role="status" aria-live="polite">
          <span className="feedback-label">Forecast service</span>
          <h2>Loading forecast</h2>
          <p>{catalogState.status === 'loading' ? 'Retrieving available forecast issue times.' : 'Retrieving the selected cached forecast from the local service.'}</p>
        </section>}

        {state.status === 'error' && <section className="feedback feedback-error" role="alert">
          <span className="feedback-label">Connection needs attention</span>
          <h2>Forecast unavailable</h2>
          <p>{state.message}</p>
          <p className="feedback-help">Use Retry connection above when the service is ready. Retrying refreshes the available forecast run.</p>
        </section>}

        {state.status === 'ready' && <>
          <section className="forecast-overview" aria-label="Forecast context">
            <dl>
              <div><dt>Forecast origin</dt><dd><Timestamp value={state.forecast.forecast_origin_utc} zone={zone} /></dd></div>
              <div><dt>Delivery window ends</dt><dd><Timestamp value={deliveryWindowEnd(state.forecast.forecast_origin_utc)} zone={zone} /></dd></div>
              <div className="model-context"><dt>Model</dt><dd>{state.forecast.model_id === 'persistence-v1' ? 'Persistence baseline' : state.forecast.model_id}</dd></div>
            </dl>
          </section>

          <div hidden={view !== 'forecast'}>
            <ForecastAnalysis key={`analysis/${state.forecast.run_id}/${state.forecast.forecast_origin_utc}`} forecast={state.forecast} zone={zone}
              comparisonEnabled={comparisonEnabled} onComparisonEnabled={setComparisonEnabled} />
          </div>
          {view === 'view-3' && <div className="raw-data-panel">
            <ForecastTable key={`table/${state.forecast.run_id}/${state.forecast.forecast_origin_utc}`} points={state.forecast.points} zone={zone} />
          </div>}

          {view === 'forecast' && <details className="run-details">
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
          </details>}
        </>}
        </div>
      </main>
      <footer className="app-footer"><span>Historical forecasts. Optional actual outcomes are retrospective.</span><span>Challenge demonstration · No live market feed</span></footer>
    </>
  );
}
