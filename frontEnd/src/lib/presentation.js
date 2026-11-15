export function safeLink(value) {
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
  catch { return null; }
}
export function money(value, currency) {
  if (value === null || value === undefined || value === "") return "Unknown";
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "Unknown";
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency }).format(amount); }
  catch { return amount.toLocaleString() + (currency ? " " + currency : ""); }
}
export function stamp(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Time unavailable" : date.toLocaleString();
}
export function impact(selling, cost, units) {
  if ([selling, cost, units].some(v => v === "" || v == null || !Number.isFinite(Number(v)) || Number(v) < 0) || !Number.isInteger(Number(units))) return null;
  const revenue = Number(selling) * Number(units), grossProfit = (Number(selling) - Number(cost)) * Number(units);
  return { revenue, grossProfit, margin: Number(selling) > 0 ? (Number(selling) - Number(cost)) * 100 / Number(selling) : null };
}
