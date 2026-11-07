import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import ProbabilityChart from './ProbabilityChart';
import ForecastAnalysis from './ForecastAnalysis';
import ForecastTable from './ForecastTable';
import { fixture } from '../test/fixture';

it('plots raw probabilities on zero-to-one-hundred axes, including boundaries and the final quarter', async () => {
  const points = fixture().points.map((point, index) => ({ ...point, p_up: index === 0 ? 0 : 1, p_down: index === 0 ? 1 : 0, p_none: 0, p_spike_high: 0, p_spike_low: 1 }));
  const original = structuredClone(points);
  const { container } = render(<ProbabilityChart points={points} zone="UTC" selectedIndex={0} onSelect={vi.fn()} />);
  await waitFor(() => expect(container.querySelectorAll('.recharts-line-curve')).toHaveLength(5));
  expect(screen.getAllByText('100%').length).toBeGreaterThanOrEqual(2);
  expect(screen.getAllByText('0%').length).toBeGreaterThanOrEqual(2);
  const tail = container.querySelectorAll('.probability-final-quarter line');
  expect(tail).toHaveLength(5);
  for (const line of tail) {
    expect(Number(line.getAttribute('x2'))).toBeCloseTo(888, 2);
    expect(Number(line.getAttribute('x2')) - Number(line.getAttribute('x1'))).toBeCloseTo(830 / 40, 2);
  }
  const paths = [...container.querySelectorAll('.recharts-line-curve')].map((path) => path.getAttribute('d')!);
  const first = [...paths[0].matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)];
  expect(Number(first[0][2])).toBeCloseTo(304, 2); // 0 at plot bottom.
  expect(Math.min(...first.map((pair) => Number(pair[2])))).toBeCloseTo(12, 2); // 1 at plot top.
  expect(points).toEqual(original);
});

it('links price, probability and summary selection without fetching and preserves flat signals', async () => {
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  render(<ForecastAnalysis points={fixture().points} zone="Europe/Helsinki" />);
  const price = await screen.findByRole('application', { name: 'Ten-hour imbalance price forecast' });
  const direction = await screen.findByRole('application', { name: 'Balancing direction timeline' });
  const user = userEvent.setup();
  direction.focus();
  await user.keyboard('{End}');
  expect(screen.getByRole('combobox', { name: 'Inspect delivery quarter' })).toHaveValue('39');
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 40 of 40');
  expect(within(screen.getByRole('region', { name: 'Exceptional price' })).getByText(/Selected quarter 40/)).toBeVisible();
  price.focus();
  await user.keyboard('{Home}{ArrowRight}');
  expect(screen.getByRole('combobox', { name: 'Inspect delivery quarter' })).toHaveValue('1');
  expect(within(screen.getByRole('region', { name: 'Balancing direction' })).getByText(/Selected quarter 2/)).toBeVisible();
  await user.selectOptions(screen.getByRole('combobox', { name: 'Inspect delivery quarter' }), '7');
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 8 of 40');
  fireEvent.mouseMove(direction, { clientX: 873, clientY: 150 });
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 40 of 40');
  expect(screen.getAllByText(/These probabilities are constant across all 40 quarters/)).toHaveLength(2);
  expect(fetch).not.toHaveBeenCalled();
});

it('retains real price table and selectable exact probabilities when plotting fails', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.stubGlobal('ResizeObserver', class { constructor() { throw new Error('INVENTED_PLOT_FAILURE'); } });
  const points = fixture().points;
  render(<><ForecastAnalysis points={points} zone="UTC" /><ForecastTable points={points} zone="UTC" /></>);
  expect(await screen.findByRole('heading', { name: 'Probability timelines unavailable' })).toBeVisible();
  expect(screen.getByRole('heading', { name: 'Price chart unavailable' })).toBeVisible();
  expect(screen.getByRole('table')).toBeVisible();
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Inspect delivery quarter' }), '39');
  await userEvent.click(screen.getByText('Exact model probabilities (0–1)'));
  expect(screen.getByText('0.4')).toBeVisible();
  expect(screen.queryByText('INVENTED_PLOT_FAILURE')).not.toBeInTheDocument();
});
