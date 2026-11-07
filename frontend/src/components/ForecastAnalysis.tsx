import { lazy, Suspense, useMemo, useState } from 'react';
import type { ForecastPoint } from '../api/forecast';
import { summarizeForecast } from '../forecastSummary';
import type { DisplayZone } from '../time';
import ChartBoundary from './ChartBoundary';
import RiskSummary from './RiskSummary';

const ForecastChart = lazy(() => import('./ForecastChart'));
const ProbabilityChart = lazy(() => import('./ProbabilityChart'));

export default function ForecastAnalysis({ points, zone }: { points: ForecastPoint[]; zone: DisplayZone }) {
  const [selectedIndex, onSelect] = useState(0);
  const summary = useMemo(() => summarizeForecast(points), [points]);
  const props = { points, zone, selectedIndex, onSelect };
  return <>
    <RiskSummary {...props} summary={summary} />
    <ChartBoundary>
      <Suspense fallback={<section className="chart-loading" role="status">Loading price chart. Exact prices are available in the table below.</section>}><ForecastChart {...props} /></Suspense>
    </ChartBoundary>
    <ChartBoundary title="Probability timelines unavailable" message="Use the delivery selector and exact probabilities in the risk summary above. Reload the page to try loading the timelines again.">
      <Suspense fallback={<section className="chart-loading" role="status">Loading probability timelines. Selected probabilities are available in the risk summary above.</section>}><ProbabilityChart {...props} /></Suspense>
    </ChartBoundary>
  </>;
}
