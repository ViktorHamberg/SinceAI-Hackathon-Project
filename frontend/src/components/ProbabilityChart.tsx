import { useCallback, useMemo } from 'react';
import { CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import type { ForecastPoint } from '../api/forecast';
import { buildChartData, CHART_MARGIN, formatChartTick, PRICE_AXIS_WIDTH, TIME_AXIS_HEIGHT } from '../forecastChart';
import { directionSeries, formatProbability, probabilitiesAreFlat, spikeSeries } from '../forecastSummary';
import type { ProbabilityKey } from '../forecastSummary';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import { useQuarterInspection } from '../useQuarterInspection';
import './ProbabilityChart.css';

type Series = { key: ProbabilityKey; label: string; color: string; dash: string | undefined };
interface Props { points: ForecastPoint[]; zone: DisplayZone; selectedIndex: number; onSelect: (index: number) => void }
const axisPercent = (value: number) => `${Math.round(value * 100)}%`;

function ProbabilityPanel({ points, zone, selectedIndex, onSelect, series, title, id }: Props & { series: readonly Series[]; title: string; id: string }) {
  const { data, start, end, ticks } = useMemo(() => buildChartData(points), [points]);
  const selected = points[selectedIndex];
  const last = points[points.length - 1];
  const flat = useMemo(() => probabilitiesAreFlat(points, series.map((item) => item.key)), [points, series]);
  const inspection = useQuarterInspection(points.length, selectedIndex, onSelect);
  const timeTick = useCallback((value: number) => formatChartTick(value, zone), [zone]);
  return <section className="probability-panel" aria-labelledby={`${id}-heading`}>
    <h3 id={`${id}-heading`}>{title}</h3>
    <div id={`${id}-readout`} className="probability-readout" aria-live="polite">
      <p>Selected quarter {selected.step} · <time dateTime={selected.delivery_start_utc}>{formatTimestamp(selected.delivery_start_utc, zone)}</time></p>
      <ul className="probability-legend" aria-label={`${title} legend`}>{series.map((item) => <li key={item.key}>
        <svg width="25" height="12" aria-hidden="true"><line x1="0" x2="25" y1="6" y2="6" stroke={item.color} strokeDasharray={item.dash} strokeWidth="2.5" /></svg>
        <span>{item.label}</span><strong>{formatProbability(selected[item.key])}</strong>
      </li>)}</ul>
    </div>
    <div className="chart-canvas probability-canvas" role="application" tabIndex={0} aria-label={`${title} timeline`} aria-describedby={`probability-help ${id}-readout`} {...inspection}>
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <ComposedChart data={data} margin={CHART_MARGIN} accessibilityLayer={false} tabIndex={-1} role="img" aria-label={`${title}, probability from zero to one hundred percent`}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="timestamp" type="number" scale="time" domain={[start, end]} ticks={ticks} tickFormatter={timeTick} minTickGap={24} height={TIME_AXIS_HEIGHT} tickLine={false} axisLine={false} />
          <YAxis domain={[0, 1]} ticks={[0, .25, .5, .75, 1]} width={PRICE_AXIS_WIDTH} tickFormatter={axisPercent} tickLine={false} axisLine={false} allowDataOverflow />
          {series.map((item) => <Line key={item.key} dataKey={`point.${item.key}`} type="stepAfter" name={item.label} stroke={item.color} strokeDasharray={item.dash} strokeWidth={2.5} dot={false} activeDot={false} isAnimationActive={false} />)}
          {series.map((item) => <ReferenceLine key={`tail-${item.key}`} className="probability-final-quarter" segment={[{ x: Date.parse(last.delivery_start_utc), y: last[item.key] }, { x: end, y: last[item.key] }]} stroke={item.color} strokeDasharray={item.dash} strokeWidth={2.5} />)}
          <ReferenceLine x={Date.parse(selected.delivery_start_utc)} stroke="var(--ink)" strokeDasharray="3 3" />
          {series.map((item) => <ReferenceDot key={`dot-${item.key}`} x={Date.parse(selected.delivery_start_utc)} y={selected[item.key]} r={3.5} fill={item.color} stroke="var(--paper)" strokeWidth={1.5} />)}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    {flat && <p className="probability-flat">These probabilities are constant across all 40 quarters for this forecast.</p>}
  </section>;
}

export default function ProbabilityChart(props: Props) {
  return <section className="probability-charts" aria-labelledby="probability-heading">
    <h2 id="probability-heading">Direction and exceptional-price probabilities</h2>
    <p id="probability-help">Same delivery quarters as the price chart. Hover or tap to inspect; use Left/Right or Home/End when a timeline is focused. Line styles and labels distinguish events; overlapping lines can have equal probabilities.</p>
    <ProbabilityPanel {...props} series={directionSeries} title="Balancing direction" id="direction" />
    <ProbabilityPanel {...props} series={spikeSeries} title="Exceptional price" id="spike" />
  </section>;
}
