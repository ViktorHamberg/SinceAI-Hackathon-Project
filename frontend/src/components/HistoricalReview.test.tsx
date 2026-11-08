import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { expect, it, vi } from 'vitest';
import type { ForecastResponse } from '../api/forecast';
import { fixture, historyFixture, jsonResponse, selectedFixture } from '../test/fixture';
import HistoricalReview from './HistoricalReview';

const forecast = fixture();
function Review({ current = forecast, index = 0 }: { current?: ForecastResponse; index?: number }) {
  const [enabled, onEnabled] = useState(false);
  return <HistoricalReview forecast={current} enabled={enabled} onEnabled={onEnabled} zone="UTC" selectedIndex={index}>
    {(history, control) => <>{control}<p>{history ? 'Overlay ready' : 'Forecast only'}</p></>}
  </HistoricalReview>;
}

it('starts off, loads only on request, shows exact outcomes and hides all comparison data when disabled', async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(historyFixture()))); vi.stubGlobal('fetch', fetch);
  const { rerender } = render(<Review />);
  expect(fetch).not.toHaveBeenCalled();
  expect(screen.queryByText('Retrospective comparison')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  await screen.findByText('Overlay ready');
  expect(screen.getByText('66.667%')).toBeVisible();
  expect(screen.getByText('3 of 40 quarters')).toBeVisible();
  expect(screen.getByText('-12.346 EUR/MWh')).toBeVisible();
  expect(screen.getByText('Up regulation')).toBeVisible();
  rerender(<Review index={3} />);
  expect(screen.getByText('Unavailable')).toBeVisible();
  expect(screen.getByText('Up regulation')).toBeVisible();
  expect(fetch).toHaveBeenCalledTimes(1);
  await userEvent.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  expect(screen.queryByText('Retrospective comparison')).not.toBeInTheDocument();
  expect(screen.getByText('Forecast only')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  await screen.findByText('Overlay ready');
  expect(fetch).toHaveBeenCalledTimes(2);
});

it('keeps forecast inspection usable on error and retries without showing private diagnostics', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('PRIVATE')).mockResolvedValueOnce(jsonResponse(historyFixture())));
  render(<Review />);
  await userEvent.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load actual outcomes');
  expect(screen.getByText('Forecast only')).toBeVisible();
  expect(screen.queryByText('PRIVATE')).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: 'Retry actual outcomes' }));
  await screen.findByText('Overlay ready');
});

it('cancels old requests and ignores late results across origin changes and disabling', async () => {
  const pending: { resolve: (r: Response) => void; signal: AbortSignal }[] = [];
  vi.stubGlobal('fetch', vi.fn((_url: string, options: RequestInit) => new Promise<Response>((resolve) => pending.push({ resolve, signal: options.signal as AbortSignal }))));
  const later = selectedFixture('2026-09-06T22:00:00Z');
  const { rerender } = render(<Review />);
  await userEvent.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  await waitFor(() => expect(pending).toHaveLength(1));
  rerender(<Review current={later} />);
  await waitFor(() => expect(pending).toHaveLength(2));
  expect(pending[0].signal.aborted).toBe(true);
  await act(async () => pending[0].resolve(jsonResponse(historyFixture())));
  expect(screen.queryByText('Overlay ready')).not.toBeInTheDocument();
  await act(async () => pending[1].resolve(jsonResponse(historyFixture(later))));
  await screen.findByText('Overlay ready');
  rerender(<Review />);
  await waitFor(() => expect(pending).toHaveLength(3));
  await userEvent.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  expect(pending[2].signal.aborted).toBe(true);
  await act(async () => pending[2].resolve(jsonResponse(historyFixture())));
  expect(screen.queryByText('Overlay ready')).not.toBeInTheDocument();
});

it('explains all-missing prices without inventing metrics or losing actual directions', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(historyFixture(forecast, []))));
  render(<Review />);
  await userEvent.click(screen.getByRole('button', { name: 'Show actual outcomes' }));
  expect(await screen.findByText(/No actual prices are available/)).toBeVisible();
  expect(screen.getByText('0 of 40 quarters')).toBeVisible();
  expect(screen.getAllByText('Unavailable')).toHaveLength(3);
  expect(screen.getByText('Up regulation')).toBeVisible();
});
