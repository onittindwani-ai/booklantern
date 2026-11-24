/** Money comes from the API as integer minor units. These helpers only format it for display, they never add or round money. */
export function money(minor: number, symbol = "$"): string {
  const neg = minor < 0;
  const n = Math.abs(Math.trunc(minor));
  const whole = Math.trunc(n / 100).toLocaleString("en-US");
  return `${neg ? "-" : ""}${symbol}${whole}.${String(n % 100).padStart(2, "0")}`;
}
export const moneyShort = (minor: number): string => {
  const a = Math.abs(minor) / 100;
  const s = a >= 1_000_000 ? `${(a / 1_000_000).toFixed(1)}M` : a >= 1000 ? `${Math.round(a / 1000)}k` : String(Math.round(a));
  return `${minor < 0 ? "-" : ""}$${s}`;
};
export const bpPercent = (bp: number) => `${(bp / 100).toFixed(bp % 100 === 0 ? 0 : 2)}%`;
export const qty = (milli: number) => (milli % 1000 === 0 ? String(milli / 1000) : String(milli / 1000));

const SYMBOL: Record<string, string> = { USD: "$", EUR: "€", GBP: "£" };
const NO_DECIMALS = new Set(["JPY", "KRW"]);
/** Format an amount in its own currency: a symbol where there is a common one, otherwise the code. Display only. */
export function moneyIn(minor: number, currency: string): string {
  if (NO_DECIMALS.has(currency)) return `${minor < 0 ? "-" : ""}${Math.abs(Math.trunc(minor)).toLocaleString("en-US")} ${currency}`;
  const sym = SYMBOL[currency];
  return sym ? money(minor, sym) : `${money(minor, "")} ${currency}`;
}
