import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import App from './App';
import { fixture, historyFixture, jsonResponse, originsFixture, selectedFixture } from './test/fixture';

it('keeps comparison opt-in, follows selected origins and quarters, and switches timezones without refetching', async () => {
  const catalog = originsFixture();
  const fetch = vi.fn((url: string) => {
    if (url === '/api/origins') return Promise.resolve(jsonResponse(catalog));
    const origin = new URL(url, 'http://127.0.0.1').searchParams.get('origin')!;
    const forecast = selectedFixture(origin);
    return Promise.resolve(jsonResponse(url.startsWith('/api/history') ? historyFixture(forecast) : forecast));
  });
  vi.stubGlobal('fetch', fetch);
  render(<App />);
  await screen.findByRole('table');
  const user = userEvent.setup();
  const toggle = await screen.findByRole('button', { name: 'Show actual outcomes' });
  expect(toggle).toHaveAttribute('aria-pressed', 'false');
  expect(fetch.mock.calls.some(([url]) => url.startsWith('/api/history'))).toBe(false);
  const originalTable = screen.getByRole('table').textContent;
  toggle.focus(); await user.keyboard(' ');
  const review = await screen.findByRole('region', { name: 'Retrospective comparison' });
  await within(review).findByText('3 of 40 quarters');
  expect(screen.getByRole('table').textContent).toBe(originalTable);
  expect(await screen.findByRole('list', { name: 'Chart legend' })).toHaveTextContent('Observed price · retrospective');
  await user.selectOptions(screen.getByRole('combobox', { name: 'Inspect delivery quarter' }), '39');
  expect(within(review).getByRole('status')).toHaveTextContent('Observed quarter 40');
  const before = fetch.mock.calls.length;
  await user.click(screen.getByRole('button', { name: /^UTC$/ }));
  expect(within(review).getByRole('status')).toHaveTextContent('07 Sept 2026, 06:45 UTC');
  expect(fetch.mock.calls).toHaveLength(before);
  await user.selectOptions(screen.getByRole('combobox', { name: 'Choose exact issue time' }), catalog.origins[1]);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Show actual outcomes' })).toHaveAttribute('aria-pressed', 'true'));
  const laterReview = await screen.findByRole('region', { name: 'Retrospective comparison' });
  await within(laterReview).findByText('3 of 40 quarters');
  expect(within(laterReview).getByRole('status')).toHaveTextContent('Observed quarter 1');
  expect(within(laterReview).getByRole('status')).toHaveTextContent('06 Sept 2026, 22:00 UTC');
  expect(fetch.mock.calls.filter(([url]) => url.startsWith('/api/history'))).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  expect(screen.queryByRole('region', { name: 'Retrospective comparison' })).not.toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'Chart legend' })).not.toHaveTextContent('Observed price');
});

it('ignores obsolete history even when the transport disregards abort, and rejects another backend run', async () => {
  const catalog = originsFixture();
  const pending: { origin: string; resolve: (r: Response) => void; signal: AbortSignal }[] = [];
  vi.stubGlobal('fetch', vi.fn((url: string, options: RequestInit) => {
    if (url === '/api/origins') return Promise.resolve(jsonResponse(catalog));
    const origin = new URL(url, 'http://127.0.0.1').searchParams.get('origin')!;
    if (url.startsWith('/api/history')) return new Promise<Response>((resolve) => pending.push({ origin, resolve, signal: options.signal as AbortSignal }));
    return Promise.resolve(jsonResponse(selectedFixture(origin)));
  }));
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Show actual outcomes' }));
  await waitFor(() => expect(pending).toHaveLength(1));
  await user.selectOptions(screen.getByRole('combobox', { name: 'Choose exact issue time' }), catalog.origins[1]);
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(pending[0].signal.aborted).toBe(true);
  await act(async () => pending[0].resolve(jsonResponse(historyFixture(fixture()))));
  expect(screen.queryByText('3 of 40 quarters')).not.toBeInTheDocument();
  const changedRun = historyFixture(selectedFixture(pending[1].origin));
  changedRun.run_id = '00000000-0000-4000-8000-000000000099';
  await act(async () => pending[1].resolve(jsonResponse(changedRun)));
  expect(await screen.findByRole('alert')).toHaveTextContent('did not match this forecast');
  await user.click(screen.getByText('View all 40 forecast quarters'));
  expect(screen.getByRole('table')).toBeVisible();
  expect(screen.getByRole('list', { name: 'Chart legend' })).not.toHaveTextContent('Observed price');
});

it('retains actual-outcome controls, metrics and exact quarter inspection if plotting fails', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  vi.stubGlobal('ResizeObserver', class { constructor() { throw new Error('INVENTED_PLOT_FAILURE'); } });
  vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(jsonResponse(url === '/api/origins' ? originsFixture()
    : url.startsWith('/api/history') ? historyFixture() : fixture()))));
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole('heading', { name: 'Price chart unavailable' });
  await user.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  const review = await screen.findByRole('region', { name: 'Retrospective comparison' });
  await within(review).findByText('3 of 40 quarters');
  await user.click(screen.getByText('View all 40 forecast quarters'));
  expect(screen.getByRole('table')).toBeVisible();
  await user.selectOptions(screen.getByRole('combobox', { name: 'Inspect delivery quarter' }), '2');
  expect(within(review).getByText('200 EUR/MWh')).toBeVisible();
  expect(within(review).getByText('No dominating mFRR direction')).toBeVisible();
  expect(screen.queryByText('INVENTED_PLOT_FAILURE')).not.toBeInTheDocument();
});
