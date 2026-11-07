/** Explicit display zones keep replay independent of the viewer's machine timezone. */
export type DisplayZone = 'Europe/Helsinki' | 'UTC';

export function formatTimestamp(value: string, timeZone: DisplayZone = 'Europe/Helsinki'): string {
  return new Intl.DateTimeFormat('en-GB', {
    timeZone, year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZoneName: 'shortOffset',
  }).format(new Date(value)).replace('GMT', 'UTC');
}

export function deliveryWindowEnd(origin: string): string {
  return new Date(Date.parse(origin) + 10 * 60 * 60 * 1000).toISOString().replace('.000Z', 'Z');
}
