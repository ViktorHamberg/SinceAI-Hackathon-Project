import { memo } from 'react';
import type { ForecastPoint } from '../api/forecast';
import { directionSeries, formatProbability, highestDirections, spikeSeries } from '../forecastSummary';
import type { ForecastSummary } from '../forecastSummary';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import { formatThreeDecimals } from '../format';
import './RiskSummary.css';

const MaximumSummary = memo(function MaximumSummary({ title, maximum, unit, points, zone, onSelect }: {
  title: string; maximum: ForecastSummary['high']; unit: 'probability' | 'price';
  points: ForecastPoint[]; zone: DisplayZone; onSelect: (index: number) => void;
}) {
  const first = maximum.indices[0];
  return <article className="risk-maximum" aria-label={title}>
    <h3>{title}</h3>
    <p className="risk-value">{unit === 'probability' ? formatProbability(maximum.value) : `${formatThreeDecimals(maximum.value)} EUR/MWh`}</p>
    <button type="button" onClick={() => onSelect(first)}>Inspect quarter {first + 1}<span>{formatTimestamp(points[first].delivery_start_utc, zone)}</span></button>
    {maximum.indices.length === points.length ? <p>All {points.length} quarters share this value.</p>
      : maximum.indices.length > 1 ? <details><summary>{maximum.indices.length} quarters tied for this maximum</summary>
        <ul>{maximum.indices.map((index) => <li key={index}><button type="button" onClick={() => onSelect(index)}>Quarter {index + 1} · {formatTimestamp(points[index].delivery_start_utc, zone)}</button></li>)}</ul>
      </details> : <p>One quarter has this maximum.</p>}
  </article>;
});

export default function RiskSummary({ points, summary, selectedIndex, zone, onSelect }: {
  points: ForecastPoint[]; summary: ForecastSummary; selectedIndex: number; zone: DisplayZone; onSelect: (index: number) => void;
}) {
  const selected = points[selectedIndex];
  const directions = highestDirections(selected);
  return <section className="risk-summary" aria-labelledby="risk-heading">
    <h2 id="risk-heading">Forecast risk summary</h2>
    <p className="risk-intro">Maxima across the selected forecast’s 40 delivery quarters. Each spike probability applies to one quarter, not to an event anywhere across the ten hours.</p>
    <div className="risk-maxima">
      <MaximumSummary title="Highest high-spike probability" maximum={summary.high} unit="probability" points={points} zone={zone} onSelect={onSelect} />
      <MaximumSummary title="Highest low-spike probability" maximum={summary.low} unit="probability" points={points} zone={zone} onSelect={onSelect} />
      <MaximumSummary title="Widest P10–P90 interval" maximum={summary.width} unit="price" points={points} zone={zone} onSelect={onSelect} />
    </div>
    <div className="risk-selected" aria-label="Selected delivery probabilities">
      <label htmlFor="risk-quarter">Inspect delivery quarter</label>
      <select id="risk-quarter" value={selectedIndex} onChange={(event) => onSelect(Number(event.target.value))}>
        {points.map((point, index) => <option key={point.delivery_start_utc} value={index}>Quarter {point.step} · {formatTimestamp(point.delivery_start_utc, zone)}</option>)}
      </select>
      <p>Highest direction probability: <strong>{directions.join(' / ')}{directions.length > 1 ? ' (tie)' : ''}</strong></p>
      <dl className="risk-probabilities">{[...directionSeries, ...spikeSeries].map((series) => <div key={series.key}>
        <dt>{series.label}</dt><dd>{formatProbability(selected[series.key])}</dd>
      </div>)}</dl>
      <p>P10–P90 width: <strong>{formatThreeDecimals(selected.p90 - selected.p10)} EUR/MWh</strong> · P90 minus P10.</p>
      <details className="risk-exact"><summary>Model probabilities (0–1, three decimals)</summary>
        <dl>{[...directionSeries, ...spikeSeries].map((series) => <div key={series.key}><dt>{series.label}</dt><dd>{formatThreeDecimals(selected[series.key])}</dd></div>)}</dl>
      </details>
    </div>
    <div className="risk-definitions">
      <p>Direction means dominating mFRR balancing regulation, not whether prices rise or fall.</p>
      <p>High spike: imbalance price strictly above spot + €50/MWh. Low spike: strictly below spot − €50/MWh.</p>
      <p>Displayed values are rounded for reading; calculations use the original forecast values. These summaries describe forecasts, not model drivers or causes.</p>
    </div>
  </section>;
}
