const threeDecimals = new Intl.NumberFormat('en-GB', {
  minimumFractionDigits: 3,
  maximumFractionDigits: 3,
});

export function formatThreeDecimals(value: number): string {
  return threeDecimals.format(Math.abs(value) < 0.0005 ? 0 : value);
}
