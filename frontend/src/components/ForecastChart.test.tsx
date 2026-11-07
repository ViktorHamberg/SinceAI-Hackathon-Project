import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import ForecastChart from './ForecastChart';
import { fixture } from '../test/fixture';

it('renders a real ranged band, median and final-quarter marks with an accessible chart', async () => {
  const { container } = render(<ForecastChart points={fixture().points} zone="Europe/Helsinki" />);
  expect(await screen.findByRole('application', { name: 'Ten-hour imbalance price forecast' })).toBeVisible();
  await waitFor(() => expect(container.querySelector('.recharts-area-area')).toHaveAttribute('d', expect.stringContaining('M')));
  expect(container.querySelector('.recharts-line-curve')).toHaveAttribute('d', expect.stringContaining('M'));
  expect(container.querySelector('.final-quarter-band')).toBeInTheDocument();
  expect(container.querySelector('.final-quarter-median')).toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'Chart legend' })).toHaveTextContent('P50 median');
  expect(screen.getByRole('button', { name: 'Previous quarter' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: 'Next quarter' }));
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 2 of 40');
  await userEvent.click(screen.getByRole('button', { name: 'Previous quarter' }));
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 1 of 40');
});

it('inspects all 40 real quarters with the keyboard and reports exact values and times', async () => {
  const { container } = render(<ForecastChart points={fixture().points} zone="Europe/Helsinki" />);
  const user = userEvent.setup();
  const chart = await screen.findByRole('application', { name: 'Ten-hour imbalance price forecast' });
  await waitFor(() => expect(container.querySelector('.recharts-area-area')).not.toBeNull());
  await user.tab();
  expect(chart).toHaveFocus();
  const first = await screen.findByRole('status');
  expect(first).toHaveTextContent('Quarter 1 of 40');
  expect(within(first).getByText('-12.345678')).toBeVisible();
  expect(first).toHaveTextContent('UTC start: 06 Sept 2026, 21:00 UTC');
  for (let index = 1; index < 40; index++) {
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('status')).toHaveTextContent(`Quarter ${index + 1} of 40`);
  }
  expect(screen.getByRole('status')).toHaveTextContent('Ends 07 Sept 2026, 10:00 UTC+3');
  await user.keyboard('{ArrowRight}');
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 40 of 40');
  expect(screen.getByRole('button', { name: 'Next quarter' })).toBeDisabled();
  await user.keyboard('{Home}');
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 1 of 40');
  await user.keyboard('{End}');
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 40 of 40');
  await user.tab();
  expect(chart).not.toHaveFocus();
}, 15_000);

it('shows both repeated local hours with their distinct offsets and changes to UTC', async () => {
  const { rerender } = render(<ForecastChart points={fixture('2026-10-25T00:00:00Z').points} zone="Europe/Helsinki" />);
  const user = userEvent.setup();
  await screen.findByRole('application');
  await user.tab();
  expect(await screen.findByRole('status')).toHaveTextContent('25 Oct 2026, 03:00 UTC+3');
  await user.keyboard('{ArrowRight>4/}');
  expect(screen.getByRole('status')).toHaveTextContent('25 Oct 2026, 03:00 UTC+2');
  rerender(<ForecastChart points={fixture('2026-10-25T00:00:00Z').points} zone="UTC" />);
  expect(screen.getByRole('status')).toHaveTextContent('25 Oct 2026, 01:00 UTC');
});

it.each([[-90, -30, -10], [-70, 0, 50]])('draws actual lower/upper boundaries, including negative prices (%s,%s,%s)', async (p10, p50, p90) => {
  const points = fixture().points.map((p) => ({ ...p, p10, p50, p90 }));
  const { container } = render(<ForecastChart points={points} zone="UTC" />);
  await screen.findByRole('application');
  await waitFor(() => expect(container.querySelector('.recharts-area-area')).not.toBeNull());
  const d = container.querySelector('.recharts-area-area')!.getAttribute('d')!;
  const pairs = [...d.matchAll(/[ML](-?[\d.]+),(-?[\d.]+)/g)];
  const ys = pairs.map((pair) => Number(pair[2]));
  const domainLow = -100;
  const domainHigh = p90 < 0 ? 0 : 100;
  const y = (price: number) => 12 + (domainHigh - price) / (domainHigh - domainLow) * (360 - 12 - 48 - 8);
  expect(Math.min(...ys)).toBeCloseTo(y(p90), 2);
  expect(Math.max(...ys)).toBeCloseTo(y(p10), 2);
  const tail = container.querySelector('.final-quarter-median line')!;
  expect(Number(tail.getAttribute('x2'))).toBeCloseTo(888, 2);
  expect(Number(tail.getAttribute('x2')) - Number(tail.getAttribute('x1'))).toBeCloseTo((900 - 58 - 12) / 40, 2);
});

it('switches between hover, click and keyboard inspection without stale selection', async () => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, right: 900, bottom: 360, width: 900, height: 360, toJSON() {} });
  const { container } = render(<ForecastChart points={fixture().points} zone="UTC" />);
  await screen.findByRole('application');
  await waitFor(() => expect(container.querySelector('.recharts-area-area')).not.toBeNull());
  const wrapper = container.querySelector('.recharts-wrapper')!;
  fireEvent.mouseMove(wrapper, { clientX: 473, clientY: 150 });
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Quarter 21 of 40'));
  fireEvent.click(wrapper, { clientX: 65, clientY: 150 });
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Quarter 1 of 40'));
  const user = userEvent.setup();
  await user.tab();
  await user.keyboard('{ArrowRight}');
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 2 of 40');
  fireEvent.click(wrapper, { clientX: 873, clientY: 150 });
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Quarter 40 of 40'));
  await user.keyboard('{ArrowLeft}');
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 39 of 40');
  fireEvent.touchStart(wrapper, { touches: [{ clientX: 65, clientY: 150 }] });
  fireEvent.touchEnd(wrapper, { changedTouches: [{ clientX: 65, clientY: 150 }] });
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 1 of 40');
  fireEvent.touchStart(wrapper, { touches: [{ clientX: 65, clientY: 150 }] });
  fireEvent.touchEnd(wrapper, { changedTouches: [{ clientX: 873, clientY: 150 }] });
  expect(screen.getByRole('status')).toHaveTextContent('Quarter 1 of 40');
  expect(container.querySelector('animate')).toBeNull();
});
