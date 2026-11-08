import { lazy, Suspense, useMemo, useState } from 'react';
import type { ForecastResponse } from '../api/forecast';
import { summarizeForecast } from '../forecastSummary';
import type { DisplayZone } from '../time';
import ChartBoundary from './ChartBoundary';
import RiskSummary from './RiskSummary';
import HistoricalReview from './HistoricalReview';
import './ForecastAnalysis.css';

const ForecastChart = lazy(() => import('./ForecastChart'));
const ProbabilityChart = lazy(() => import('./ProbabilityChart'));

export default function ForecastAnalysis({ forecast, zone, comparisonEnabled, onComparisonEnabled }: {
  forecast: ForecastResponse; zone: DisplayZone; comparisonEnabled: boolean; onComparisonEnabled: (enabled: boolean) => void;
}) {
  const points = forecast.points;
  const [selectedIndex, onSelect] = useState(0);
  const summary = useMemo(() => summarizeForecast(points), [points]);
  const props = { points, zone, selectedIndex, onSelect };
  return <div className="analysis-grid">
    <div className="analysis-price">
      <HistoricalReview forecast={forecast} enabled={comparisonEnabled} onEnabled={onComparisonEnabled} zone={zone} selectedIndex={selectedIndex}>
        {(history, control) => <ChartBoundary recovery={control}>
          <Suspense fallback={<section className="chart-loading"><p role="status">Loading price chart. Open Raw Data for the 40-quarter price table.</p>{control}</section>}>
            <ForecastChart {...props} history={history} comparisonControl={control} />
          </Suspense>
        </ChartBoundary>}
      </HistoricalReview>
    </div>
    <div className="analysis-risk"><RiskSummary {...props} summary={summary} /></div>
    <div className="analysis-probabilities">
      <ChartBoundary title="Probability timelines unavailable" message="Use the delivery selector and exact probabilities in the risk summary above. Reload the page to try loading the timelines again.">
        <Suspense fallback={<section className="chart-loading" role="status">Loading probability timelines. Selected probabilities are available in the risk summary above.</section>}><ProbabilityChart {...props} /></Suspense>
      </ChartBoundary>
    </div>
  </div>;
}
