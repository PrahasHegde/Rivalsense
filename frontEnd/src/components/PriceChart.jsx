import { money } from "../lib/presentation";
export default function PriceChart({ comparison }) {
  if (!comparison?.comparable_count) return null;
  const rows = [
    { label: "Your price · input", price: comparison.selling_price, currency: comparison.currency, own: true },
    ...comparison.competitors.filter(item => item.comparable).map(item => ({ label: item.product_name || "Confirmed competitor", price: item.price, currency: item.currency })),
  ].filter(item => item.price != null && Number.isFinite(Number(item.price)));
  const maximum = Math.max(1, ...rows.map(item => Number(item.price)));
  return <figure className="price-chart"><figcaption>Confirmed same-currency prices <small>Current fetched observations and your input</small></figcaption>
    {rows.map((row, i) => <div className="price-bar-row" key={i}><span>{row.label}</span><div className="price-bar-track" aria-hidden="true"><div className={row.own ? "price-bar own" : "price-bar"} style={{ width: Math.max(0, Number(row.price) * 100 / maximum) + "%" }} /></div><strong>{money(row.price, row.currency)}</strong></div>)}
  </figure>;
}
