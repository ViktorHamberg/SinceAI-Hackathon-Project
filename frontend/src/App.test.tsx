import { StrictMode } from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import App from './App';
import { fixture, jsonResponse } from './test/fixture';

it('loads the real endpoint contract and displays origin, horizon and run identity', async () => {
  let resolve!: (response: Response) => void;
  vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
  render(<App />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading forecast');
  await act(async () => resolve(jsonResponse()));
  expect(await screen.findByRole('table')).toBeVisible();
  expect(screen.getAllByRole('row')).toHaveLength(41);
  expect(screen.getByText('07 Sept 2026, 10:00 UTC+3')).toBeVisible();
  expect(screen.getByText(/Persistence baseline/)).toBeVisible();
  await userEvent.click(screen.getByText('Model and run details'));
  expect(screen.getByText(fixture().run_id)).toBeVisible();
  expect(screen.getByText(/Historical replay/)).toBeVisible();
});

it('shows a safe error and recovers when the user retries', async () => {
  const mock = vi.fn().mockRejectedValueOnce(new Error('PRIVATE DETAIL')).mockResolvedValueOnce(jsonResponse());
  vi.stubGlobal('fetch', mock);
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not connect');
  expect(screen.queryByText(/PRIVATE/)).not.toBeInTheDocument();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Retry connection' }));
  expect(await screen.findByRole('table')).toBeVisible();
  expect(mock).toHaveBeenCalledTimes(2);
});

it('clears the previous forecast while reloading and on a malformed response', async () => {
  let resolve!: (response: Response) => void;
  const mock = vi.fn().mockResolvedValueOnce(jsonResponse())
    .mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }));
  vi.stubGlobal('fetch', mock);
  render(<App />);
  await screen.findByRole('table');
  await userEvent.click(screen.getByRole('button', { name: 'Reload forecast' }));
  expect(screen.getByRole('status')).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  const incomplete = fixture();
  incomplete.points.pop();
  await act(async () => resolve(jsonResponse(incomplete)));
  expect(await screen.findByRole('alert')).toHaveTextContent('incomplete or unsupported');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('ignores a stale response even if a transport disregards cancellation', async () => {
  const resolvers: ((response: Response) => void)[] = [];
  const signals: AbortSignal[] = [];
  vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => {
    signals.push(options.signal as AbortSignal);
    return new Promise<Response>((resolve) => resolvers.push(resolve));
  }));
  render(<StrictMode><App /></StrictMode>);
  await waitFor(() => expect(resolvers).toHaveLength(2));
  expect(signals[0].aborted).toBe(true);
  await act(async () => resolvers[1](jsonResponse()));
  await screen.findByRole('table');
  await act(async () => resolvers[0](jsonResponse(fixture('2026-09-07T00:00:00Z'))));
  expect(screen.queryByText('07 Sept 2026, 13:00 UTC+3')).not.toBeInTheDocument();
  expect(screen.getByText('07 Sept 2026, 10:00 UTC+3')).toBeVisible();
});

it('switches all displayed times by keyboard without another request or changed prices', async () => {
  const fetch = vi.fn().mockResolvedValue(jsonResponse());
  vi.stubGlobal('fetch', fetch);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole('table');
  await user.tab();
  expect(screen.getByRole('link', { name: 'Skip to forecast' })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole('button', { name: 'Reload forecast' })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole('button', { name: 'Helsinki' })).toHaveFocus();
  await user.tab();
  const utc = screen.getByRole('button', { name: 'UTC' });
  expect(utc).toHaveFocus();
  await user.keyboard('{Enter}');
  expect(utc).toHaveAttribute('aria-pressed', 'true');
  expect(screen.getByRole('button', { name: 'Helsinki' })).toHaveAttribute('aria-pressed', 'false');
  expect(within(screen.getByRole('region', { name: 'Forecast context' })).getByText('06 Sept 2026, 21:00 UTC')).toBeVisible();
  expect(screen.getByText('07 Sept 2026, 07:00 UTC')).toBeVisible();
  expect(within(screen.getByRole('table')).getByText('-12.345678')).toBeVisible();
  await user.click(screen.getByText('Model and run details'));
  expect(screen.getByText('07 Nov 2026, 12:00 UTC')).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole('button', { name: 'Helsinki' }));
  expect(screen.getByText('07 Sept 2026, 10:00 UTC+3')).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('keeps the reload control and focus stable and ignores activation while pending', async () => {
  let resolve!: (response: Response) => void;
  const fetch = vi.fn().mockResolvedValueOnce(jsonResponse())
    .mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }));
  vi.stubGlobal('fetch', fetch);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByRole('table');
  const reload = screen.getByRole('button', { name: 'Reload forecast' });
  await user.click(reload);
  expect(reload).toHaveFocus();
  expect(reload).toHaveAttribute('aria-disabled', 'true');
  await user.keyboard('{Enter}');
  expect(fetch).toHaveBeenCalledTimes(2);
  await act(async () => resolve(jsonResponse()));
  await screen.findByRole('table');
  expect(reload).toHaveFocus();
  expect(reload).toHaveAttribute('aria-disabled', 'false');
});
