import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { fixture } from '../test/fixture';
import PriceDrivers from './PriceDrivers';

it('preserves returned ranking, explains only approved categories and updates with the quarter', async () => {
  const points = fixture().points;
  points[0].top_drivers = 'spot_price_conditions;unapproved;historical_prices;spot_price_conditions;calendar_horizon;production';
  points[1].top_drivers = null;
  render(<PriceDrivers points={points} zone="UTC" />);
  const items = within(screen.getByRole('list')).getAllByRole('listitem');
  expect(items).toHaveLength(3);
  expect(within(items[0]).getByRole('heading')).toHaveTextContent('Spot-price conditions');
  expect(within(items[1]).getByRole('heading')).toHaveTextContent('Historical prices');
  expect(within(items[2]).getByRole('heading')).toHaveTextContent('Calendar and forecast horizon');
  expect(screen.queryByText('unapproved')).not.toBeInTheDocument();
  await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: 'Delivery quarter' }), '1');
  expect(screen.getByText('Driver explanations unavailable for this quarter.')).toBeVisible();
  expect(screen.queryByRole('list')).not.toBeInTheDocument();
});

it('distinguishes the persistence input marker from learned contributions', () => {
  const points = fixture().points;
  points[0].top_drivers = 'last_imbalance_price';
  render(<PriceDrivers points={points} zone="Europe/Helsinki" />);
  expect(screen.getByText(/input marker rather than a ranked model attribution/)).toBeVisible();
});
