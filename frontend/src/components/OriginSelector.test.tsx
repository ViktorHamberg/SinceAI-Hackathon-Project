import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import OriginSelector, { nearestOriginIndex } from './OriginSelector';
import { originsFixture } from '../test/fixture';

const origins = originsFixture().origins;
const first = origins[0];

it('renders all 28 daily marks and allows selection of the last forecast', async () => {
  const daily = Array.from({ length: 28 }, (_, day) =>
    new Date(Date.parse(first) + day * 86_400_000).toISOString().replace('.000Z', 'Z'));
  const onSelect = vi.fn();
  const { container } = render(<OriginSelector origins={daily} selectedOrigin={daily[0]}
    displayedOrigin={daily[0]} loading={false} zone="Europe/Helsinki" onSelect={onSelect} />);
  expect(container.querySelectorAll('[data-origin]')).toHaveLength(28);
  expect(screen.getByRole('combobox', { name: 'Choose exact issue time' }).querySelectorAll('option')).toHaveLength(28);
  await userEvent.setup().selectOptions(screen.getByRole('combobox', { name: 'Choose exact issue time' }), daily[27]);
  expect(onSelect).toHaveBeenCalledWith(daily[27]);
});
function setup() {
  const onSelect = vi.fn();
  const props = { origins, selectedOrigin: first, displayedOrigin: first, loading: false, zone: 'Europe/Helsinki' as const, onSelect };
  return { ...render(<OriginSelector {...props} />), props, onSelect };
}

beforeEach(() => {
  vi.stubGlobal('PointerEvent', class extends MouseEvent {
    pointerId: number;
    isPrimary: boolean;
    constructor(type: string, options: PointerEventInit = {}) {
      super(type, options);
      this.pointerId = options.pointerId ?? 1;
      this.isPrimary = options.isPrimary ?? true;
    }
  });
});

it('spaces marks by elapsed UTC time and snaps to real origins with earlier ties', () => {
  const { container } = setup();
  const marks = container.querySelectorAll('[data-origin]');
  expect(marks).toHaveLength(3);
  expect(Number(marks[0].getAttribute('x1'))).toBe(0);
  expect(Number(marks[1].getAttribute('x1'))).toBeCloseTo(1000 / 648, 5);
  expect(Number(marks[2].getAttribute('x1'))).toBe(1000);
  expect(nearestOriginIndex(origins, Date.parse(first) + 30 * 60_000)).toBe(0);
  expect(nearestOriginIndex(origins, Date.parse(first) + 40 * 60_000)).toBe(1);
  expect(nearestOriginIndex(origins, Date.parse(origins[2]) - 3600_000)).toBe(2);
  expect(screen.getByText(/gaps have no cached forecasts/)).toBeVisible();
});

it('previews without selecting during drag and commits once on release', () => {
  const { onSelect } = setup();
  const slider = screen.getByRole('slider');
  fireEvent.pointerDown(slider, { pointerId: 8, button: 0, isPrimary: true });
  fireEvent.change(slider, { target: { value: Date.parse(origins[1]) } });
  expect(onSelect).not.toHaveBeenCalled();
  expect(screen.getByText('Preview · release to load')).toBeVisible();
  expect(slider).toHaveAttribute('aria-valuetext', expect.stringContaining('forecast 2 of 3'));
  expect(screen.getByText(/Displayed forecast:/)).toHaveTextContent('00:00 UTC+3');
  fireEvent.change(slider, { target: { value: Date.parse(origins[2]) } });
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.pointerUp(slider, { pointerId: 8 });
  expect(onSelect).toHaveBeenCalledExactlyOnceWith(origins[2]);
});

it('cancels a drag without committing and ignores a release from another pointer', () => {
  const { onSelect } = setup();
  const slider = screen.getByRole('slider');
  fireEvent.pointerDown(slider, { pointerId: 4, button: 0, isPrimary: true });
  fireEvent.change(slider, { target: { value: Date.parse(origins[2]) } });
  fireEvent.pointerUp(slider, { pointerId: 5 });
  expect(onSelect).not.toHaveBeenCalled();
  fireEvent.pointerCancel(slider, { pointerId: 4 });
  fireEvent.change(slider, { target: { value: Date.parse(origins[2]) } });
  fireEvent.pointerUp(slider, { pointerId: 4 });
  expect(onSelect).not.toHaveBeenCalled();
  expect(slider).toHaveValue(String(Date.parse(first)));
});

it('provides bounded keyboard, exact-time and forecast-button alternatives', async () => {
  const { onSelect, rerender, props } = setup();
  const user = userEvent.setup();
  const slider = screen.getByRole('slider');
  slider.focus();
  await user.keyboard('{ArrowLeft}');
  expect(onSelect).not.toHaveBeenCalled();
  await user.keyboard('{ArrowRight}');
  expect(onSelect).toHaveBeenLastCalledWith(origins[1]);
  rerender(<OriginSelector {...props} selectedOrigin={origins[1]} />);
  await user.keyboard('{End}');
  expect(onSelect).toHaveBeenLastCalledWith(origins[2]);
  rerender(<OriginSelector {...props} selectedOrigin={origins[2]} />);
  expect(screen.getByRole('button', { name: 'Next forecast' })).toBeDisabled();
  await user.keyboard('{Home}');
  expect(onSelect).toHaveBeenLastCalledWith(first);
  await user.selectOptions(screen.getByRole('combobox'), origins[1]);
  expect(onSelect).toHaveBeenLastCalledWith(origins[1]);
  await user.click(screen.getByRole('button', { name: 'Previous forecast' }));
  expect(onSelect).toHaveBeenLastCalledWith(origins[1]);
  rerender(<OriginSelector {...props} selectedOrigin={first} />);
  expect(screen.getByRole('button', { name: 'Previous forecast' })).toBeDisabled();
});

it('retains UTC identity through repeated Helsinki hours and handles one available origin', () => {
  const dates = ['2026-10-25T00:00:00Z', '2026-10-25T01:00:00Z'];
  const onSelect = vi.fn();
  const { rerender } = render(<OriginSelector origins={dates} selectedOrigin={dates[0]} displayedOrigin={null} loading zone="Europe/Helsinki" onSelect={onSelect} />);
  expect(screen.getByRole('option', { name: /03:00 UTC\+3/ })).toHaveValue(dates[0]);
  expect(screen.getByRole('option', { name: /03:00 UTC\+2/ })).toHaveValue(dates[1]);
  rerender(<OriginSelector origins={[first]} selectedOrigin={first} displayedOrigin={null} loading={false} zone="UTC" onSelect={onSelect} />);
  expect(screen.getByRole('slider')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Previous forecast' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Next forecast' })).toBeDisabled();
});
