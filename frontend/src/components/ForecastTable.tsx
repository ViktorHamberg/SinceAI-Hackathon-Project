import type { ForecastPoint } from '../api/forecast';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import { formatThreeDecimals } from '../format';
import './ForecastTable.css';

export default function ForecastTable({ points, zone = 'Europe/Helsinki' }: { points: ForecastPoint[]; zone?: DisplayZone }) {
  return (
    <section className="forecast-section" aria-labelledby="prices-heading">
      <div className="table-heading">
        <div>
          <h2 id="prices-heading">Quarter-hour prices</h2>
          <p>40 delivery periods · Prices in EUR/MWh</p>
        </div>
        <span className="table-unit">{zone === 'UTC' ? 'UTC' : 'Europe/Helsinki'} · Offsets shown per delivery</span>
      </div>
      <p id="table-help" className="table-help">Each row covers 15 minutes. Scroll within the table for all quarters and columns.</p>
      <div className="table-scroll" role="region" aria-label="Forecast price table" aria-describedby="table-help" tabIndex={0}>
        <table>
          <caption className="visually-hidden">Predicted imbalance prices for all 40 quarter-hours. P10 and P90 are uncertainty bounds; P50 is the median.</caption>
          <thead><tr>
            <th scope="col">Quarter</th>
            <th scope="col">Delivery start</th>
            <th scope="col" className="number">P10 <span>Lower</span></th>
            <th scope="col" className="number median">P50 <span>Median</span></th>
            <th scope="col" className="number">P90 <span>Upper</span></th>
          </tr></thead>
          <tbody>{points.map((point) => (
            <tr key={point.delivery_start_utc} className={(point.step - 1) % 4 === 0 ? 'hour-start' : undefined}>
              <th scope="row" className="quarter">{String(point.step).padStart(2, '0')}</th>
              <td><time dateTime={point.delivery_start_utc}>
                {formatTimestamp(point.delivery_start_utc, zone)}
              </time></td>
              <td className="number">{formatThreeDecimals(point.p10)}</td>
              <td className="number median">{formatThreeDecimals(point.p50)}</td>
              <td className="number">{formatThreeDecimals(point.p90)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="table-notes"><p>P10 and P90 bound a nominal 80% forecast interval. P50 is the median.</p><p>Negative prices are valid.</p></div>
    </section>
  );
}
