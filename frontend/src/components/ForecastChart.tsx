import { useCallback, useMemo } from 'react';
import type { ReactNode } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import type { ForecastPoint, HistoryResponse } from '../api/forecast';
import { buildChartData, CHART_MARGIN, formatChartTick, PRICE_AXIS_WIDTH, QUARTER_MS, TIME_AXIS_HEIGHT } from '../forecastChart';
import { useQuarterInspection } from '../useQuarterInspection';
import { formatTimestamp } from '../time';
import { formatThreeDecimals } from '../format';
import type { DisplayZone } from '../time';
import './ForecastChart.css';

const priceAxisFormat = new Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 });
const driverLabels: Record<string, string> = {
  renewable_production: 'Renewable production',
  consumption: 'Consumption',
  production: 'Production',
  cross_border_flows: 'Cross-border flows',
  neighboring_markets: 'Neighbouring markets',
  balancing_conditions: 'Balancing conditions',
  historical_prices: 'Recent imbalance prices',
  spot_price_conditions: 'Day-ahead spot conditions',
  calendar_horizon: 'Calendar and delivery time',
};

function QuarterDetails({ point, zone, onStep }: { point: ForecastPoint; zone: DisplayZone; onStep: (delta: number) => void }) {
  const end = new Date(Date.parse(point.delivery_start_utc) + QUARTER_MS).toISOString().replace('.000Z', 'Z');
  const drivers = point.top_drivers?.split(';').map((name) => driverLabels[name]).filter((name): name is string => name !== undefined) ?? [];
  return <div className="chart-selection" role="status" aria-live="polite" aria-atomic="true">
    <div className="selection-time">
      <p className="selection-label">Selected delivery · Quarter {point.step} of 40</p>
      <p className="selection-start"><time dateTime={point.delivery_start_utc}>{formatTimestamp(point.delivery_start_utc, zone)}</time></p>
      <p className="selection-end">Ends {formatTimestamp(end, zone)}</p>
      {zone !== 'UTC' && <p className="selection-utc">UTC start: {formatTimestamp(point.delivery_start_utc, 'UTC')}</p>}
    </div>
    <dl>
      <div><dt>P10 · Lower</dt><dd>{formatThreeDecimals(point.p10)}</dd></div>
      <div className="selection-median"><dt>P50 · Median</dt><dd>{formatThreeDecimals(point.p50)}</dd></div>
      <div><dt>P90 · Upper</dt><dd>{formatThreeDecimals(point.p90)}</dd></div>
    </dl>
    <p className="selection-unit">EUR/MWh</p>
    <div className="selection-drivers">
      <h3>P50 model contributions</h3>
      {drivers.length > 0 ? <ol>{drivers.map((label) => <li key={label}>{label}</li>)}</ol>
        : <p>No verified contribution labels for this quarter.</p>}
      <p>Ranked model categories for the median price. They do not explain direction or spike probabilities.</p>
    </div>
    <div className="chart-navigation" role="group" aria-label="Delivery inspection">
      <button type="button" disabled={point.step === 1} onClick={() => onStep(-1)} aria-label="Previous quarter">Previous</button>
      <button type="button" disabled={point.step === 40} onClick={() => onStep(1)} aria-label="Next quarter">Next</button>
    </div>
  </div>;
}

export default function ForecastChart({ points, zone, selectedIndex, onSelect, history, comparisonControl }: {
  points: ForecastPoint[]; zone: DisplayZone; selectedIndex: number; onSelect: (index: number) => void;
  history?: HistoryResponse; comparisonControl?: ReactNode;
}) {
  const { data, start, end, ticks, priceDomain, priceTicks } = useMemo(() => buildChartData(points, history?.points), [points, history]);
  const last = data[data.length - 1];
  const selected = data[selectedIndex];
  const inspection = useQuarterInspection(points.length, selectedIndex, onSelect);
  const timeTick = useCallback((value: number) => formatChartTick(value, zone), [zone]);

  return <section className="forecast-chart" aria-labelledby="chart-heading">
    <div className="chart-heading">
      <div><h2 id="chart-heading">10-hour price outlook</h2><p>Imbalance price · EUR/MWh</p></div>
      {comparisonControl}
      <ul className="chart-legend" aria-label="Chart legend">
        <li><span className="legend-median" aria-hidden="true" />P50 median</li>
        <li><span className="legend-range" aria-hidden="true" />P10 to P90 interval</li>
        {history && <li><span className="legend-observed" aria-hidden="true" />Observed price · retrospective</li>}
      </ul>
    </div>
    <p className="chart-help" id="chart-help">Hover or tap a delivery for values rounded to three decimals below. Keyboard: Tab to the chart, then use Left and Right arrows. Home and End select the first and last quarter.</p>
    <div className="chart-canvas" role="application" tabIndex={0} aria-label="Ten-hour imbalance price forecast" aria-describedby="chart-help"
      {...inspection}>
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <ComposedChart data={data} margin={CHART_MARGIN}
          accessibilityLayer={false} tabIndex={-1} role="img" aria-label={history ? 'Median price, P10 to P90 interval and retrospective observed price' : 'Median price and P10 to P90 interval'}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="timestamp" type="number" scale="time" domain={[start, end]} ticks={ticks}
            tickFormatter={timeTick} minTickGap={24} height={TIME_AXIS_HEIGHT} tickLine={false} axisLine={false} />
          <YAxis domain={priceDomain} ticks={priceTicks} width={PRICE_AXIS_WIDTH} tickLine={false} axisLine={false}
            tickFormatter={priceAxisFormat.format} />
          {priceDomain[0] < 0 && priceDomain[1] > 0 && <ReferenceLine y={0} stroke="var(--control-line)" strokeDasharray="2 3" />}
          <Area dataKey="band" type="stepAfter" name="P10 to P90" fill="var(--chart-band-fill)" fillOpacity={1}
            stroke="var(--chart-band-edge)" strokeDasharray="4 3" strokeWidth={1.25} dot={false} activeDot={false} isAnimationActive={false} />
          {/* The final quarter has duration too; these marks end it without adding a 41st forecast. */}
          <ReferenceArea className="final-quarter-band" x1={last.timestamp} x2={end} y1={last.point.p10} y2={last.point.p90}
            fill="var(--chart-band-fill)" fillOpacity={1} stroke="var(--chart-band-edge)" strokeDasharray="4 3" strokeWidth={1.25} />
          <Line dataKey="p50" type="stepAfter" name="P50 median" stroke="var(--ink)" strokeWidth={2.5}
            dot={false} activeDot={false} isAnimationActive={false} />
          <ReferenceLine className="final-quarter-median" segment={[{ x: last.timestamp, y: last.p50 }, { x: end, y: last.p50 }]}
            stroke="var(--ink)" strokeWidth={2.5} />
          {history && <Line className="observed-price" dataKey="actual" type="stepAfter" name="Observed price · retrospective"
            stroke="var(--observed-price)" strokeWidth={2.5} strokeDasharray="8 3 2 3" connectNulls={false}
            dot={false} activeDot={false} isAnimationActive={false} />}
          {history && data.filter((row, index) => row.actual !== null && (index === data.length - 1 || data[index + 1].actual === null)).map((row) =>
            <ReferenceLine key={row.timestamp} className="observed-quarter-end"
              segment={[{ x: row.timestamp, y: row.actual! }, { x: row.timestamp + QUARTER_MS, y: row.actual! }]}
              stroke="var(--observed-price)" strokeWidth={2.5} strokeDasharray="8 3 2 3" />)}
          <ReferenceLine x={selected.timestamp} stroke="var(--ink)" strokeDasharray="3 3" />
          <ReferenceDot x={selected.timestamp} y={selected.p50} r={4} fill="var(--ink)" stroke="var(--paper)" strokeWidth={2} />
          {history && selected.actual !== null && <ReferenceDot x={selected.timestamp} y={selected.actual} r={4}
            fill="var(--paper)" stroke="var(--observed-price)" strokeWidth={2} />}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    <QuarterDetails point={selected.point} zone={zone} onStep={(delta) => onSelect(Math.max(0, Math.min(points.length - 1, selectedIndex + delta)))} />
    <div className="chart-caption"><p>Delivery start · {zone === 'UTC' ? 'UTC' : 'Europe/Helsinki'} · Offsets shown on the time axis</p>
      <p>Each step covers 15 minutes. The shaded interval is nominally 80%; observed coverage can differ.</p>
      {history && <p>Observed prices are retrospective. Missing outcomes leave gaps; the price axis includes matched actual prices.</p>}</div>
  </section>;
}
