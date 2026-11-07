import { expect, it } from 'vitest';
import { deliveryWindowEnd, formatTimestamp } from './time';

it('shows a complete ten-hour window through midnight', () => {
  expect(deliveryWindowEnd('2026-09-06T21:00:00Z')).toBe('2026-09-07T07:00:00Z');
  expect(formatTimestamp('2026-09-06T21:00:00Z')).toBe('07 Sept 2026, 00:00 UTC+3');
  expect(formatTimestamp('2026-09-06T21:00:00Z', 'UTC')).toBe('06 Sept 2026, 21:00 UTC');
});

it('distinguishes both occurrences of the repeated Helsinki hour', () => {
  expect(formatTimestamp('2026-10-25T00:00:00Z')).toBe('25 Oct 2026, 03:00 UTC+3');
  expect(formatTimestamp('2026-10-25T01:00:00Z')).toBe('25 Oct 2026, 03:00 UTC+2');
  expect(deliveryWindowEnd('2026-10-25T00:00:00Z')).toBe('2026-10-25T10:00:00Z');
});
