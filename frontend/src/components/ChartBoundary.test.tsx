import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import ChartBoundary from './ChartBoundary';

it('contains a failed chart without removing the rest of the forecast', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  function BrokenChart(): never { throw new Error('Synthetic chart load failure'); }
  render(<><ChartBoundary><BrokenChart /></ChartBoundary><p>Forecast table remains available</p></>);
  expect(screen.getByRole('alert')).toHaveTextContent('Price chart unavailable');
  expect(screen.getByText('Forecast table remains available')).toBeVisible();
  expect(screen.queryByText('Synthetic chart load failure')).not.toBeInTheDocument();
});
