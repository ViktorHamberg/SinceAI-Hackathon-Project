import { useCallback, useMemo } from 'react';
import { CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import type { ForecastPoint } from '../api/forecast';
import { buildChartData, CHART_MARGIN, formatChartTick, PRICE_AXIS_WIDTH, TIME_AXIS_HEIGHT } from '../forecastChart';
import { directionSeries, formatProbability, probabilitiesAreFlat, spikeSeries } from '../forecastSummary';
import type { ProbabilityKey } from '../forecastSummary';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import { useQuarterInspection } from '../useQuarterInspection';
import { formatThreeDecimals } from '../format';
import './ProbabilityChart.css';

type Series = { key: ProbabilityKey; label: string; color: string; dash: string | undefined };
interface Props { points: ForecastPoint[]; zone: DisplayZone; selectedIndex: number; onSelect: (index: number) => void }
const axisPercent = (value: number) => `${Math.round(value * 100)}%`;
const axisBalance = (value: number) => `${Math.round(value * 100)} pp`;
const balanceValue = (point: ForecastPoint) => point.p_up - point.p_down;
const plottedBalance = (point: ForecastPoint) => Math.max(-.5, Math.min(.5, balanceValue(point)));
const balanceText = (value: number) => `${formatThreeDecimals(Math.max(0, value) * 100)} pp`;

function ProbabilityPanel({ points, zone, selectedIndex, onSelect, series, title, id }: Props & { series: readonly Series[]; title: string; id: string }) {
  const { data, start, end, ticks } = useMemo(() => buildChartData(points), [points]);
  const isBalance = id === 'direction';
  const chartData = useMemo(() => isBalance ? data.map((row) => ({ ...row, balance: plottedBalance(row.point) })) : data, [data, isBalance]);
  const selected = points[selectedIndex];
  const last = points[points.length - 1];
  const flat = useMemo(() => isBalance
    ? points.every((point) => Math.abs(balanceValue(point) - balanceValue(points[0])) <= 8 * Number.EPSILON)
    : probabilitiesAreFlat(points, series.map((item) => item.key)), [points, series, isBalance]);
  const beyondScale = isBalance && points.some((point) => Math.abs(balanceValue(point)) > .5);
  const inspection = useQuarterInspection(points.length, selectedIndex, onSelect);
  const timeTick = useCallback((value: number) => formatChartTick(value, zone), [zone]);
  return <section className="probability-panel" aria-labelledby={`${id}-heading`}>
    <h3 id={`${id}-heading`}>{title}</h3>
    <div id={`${id}-readout`} className="probability-readout" aria-live="polite">
      <p>Selected quarter {selected.step} · <time dateTime={selected.delivery_start_utc}>{formatTimestamp(selected.delivery_start_utc, zone)}</time></p>
      <ul className="probability-legend" aria-label={isBalance ? 'Selected direction balance and no-direction probability' : `${title} legend`}>{series.map((item) => <li key={item.key}>
        {!isBalance && <svg width="25" height="12" aria-hidden="true"><line x1="0" x2="25" y1="6" y2="6" stroke={item.color} strokeDasharray={item.dash} strokeWidth="2.5" /></svg>}
        <span>{item.label}</span><strong>{isBalance && item.key === 'p_up' ? balanceText(balanceValue(selected))
          : isBalance && item.key === 'p_down' ? balanceText(-balanceValue(selected))
            : formatProbability(selected[item.key])}</strong>
      </li>)}</ul>
    </div>
    <div className="chart-canvas probability-canvas" role="application" tabIndex={0} aria-label={`${title} timeline`} aria-describedby={`probability-help ${id}-readout`} {...inspection}>
      <ResponsiveContainer width="100%" height="100%" debounce={50}>
        <ComposedChart data={chartData} margin={CHART_MARGIN} accessibilityLayer={false} tabIndex={-1} role="img" aria-label={isBalance ? 'Up regulation probability minus down regulation probability, minus fifty to plus fifty percentage points' : `${title}, probability from zero to one hundred percent`}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="timestamp" type="number" scale="time" domain={[start, end]} ticks={ticks} tickFormatter={timeTick} minTickGap={24} height={TIME_AXIS_HEIGHT} tickLine={false} axisLine={false} />
          <YAxis domain={isBalance ? [-.5, .5] : [0, 1]} ticks={isBalance ? [-.5, -.25, 0, .25, .5] : [0, .25, .5, .75, 1]} width={PRICE_AXIS_WIDTH} tickFormatter={isBalance ? axisBalance : axisPercent} tickLine={false} axisLine={false} allowDataOverflow />
          {isBalance && <ReferenceLine y={0} stroke="var(--control-line)" strokeWidth={1.5} />}
          {isBalance ? <Line dataKey="balance" type="stepAfter" name="Up minus down" stroke="var(--ink)" strokeWidth={2.5} dot={false} activeDot={false} isAnimationActive={false} />
            : series.map((item) => <Line key={item.key} dataKey={`point.${item.key}`} type="stepAfter" name={item.label} stroke={item.color} strokeDasharray={item.dash} strokeWidth={2.5} dot={false} activeDot={false} isAnimationActive={false} />)}
          {isBalance ? <ReferenceLine className="probability-final-quarter" segment={[{ x: Date.parse(last.delivery_start_utc), y: plottedBalance(last) }, { x: end, y: plottedBalance(last) }]} stroke="var(--ink)" strokeWidth={2.5} />
            : series.map((item) => <ReferenceLine key={`tail-${item.key}`} className="probability-final-quarter" segment={[{ x: Date.parse(last.delivery_start_utc), y: last[item.key] }, { x: end, y: last[item.key] }]} stroke={item.color} strokeDasharray={item.dash} strokeWidth={2.5} />)}
          <ReferenceLine x={Date.parse(selected.delivery_start_utc)} stroke="var(--ink)" strokeDasharray="3 3" />
          {isBalance ? <ReferenceDot x={Date.parse(selected.delivery_start_utc)} y={plottedBalance(selected)} r={3.5} fill="var(--ink)" stroke="var(--paper)" strokeWidth={1.5} />
            : series.map((item) => <ReferenceDot key={`dot-${item.key}`} x={Date.parse(selected.delivery_start_utc)} y={selected[item.key]} r={3.5} fill={item.color} stroke="var(--paper)" strokeWidth={1.5} />)}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    {beyondScale && <p className="probability-flat">Some direction balances exceed the fixed ±50 pp scale and are clipped. Select a quarter to read its value.</p>}
    {flat && <p className="probability-flat">{isBalance ? 'The direction balance is constant' : 'These probabilities are constant'} across all 40 quarters for this forecast.</p>}
  </section>;
}

export default function ProbabilityChart(props: Props) {
  return <section className="probability-charts" aria-labelledby="probability-heading">
    <h2 id="probability-heading">Direction and exceptional-price probabilities</h2>
    <p id="probability-help">Direction balance is up probability minus down probability. The up and down readouts show the positive balance on their respective side, in percentage points; the no-direction readout is its original probability. Zero means equal up and down probabilities. The fixed direction axis runs from −50 to +50 pp. Hover or tap to inspect; use Left/Right or Home/End when a timeline is focused.</p>
    <ProbabilityPanel {...props} series={directionSeries} title="Balancing direction" id="direction" />
    <ProbabilityPanel {...props} series={spikeSeries} title="Exceptional price" id="spike" />
  </section>;
}
