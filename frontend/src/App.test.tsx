import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import App from './App';
import { fixture, jsonResponse, originsFixture, selectedFixture } from './test/fixture';

function installForecastTransport(mock: (url: string, options: RequestInit) => Promise<Response>) {
  vi.stubGlobal('fetch', (url: string, options: RequestInit) => url === '/api/origins'
    ? Promise.resolve(jsonResponse(originsFixture())) : mock(url, options));
}

it('loads the real endpoint contract and displays origin, horizon and run identity', async () => {
  let resolve!: (response: Response) => void;
  installForecastTransport(vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
  render(<App />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading forecast');
  await waitFor(() => expect(resolve).toBeDefined());
  await act(async () => resolve(jsonResponse()));
  expect(await screen.findByRole('table')).toBeVisible();
  expect(screen.getAllByRole('row')).toHaveLength(41);
  expect(screen.getByText('07 Sept 2026, 10:00 UTC+3')).toBeVisible();
  expect(screen.getByText(/Persistence baseline/)).toBeVisible();
  await userEvent.click(screen.getByText('Model and run details'));
  expect(screen.getByText(fixture().run_id)).toBeVisible();
  expect(screen.getByText('Historical replay / Finland')).toBeVisible();
});

it('shows a safe error and recovers when the user retries', async () => {
  const mock = vi.fn().mockRejectedValueOnce(new Error('PRIVATE DETAIL')).mockResolvedValueOnce(jsonResponse());
  installForecastTransport(mock);
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
  installForecastTransport(mock);
  render(<App />);
  await screen.findByRole('table');
  await userEvent.click(screen.getByRole('button', { name: 'Reload forecast' }));
  expect(screen.getByRole('heading', { name: 'Loading forecast' })).toBeVisible();
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  const incomplete = fixture();
  incomplete.points.pop();
  await act(async () => resolve(jsonResponse(incomplete)));
  expect(await screen.findByRole('alert')).toHaveTextContent('incomplete or unsupported');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
});

it('ignores a stale catalog response even if a transport disregards cancellation', async () => {
  const resolvers: ((response: Response) => void)[] = [];
  const signals: AbortSignal[] = [];
  vi.stubGlobal('fetch', vi.fn((url: string, options: RequestInit) => {
    if (url !== '/api/origins') return Promise.resolve(jsonResponse());
    signals.push(options.signal as AbortSignal);
    return new Promise<Response>((resolve) => resolvers.push(resolve));
  }));
  render(<StrictMode><App /></StrictMode>);
  await waitFor(() => expect(resolvers).toHaveLength(2));
  expect(signals[0].aborted).toBe(true);
  await act(async () => resolvers[1](jsonResponse(originsFixture())));
  await screen.findByRole('table');
  await act(async () => resolvers[0](jsonResponse(originsFixture(['2026-09-07T00:00:00Z']))));
  expect(screen.getByRole('combobox', { name: 'Choose exact issue time' })).toHaveValue(fixture().forecast_origin_utc);
  expect(screen.getByText('07 Sept 2026, 10:00 UTC+3')).toBeVisible();
});

it('switches all displayed times by keyboard without another request or changed prices', async () => {
  const fetch = vi.fn().mockResolvedValue(jsonResponse());
  installForecastTransport(fetch);
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
  installForecastTransport(fetch);
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

it('changes the complete snapshot, resets chart inspection and preserves the timezone', async () => {
  const catalog = originsFixture();
  const transport = vi.fn((url: string) => Promise.resolve(jsonResponse(url === '/api/origins' ? catalog
    : selectedFixture(new URL(url, 'http://127.0.0.1').searchParams.get('origin')!))));
  vi.stubGlobal('fetch', transport);
  render(<App />);
  const user = userEvent.setup();
  await screen.findByRole('table');
  const chart = await screen.findByRole('application');
  chart.focus();
  await user.keyboard('{End}');
  expect(screen.getAllByRole('status').some((status) => status.textContent?.includes('Quarter 40 of 40'))).toBe(true);
  await user.click(screen.getByRole('button', { name: 'UTC' }));
  const before = transport.mock.calls.length;
  await user.selectOptions(screen.getByRole('combobox'), catalog.origins[1]);
  await waitFor(() => expect(within(screen.getByRole('region', { name: 'Forecast context' })).getByText('06 Sept 2026, 22:00 UTC')).toBeVisible());
  expect(screen.getByRole('button', { name: 'UTC' })).toHaveAttribute('aria-pressed', 'true');
  await screen.findByRole('application');
  expect(screen.getAllByRole('status').some((status) => status.textContent?.includes('Quarter 1 of 40'))).toBe(true);
  expect(transport.mock.calls).toHaveLength(before + 1);
});

it.each(['resolve', 'reject'])('ignores an obsolete selected-origin response that later %ss', async (completion) => {
  const catalog = originsFixture();
  let finish!: (response: Response) => void;
  let fail!: (error: Error) => void;
  let oldSignal!: AbortSignal;
  vi.stubGlobal('fetch', vi.fn((url: string, options: RequestInit) => {
    if (url === '/api/origins') return Promise.resolve(jsonResponse(catalog));
    const origin = new URL(url, 'http://127.0.0.1').searchParams.get('origin')!;
    if (origin === catalog.origins[1]) {
      oldSignal = options.signal as AbortSignal;
      return new Promise<Response>((resolve, reject) => { finish = resolve; fail = reject; });
    }
    return Promise.resolve(jsonResponse(selectedFixture(origin)));
  }));
  render(<App />);
  await screen.findByRole('table');
  const user = userEvent.setup();
  await user.selectOptions(screen.getByRole('combobox'), catalog.origins[1]);
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.queryByRole('application')).not.toBeInTheDocument();
  await waitFor(() => expect(finish).toBeDefined());
  await user.selectOptions(screen.getByRole('combobox'), catalog.origins[2]);
  await waitFor(() => expect(within(screen.getByRole('region', { name: 'Forecast context' })).getByText('04 Oct 2026, 00:00 UTC+3')).toBeVisible());
  expect(oldSignal.aborted).toBe(true);
  await act(async () => completion === 'resolve' ? finish(jsonResponse(selectedFixture(catalog.origins[1]))) : fail(new Error('PRIVATE OLD ERROR')));
  expect(within(screen.getByRole('region', { name: 'Forecast context' })).getByText('04 Oct 2026, 00:00 UTC+3')).toBeVisible();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('refreshes the catalog on retry after the backend generation changes', async () => {
  let restarted = false;
  const catalog = originsFixture();
  const newRun = '00000000-0000-4000-8000-000000000002';
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    if (url === '/api/origins') return Promise.resolve(jsonResponse({ ...catalog, run_id: restarted ? newRun : catalog.run_id }));
    const origin = new URL(url, 'http://127.0.0.1').searchParams.get('origin')!;
    return Promise.resolve(jsonResponse({ ...selectedFixture(origin), run_id: restarted ? newRun : catalog.run_id }));
  }));
  render(<App />);
  await screen.findByRole('table');
  restarted = true;
  const user = userEvent.setup();
  await user.selectOptions(screen.getByRole('combobox'), catalog.origins[1]);
  expect(await screen.findByRole('alert')).toHaveTextContent('incomplete or unsupported');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Retry connection' }));
  await screen.findByRole('table');
  expect(screen.getByRole('combobox')).toHaveValue(catalog.origins[1]);
  await user.click(screen.getByText('Model and run details'));
  expect(screen.getByText(newRun)).toBeVisible();
});

it('keeps the displayed forecast while dragging and requests only the released origin', async () => {
  const catalog = originsFixture();
  const transport = vi.fn((url: string) => Promise.resolve(jsonResponse(url === '/api/origins' ? catalog
    : selectedFixture(new URL(url, 'http://127.0.0.1').searchParams.get('origin')!))));
  vi.stubGlobal('fetch', transport);
  render(<App />);
  await screen.findByRole('table');
  const slider = screen.getByRole('slider');
  const before = transport.mock.calls.length;
  fireEvent(slider, Object.assign(new MouseEvent('pointerdown', { bubbles: true, button: 0 }), { isPrimary: true, pointerId: 8 }));
  fireEvent.change(slider, { target: { value: Date.parse(catalog.origins[1]) } });
  fireEvent.change(slider, { target: { value: Date.parse(catalog.origins[2]) } });
  expect(transport.mock.calls).toHaveLength(before);
  expect(screen.getByText('Preview · release to load')).toBeVisible();
  expect(screen.getByRole('table')).toBeVisible();
  expect(within(screen.getByRole('region', { name: 'Forecast context' })).getByText('07 Sept 2026, 00:00 UTC+3')).toBeVisible();
  fireEvent(slider, Object.assign(new MouseEvent('pointerup', { bubbles: true }), { pointerId: 8 }));
  await waitFor(() => expect(within(screen.getByRole('region', { name: 'Forecast context' })).getByText('04 Oct 2026, 00:00 UTC+3')).toBeVisible());
  expect(transport.mock.calls).toHaveLength(before + 1);
});

it('rejects a malformed catalog before requesting or displaying a forecast', async () => {
  const transport = vi.fn().mockResolvedValue(jsonResponse({ ...originsFixture(), spot_price: 'INVENTED_PRIVATE' }));
  vi.stubGlobal('fetch', transport);
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('incomplete or unsupported');
  expect(screen.queryByRole('table')).not.toBeInTheDocument();
  expect(screen.queryByRole('slider')).not.toBeInTheDocument();
  expect(screen.queryByText('INVENTED_PRIVATE')).not.toBeInTheDocument();
  expect(transport).toHaveBeenCalledTimes(1);
});
