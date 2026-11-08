import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import RiskSummary from './RiskSummary';
import { summarizeForecast } from '../forecastSummary';
import { fixture } from '../test/fixture';

it('shows flat maxima, honest event definitions and rounded selected probabilities', async () => {
  const points = fixture().points;
  render(<RiskSummary points={points} summary={summarizeForecast(points)} selectedIndex={0} zone="Europe/Helsinki" onSelect={vi.fn()} />);
  expect(screen.getAllByText('All 40 quarters share this value.')).toHaveLength(3);
  expect(screen.getByText(/Highest direction probability:/)).toHaveTextContent('Down regulation');
  expect(screen.getByText(/not whether prices rise or fall/)).toBeVisible();
  expect(screen.getByText(/not to an event anywhere across the ten hours/)).toBeVisible();
  await userEvent.click(screen.getByText('Model probabilities (0–1, three decimals)'));
  expect(screen.getByText('0.400')).toBeVisible();
  expect(screen.getByText('0.500')).toBeVisible();
  expect(screen.queryByText(/strong buy|strong sell/i)).not.toBeInTheDocument();
});

it('lets users inspect each tied quarter and retains distinct repeated-hour option IDs', async () => {
  const points = fixture('2026-10-25T00:00:00Z').points;
  points[1].p_spike_high = points[4].p_spike_high = .5;
  const onSelect = vi.fn();
  render(<RiskSummary points={points} summary={summarizeForecast(points)} selectedIndex={0} zone="Europe/Helsinki" onSelect={onSelect} />);
  const high = screen.getByRole('article', { name: 'Highest high-spike probability' });
  await userEvent.click(within(high).getByRole('button', { name: /Inspect quarter 2/ }));
  expect(onSelect).toHaveBeenLastCalledWith(1);
  await userEvent.click(within(high).getByText('2 quarters tied for this maximum'));
  await userEvent.click(within(high).getByRole('button', { name: /Quarter 5/ }));
  expect(onSelect).toHaveBeenLastCalledWith(4);
  expect(screen.getByRole('option', { name: /Quarter 1 ·.*03:00 UTC\+3/ })).toHaveValue('0');
  expect(screen.getByRole('option', { name: /Quarter 5 ·.*03:00 UTC\+2/ })).toHaveValue('4');
  await userEvent.selectOptions(screen.getByRole('combobox'), '39');
  expect(onSelect).toHaveBeenLastCalledWith(39);
});
