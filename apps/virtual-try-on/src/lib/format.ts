const CURRENCY = process.env.NEXT_PUBLIC_STORE_CURRENCY || 'USD';
const LOCALE = process.env.NEXT_PUBLIC_STORE_LOCALE || 'en-US';

const money = new Intl.NumberFormat(LOCALE, {
  style: 'currency',
  currency: CURRENCY,
  maximumFractionDigits: 0,
});

export function formatPrice(value: number): string {
  return money.format(value);
}

export function formatCount(value: number, singular: string, plural = `${singular}s`): string {
  return `${value} ${value === 1 ? singular : plural}`;
}
