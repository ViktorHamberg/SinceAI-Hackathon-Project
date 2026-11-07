import { useCallback, useMemo } from 'react';
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import type { ForecastPoint } from '../api/forecast';
import { buildChartData, CHART_MARGIN, formatChartTick, PRICE_AXIS_WIDTH, QUARTER_MS, TIME_AXIS_HEIGHT } from '../forecastChart';
import { useQuarterInspection } from '../useQuarterInspection';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import './ForecastChart.css';

const priceAxisFormat = new Intl.NumberFormat('en-GB', { notation: 'compact', maximumFractionDigits: 1 });

function QuarterDetails({ point, zone, onStep }: { point: ForecastPoint; zone: DisplayZone; onStep: (delta: number) => void }) {
  const end = new Date(Date.parse(point.delivery_start_utc) + QUARTER_MS).toISOString().replace('.000Z', 'Z');
  return <div className="chart-selection" role="status" aria-live="polite" aria-atomic="true">
    <div className="selection-time">
      <p className="selection-label">Selected delivery · Quarter {point.step} of 40</p>
      <p className="selection-start"><time dateTime={point.delivery_start_utc}>{formatTimestamp(point.delivery_start_utc, zone)}</time></p>
      <p className="selection-end">Ends {formatTimestamp(end, zone)}</p>
      {zone !== 'UTC' && <p className="selection-utc">UTC start: {formatTimestamp(point.delivery_start_utc, 'UTC')}</p>}
    </div>
    <dl>
      <div><dt>P10 · Lower</dt><dd>{String(point.p10)}</dd></div>
      <div className="selection-median"><dt>P50 · Median</dt><dd>{String(point.p50)}</dd></div>
      <div><dt>P90 · Upper</dt><dd>{String(point.p90)}</dd></div>
    </dl>
    <p className="selection-unit">EUR/MWh</p>
    <div className="chart-navigation" role="group" aria-label="Delivery inspection">
      <button type="button" disabled={point.step === 1} onClick={() => onStep(-1)} aria-label="Previous quarter">Previous</button>
      <button type="button" disabled={point.step === 40} onClick={() => onStep(1)} aria-label="Next quarter">Next</button>
    </div>
  </div>;
}

export default function ForecastChart({ points, zone, selectedIndex, onSelect }: {
  points: ForecastPoint[]; zone: DisplayZone; selectedIndex: number; onSelect: (index: number) => void;
}) {
  const { data, start, end, ticks, priceDomain, priceTicks } = useMemo(() => buildChartData(points), [points]);
  const last = data[data.length - 1];
  const selected = data[selectedIndex];
  const inspection = useQuarterInspection(points.length, selectedIndex, onSelect);
  const timeTick = useCallback((value: number) => formatChartTick(value, zone), [zone]);

  return <section className="forecast-chart" aria-labelledby="chart-heading">
    <div className="chart-heading">
      <div><h2 id="chart-heading">10-hour price outlook</h2><p>Imbalance price · EUR/MWh</p></div>
      <ul className="chart-legend" aria-label="Chart legend">
        <li><span className="legend-median" aria-hidden="true" />P50 median</li>
        <li><span className="legend-range" aria-hidden="true" />P10 to P90 interval</li>
      </ul>
    </div>
    <p className="chart-help" id="chart-help">Hover or tap a delivery for exact values below. Keyboard: Tab to the chart, then use Left and Right arrows. Home and End select the first and last quarter.</p>
    <div className="chart-canvas" role="application" tabIndex={0} aria-label="Ten-hour imbalance price forecast" aria-describedby="chart-help"
      {...inspection}>
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <ComposedChart data={data} margin={CHART_MARGIN}
          accessibilityLayer={false} tabIndex={-1} role="img" aria-label="Median price and P10 to P90 interval">
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
          <ReferenceLine x={selected.timestamp} stroke="var(--ink)" strokeDasharray="3 3" />
          <ReferenceDot x={selected.timestamp} y={selected.p50} r={4} fill="var(--ink)" stroke="var(--paper)" strokeWidth={2} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    <QuarterDetails point={selected.point} zone={zone} onStep={(delta) => onSelect(Math.max(0, Math.min(points.length - 1, selectedIndex + delta)))} />
    <div className="chart-caption"><p>Delivery start · {zone === 'UTC' ? 'UTC' : 'Europe/Helsinki'} · Offsets shown on the time axis</p>
      <p>Each step covers 15 minutes. The shaded interval is nominally 80%; observed coverage can differ.</p></div>
  </section>;
}
