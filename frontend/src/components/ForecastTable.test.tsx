import { render, screen, within } from '@testing-library/react';
import { expect, it } from 'vitest';
import ForecastTable from './ForecastTable';
import { fixture } from '../test/fixture';

it('keeps all 40 quarters and exact negative/positive API values accessible', () => {
  render(<ForecastTable points={fixture().points} />);
  const rows = within(screen.getByRole('table')).getAllByRole('row');
  expect(rows).toHaveLength(41);
  expect(within(rows[1]).getByText('-12.345678')).toBeVisible();
  expect(within(rows[1]).getByText('2.123456')).toBeVisible();
  expect(within(rows[1]).getByText('45.987654')).toBeVisible();
  expect(within(rows[40]).getByRole('rowheader')).toHaveTextContent('40');
  expect(screen.getByRole('region', { name: 'Forecast price table' })).toHaveAttribute('tabindex', '0');
  expect(screen.getByText(/Prices in EUR\/MWh/)).toBeVisible();
});

it('retains UTC instants and tooltips across the repeated local hour', () => {
  render(<ForecastTable points={fixture('2026-10-25T00:00:00Z').points} />);
  const first = screen.getByText('25 Oct 2026, 03:00 UTC+3');
  const repeated = screen.getByText('25 Oct 2026, 03:00 UTC+2');
  expect(first).toHaveAttribute('datetime', '2026-10-25T00:00:00Z');
  expect(repeated).toHaveAttribute('datetime', '2026-10-25T01:00:00Z');
});

it('exposes UTC as visible text while preserving identifiers and prices', () => {
  render(<ForecastTable points={fixture().points} zone="UTC" />);
  expect(screen.getByText('06 Sept 2026, 21:00 UTC')).toHaveAttribute('datetime', '2026-09-06T21:00:00Z');
  expect(screen.getByText('-12.345678')).toBeVisible();
  expect(screen.getAllByRole('row')).toHaveLength(41);
});
