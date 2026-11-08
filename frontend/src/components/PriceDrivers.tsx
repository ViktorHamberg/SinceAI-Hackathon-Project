import { useState } from 'react';
import type { ForecastPoint } from '../api/forecast';
import { formatTimestamp } from '../time';
import type { DisplayZone } from '../time';
import './PriceDrivers.css';

const descriptions: Record<string, { label: string; description: string }> = {
  historical_prices: {
    label: 'Historical prices',
    description: 'Recent imbalance-price levels and variability give the model context about the market.',
  },
  spot_price_conditions: {
    label: 'Spot-price conditions',
    description: 'The day-ahead price, when already published, provides a reference for the imbalance-price forecast.',
  },
  calendar_horizon: {
    label: 'Calendar and forecast horizon',
    description: 'Delivery time, weekday and distance from the forecast issue time help the model distinguish delivery periods.',
  },
  balancing_conditions: {
    label: 'Balancing conditions',
    description: 'Available balancing observations describe the recent state of the electricity balancing system.',
  },
  renewable_production: {
    label: 'Renewable production',
    description: 'Available renewable-generation information provides context about electricity supply.',
  },
  consumption: {
    label: 'Consumption',
    description: 'Available consumption observations or forecasts provide context about electricity demand.',
  },
  production: {
    label: 'Production',
    description: 'Available production information provides context about electricity supply.',
  },
  cross_border_flows: {
    label: 'Cross-border flows',
    description: 'Available flow or transfer-capacity information describes connections with neighbouring electricity systems.',
  },
  neighboring_markets: {
    label: 'Neighbouring markets',
    description: 'Available observations from neighbouring markets provide context outside Finland.',
  },
  last_imbalance_price: {
    label: 'Latest imbalance price',
    description: 'The persistence baseline repeats the latest usable imbalance price as its median forecast. This is an input marker rather than a ranked model attribution.',
  },
};

export default function PriceDrivers({ points, zone }: { points: ForecastPoint[]; zone: DisplayZone }) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const point = points[selectedIndex];
  const drivers = [...new Set(point?.top_drivers?.split(';') ?? [])]
    .filter((name) => Object.hasOwn(descriptions, name)).slice(0, 3);

  return <section className="price-drivers" aria-labelledby="price-drivers-heading">
    <h2 id="price-drivers-heading">Main contributors to the median forecast</h2>
    <p className="price-drivers-intro">Inspect the model categories supplied for a delivery quarter. Select another issue time above to review a different forecast.</p>
    <label className="price-drivers-selection">
      Delivery quarter
      <select value={selectedIndex} onChange={(event) => setSelectedIndex(Number(event.target.value))}>
        {points.map((item, index) => <option key={item.step} value={index}>
          Quarter {item.step} · {formatTimestamp(item.delivery_start_utc, zone)}
        </option>)}
      </select>
    </label>
    <div role="status" aria-live="polite" aria-atomic="true">
      {drivers.length > 0 ? <ol className="price-drivers-list">
        {drivers.map((name) => <li key={name}>
          <h3>{descriptions[name].label}</h3>
          <p>{descriptions[name].description}</p>
        </li>)}
      </ol> : <p className="price-drivers-empty">Driver explanations unavailable for this quarter.</p>}
    </div>
    <p className="price-drivers-note">Model contributions, not proven causes. Learned-model categories retain the engine’s ranking for P50. Descriptions explain each category; they do not show the size or direction of its effect, or explain balancing-direction and spike probabilities.</p>
  </section>;
}
