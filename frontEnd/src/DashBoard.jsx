import { useEffect, useRef, useState } from "react";
import { api } from "./lib/api";
import { impact, money, safeLink, stamp } from "./lib/presentation";
import PriceChart from "./components/PriceChart";

const examples = [
  ["Company research", "Who founded Microsoft and when?"],
  ["Market signals", "What major electric vehicle developments have been reported in the last 30 days? Include dates."],
  ["Competitive landscape", "Who are the main competitors of Notion and how do their offerings differ?"],
];
const tabs = [["overview", "◈", "Overview"], ["research", "✳", "AI Research"], ["competitors", "◎", "Competitors"], ["history", "◷", "History"], ["impact", "↗", "Financial Impact"]];
const blankCompare = { product_name: "", selling_price: "", currency: "EUR", brand: "", sku: "", urls: "" };
function readHistory(key) {
  try { const data = JSON.parse(localStorage.getItem(key) || "[]"); return Array.isArray(data) ? data.filter(x => typeof x.question === "string" && typeof x.answer === "string" && Array.isArray(x.sources)).slice(0, 20) : []; }
  catch { return []; }
}
function External({ url, children, ...props }) {
  const link = safeLink(url);
  return link ? <a href={link} target="_blank" rel="noopener noreferrer" {...props}>{children} ↗</a> : <span>{children}</span>;
}
function Field({ label, ...props }) {
  return <label className="field"><span>{label}</span><input {...props} /></label>;
}
export function ResearchResult({ result, savedExample = false, historical = false, panelRef }) {
  if (!result) return null;
  const facts = result.research_data?.facts || [];
  const notes = (result.research_data?.uncertainties || []).filter(x => typeof x === "string" && !/^(none|n\/a|none identified)$/i.test(x.trim()));
  return <article ref={panelRef} className="panel answer-panel" aria-live="polite" aria-label="Research answer" tabIndex={-1}>
    <div className="section-row"><span className={"status-pill " + (savedExample || historical ? "amber" : "")}>{savedExample ? "Saved verified example · NOT LIVE" : historical ? "Saved research snapshot · NOT LIVE" : result.status === "partial" ? "Partial research" : result.status === "insufficient_evidence" ? "More evidence needed" : "Live provider response"}</span><small>{stamp(result.retrieved_at)}</small></div>
    <h2>{result.question}</h2><p className="answer-text">{result.answer}</p>
    {!!result.keywords?.length && <div className="chips">{result.keywords.map((word, i) => <span key={i}>{word}</span>)}</div>}
    {!!facts.length && <dl className="facts">{facts.map((fact, i) => <div key={i}><dt>{fact.label}</dt><dd>{fact.value}</dd>{fact.source_url && <External url={fact.source_url}>Source</External>}</div>)}</dl>}
    {!!notes.length && <div className="notice"><strong>Uncertainty to keep in mind</strong><ul>{notes.map((note, i) => <li key={i}>{note}</li>)}</ul></div>}
    <div className="sources-heading"><h3>Follow the evidence</h3><span>{result.sources?.length || 0} sources</span></div>
    <div className="source-grid">{result.sources?.map((source, i) => <External key={i} url={source.url} className="source-card"><span className="source-number">{String(i + 1).padStart(2, "0")}</span><span><strong>{source.title}</strong><small>{source.publisher || source.url}{source.published_at ? " · " + source.published_at : ""}</small></span></External>)}</div>
    <p className="fine-print">{result.research_data?.evidence_note || "Sources contributed to the provider's research. Check the original pages before acting on changing information."}</p>
    {!savedExample && <small>{result.persistence === "saved" ? "Saved to your configured cloud history." : result.persistence === "unavailable" ? "Cloud save unavailable; this answer is still available." : "Cloud history is not configured. Successful results are retained in this browser when storage is available."}</small>}
  </article>;
}
export default function Dashboard({ session, audience, signOut, error: authError }) {
  const [tab, setTab] = useState("overview");
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState(null);
  const [example, setExample] = useState(false);
  const [snapshot, setSnapshot] = useState(false);
  const [busy, setBusy] = useState("");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const historyKey = "rivalsense.research." + session.user.id;
  const [history, setHistory] = useState(() => readHistory(historyKey));
  const [cloudHistory, setCloudHistory] = useState([]);
  const [cloudStatus, setCloudStatus] = useState("loading");
  const [products, setProducts] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [accountError, setAccountError] = useState("");
  const [url, setUrl] = useState("");
  const [extracted, setExtracted] = useState(null);
  const [compare, setCompare] = useState(blankCompare);
  const [comparison, setComparison] = useState(null);
  const [listings, setListings] = useState([]);
  const [prices, setPrices] = useState(null);
  const [priceProduct, setPriceProduct] = useState("");
  const [priceListing, setPriceListing] = useState("");
  const [simulation, setSimulation] = useState({ selling: "", cost: "", units: "", currency: "EUR" });
  const request = useRef(null);
  const historyRequest = useRef(null);
  const input = useRef(null);
  const resultPanel = useRef(null);
  useEffect(() => {
    if (result && tab === "research") {
      resultPanel.current?.scrollIntoView({ block: "start" });
      resultPanel.current?.focus({ preventScroll: true });
    }
  }, [result, tab]);
  useEffect(() => {
    const controller = new AbortController();
    Promise.allSettled([
      api("/api/products?limit=100", { signal: controller.signal }),
      api("/api/alerts?limit=100", { signal: controller.signal }),
      api("/api/ai/history", { signal: controller.signal }),
    ]).then(([p, a, h]) => {
      if (controller.signal.aborted) return;
      if (p.status === "fulfilled") setProducts(p.value);
      if (a.status === "fulfilled") setAlerts(a.value);
      if (h.status === "fulfilled") { setCloudHistory(h.value.items || []); setCloudStatus(h.value.status); }
      else setCloudStatus("unavailable");
      if (p.status === "rejected" || a.status === "rejected") setAccountError("Account overview is unavailable. Research and manual product checks can still be used.");
    });
    return () => { controller.abort(); request.current?.abort(); historyRequest.current?.abort(); };
  }, []);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setSeconds(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  function go(value) { setTab(value); setError(""); setNotice(""); }
  function suggest(value) { setQuestion(value); setTab("research"); input.current?.focus(); }
  async function perform(kind, action) {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setBusy(kind); setSeconds(0); setError(""); setNotice("");
    try { await action(controller.signal); }
    catch (e) { if (e.name !== "AbortError" && !controller.signal.aborted) setError(e.message); }
    finally { if (request.current === controller) setBusy(""); }
  }
  function research(event) {
    event.preventDefault();
    perform("research", async signal => {
      const response = await api("/api/ai/ask", { method: "POST", body: { question: question.trim() }, signal });
      if (signal.aborted) return;
      setResult(response); setExample(false); setSnapshot(false); setTab("research");
      const items = [response, ...history].slice(0, 20); setHistory(items);
      try { localStorage.setItem(historyKey, JSON.stringify(items)); }
      catch { setNotice("The answer is ready, but browser history could not be saved."); }
    });
  }
  function extract(event) {
    event.preventDefault(); setExtracted(null);
    perform("product", async signal => {
      const response = await api("/api/prices/extract", { method: "POST", body: { url: url.trim() }, signal });
      if (signal.aborted) return;
      setExtracted(response);
      setCompare(current => ({ ...current, product_name: response.product_name || "", brand: response.brand || "", sku: response.sku || "", currency: response.currency?.toUpperCase() || current.currency }));
    });
  }
  function compareProducts(event) {
    event.preventDefault(); setComparison(null);
    const urls = compare.urls.split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    if (!urls.length || urls.length > 5) { setError("Enter between one and five competitor URLs, one per line."); return; }
    const body = { product_name: compare.product_name, selling_price: compare.selling_price, currency: compare.currency.toUpperCase(), competitor_urls: urls,
      ...(compare.brand ? { brand: compare.brand } : {}), ...(compare.sku ? { sku: compare.sku } : {}) };
    perform("comparison", async signal => {
      const response = await api("/api/prices/compare", { method: "POST", body, signal });
      if (!signal.aborted) setComparison(response);
    });
  }
  async function loadPriceHistory(productId, listingId = "") {
    historyRequest.current?.abort();
    const controller = new AbortController(); historyRequest.current = controller;
    setError(""); setPrices(null);
    try {
      if (!listingId) {
        setPriceProduct(productId); setPriceListing(""); setListings([]);
        if (productId) {
          const rows = await api("/api/products/" + encodeURIComponent(productId) + "/competitors", { signal: controller.signal });
          if (!controller.signal.aborted) setListings(rows);
        }
      } else {
        setPriceListing(listingId);
        const rows = await api("/api/competitors/" + encodeURIComponent(listingId) + "/observations", { signal: controller.signal });
        if (!controller.signal.aborted) setPrices(rows);
      }
    } catch (e) { if (e.name !== "AbortError" && !controller.signal.aborted) setError(e.message); }
  }
  async function openExample() {
    setError("");
    try {
      const response = await fetch("/verified-example.json");
      if (!response.ok) throw new Error();
      setResult(await response.json()); setExample(true); setTab("research");
    } catch { setError("The saved example is unavailable. No sample answer was invented."); }
  }
  const projected = impact(simulation.selling, simulation.cost, simulation.units);
  const sources = new Set(history.flatMap(item => item.sources.map(source => source.url)));
  const name = session.user.user_metadata?.full_name?.split(" ")[0] || "there";
  const currentTitle = tabs.find(([id]) => id === tab)?.[2];
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">R</span><div>RivalSense<small>WEB INTELLIGENCE</small></div></div>
      <span className="nav-label">YOUR WORKSPACE</span>
      <nav aria-label="Main navigation">{tabs.map(([id, icon, label]) => <button key={id} className={tab === id ? "nav-item active" : "nav-item"} onClick={() => go(id)} aria-current={tab === id ? "page" : undefined}><span>{icon}</span>{label}{id === "research" && <small>AI</small>}</button>)}</nav>
      <div className="sidebar-note"><span className="live-dot" /><strong>Evidence first.</strong><p>Live requests, visible sources, and honest uncertainty.</p><small>Automatic monitoring is off.</small></div>
      <div className="account"><span className="avatar">{name.slice(0, 1).toUpperCase()}</span><div><strong>{name}</strong><small>{audience === "business_owner" ? "Business workspace" : audience === "reporter" ? "Research workspace" : "Your workspace"}</small></div><button className="icon-button" title="Sign out" aria-label="Sign out" onClick={signOut}>↪</button></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div><span className="breadcrumb">Workspace / </span>{currentTitle}</div><span className="provider-badge"><span className="live-dot" /> Context.dev research</span></header>
      <main className="main-content">
        {(error || authError) && <div className="error" role="alert">{error || authError}<button className="text-button" onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
        {notice && <p className="notice" role="status">{notice}</p>}
        {(tab === "overview" || tab === "research") && <>
          <section className="hero"><div className="eyebrow">YOUR NEXT MOVE STARTS WITH A BETTER QUESTION</div><h1>{tab === "overview" ? <>Good to see you, {name}.<br /><em>What will you discover today?</em></> : <>Ask the question.<br /><em>Get the evidence.</em></>}</h1><p>From a quick fact to a competitive insight. Research the web, inspect the sources, and see what matters.</p></section>
          {tab === "overview" && <div className="metrics"><div className="metric"><span>Saved research · this browser</span><strong>{history.length}</strong><small>Actual responses, retained locally</small></div><div className="metric"><span>Sources in your research</span><strong>{sources.size}</strong><small>Distinct contributing pages</small></div><div className="metric"><span>Tracked products · first 100</span><strong>{products?.length ?? "—"}</strong><small>{products ? "From your Supabase account" : "Not loaded"}</small></div><div className="metric"><span>Unread alerts · first 100</span><strong>{alerts ? alerts.filter(a => a.status === "unread").length : "—"}</strong><small>Existing records · automation off</small></div></div>}
          <section className="panel research-composer"><div className="section-row"><h2><span className="spark">✳</span> Ask RivalSense AI</h2><span className="subtle-label">SOURCED WEB RESEARCH</span></div>
            <form onSubmit={research}><label className="sr-only" htmlFor="question">Your research question</label><textarea ref={input} id="question" value={question} onChange={e => setQuestion(e.target.value)} minLength={3} maxLength={2000} required placeholder="What would you like to understand about the world—or your competition?" /><div className="composer-footer"><small>Public web sources · unknowns stay unknown</small><button className="primary" disabled={!!busy || question.trim().length < 3}>{busy === "research" ? "Researching…" : "Research question"} <span>↗</span></button></div></form>
            {!!busy && <div className="progress" role="status"><span className="spinner" /> {busy === "research" ? "Waiting for Context.dev research and sources" : "A product request is in progress"} · {seconds}s <button className="text-button" onClick={() => request.current?.abort()}>Cancel</button></div>}
          </section>
          <ResearchResult result={result} savedExample={example} historical={snapshot} panelRef={resultPanel} />
          <div className="suggestions">{examples.map(([label, value]) => <button key={label} onClick={() => suggest(value)}><span>{label} ↗</span><strong>{value}</strong></button>)}</div>
          {!result && <div className="empty-inline"><span>◎</span><p>Your next insight will appear here, with sources.</p><button className="text-button" onClick={openExample}>Open a saved, verified provider example ↗</button></div>}
          {error && <button className="text-button" onClick={openExample}>Provider unavailable? Open a saved verified example (not live)</button>}
          {accountError && <p className="fine-print">{accountError}</p>}
        </>}
        {tab === "competitors" && <>
          <section className="hero"><div className="eyebrow">COMPETITOR INTELLIGENCE</div><h1>Prices change.<br /><em>Keep your perspective.</em></h1><p>Check a product page now, then compare confirmed identities in the same currency. Each check is a manual live request.</p></section>
          <section className="panel"><h2>Read a product page</h2><form onSubmit={extract} className="url-form"><Field label="Public HTTPS product URL" type="url" required value={url} onChange={e => setUrl(e.target.value)} placeholder="https://shop.example.com/product" /><button className="primary" disabled={!!busy}>{busy === "product" ? "Extracting…" : "Check product ↗"}</button></form><button className="text-button" onClick={() => setUrl("https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html")}>Use the public book demo URL</button>
          {!!busy && <p className="progress" role="status"><span className="spinner" /> Waiting for product evidence · {seconds}s</p>}
          {extracted && <div className="product-result"><div><span className="status-pill">{extracted.status === "partial" ? "Partial extraction" : "Current extraction"}</span><h3>{extracted.product_name || "Product name unknown"}</h3><p>{extracted.availability || "Availability unknown"}</p><External url={extracted.source_url}>Original product page</External></div><div className="product-price">{money(extracted.price, extracted.currency)}<small>Received {stamp(extracted.observed_at)}</small></div>{extracted.error && <p className="notice">{extracted.error}</p>}</div>}</section>
          <section className="panel"><div className="section-row"><h2>Compare competitor prices</h2><span className="subtle-label">NO CURRENCY CONVERSION</span></div><p className="muted">An exact name plus brand, SKU, or explicit model evidence is needed to confirm a product. Uncertain matches are kept separate.</p>
            <form onSubmit={compareProducts}><div className="form-grid"><Field label="Reference product name" required value={compare.product_name} onChange={e => setCompare({ ...compare, product_name: e.target.value })} /><Field label="Your selling price" required type="number" min="0" step="0.01" value={compare.selling_price} onChange={e => setCompare({ ...compare, selling_price: e.target.value })} /><Field label="Currency (ISO code)" required maxLength={3} pattern="[A-Za-z]{3}" value={compare.currency} onChange={e => setCompare({ ...compare, currency: e.target.value.toUpperCase() })} /><Field label="Brand (if known)" value={compare.brand} onChange={e => setCompare({ ...compare, brand: e.target.value })} /><Field label="SKU (if known)" value={compare.sku} onChange={e => setCompare({ ...compare, sku: e.target.value })} /></div><label className="field"><span>Competitor HTTPS product URLs · one per line, up to five</span><textarea required rows={3} value={compare.urls} onChange={e => setCompare({ ...compare, urls: e.target.value })} placeholder="https://competitor.example.com/product" /></label><button className="primary" disabled={!!busy}>{busy === "comparison" ? "Comparing…" : "Compare with evidence ↗"}</button></form>
            {comparison && <div className="comparison-results"><p><strong>{comparison.comparable_count}</strong> confirmed comparable results · {comparison.status}</p><PriceChart comparison={comparison} /><div className="comparison-grid">{comparison.competitors.map((item, i) => <article className="comparison-card" key={i}><span className={"status-pill " + (item.comparable ? "" : "amber")}>{item.matching_status.replaceAll("_", " ")}</span><h3>{item.product_name || "Product unavailable"}</h3><strong className="price">{money(item.price, item.currency)}</strong><p>{item.comparison_reason}</p><small>{item.matching_reason}</small>{item.comparable && <p>Difference from your price: <strong>{money(item.price_difference, comparison.currency)}</strong></p>}{item.extraction_error && <p className="notice">{item.extraction_error}</p>}<External url={item.source_url}>View source</External><small>Checked {stamp(item.observed_at)}</small></article>)}</div></div>}
          </section>
        </>}
        {tab === "history" && <>
          <section className="hero"><div className="eyebrow">YOUR RESEARCH TRAIL</div><h1>Good insights<br /><em>deserve a second look.</em></h1><p>Saved results are snapshots, not current observations. Check their dates before making a decision.</p></section>
          <section className="panel"><div className="section-row"><h2>Research history</h2><span className="status-pill">{cloudStatus === "available" ? "Cloud connected" : "This browser"}</span></div><p className="muted">{cloudStatus === "available" ? "Your cloud results and this browser's recent research." : "Cloud history is not configured or unavailable. Up to 20 results are saved in this browser for this account."}</p>
          {!history.length && !cloudHistory.length ? <div className="empty-inline"><p>No saved research yet. Start with a question.</p><button className="secondary" onClick={() => go("research")}>Ask RivalSense ↗</button></div> : <div className="history-list">{[...history.map(x => ({ ...x, storage: "Browser" })), ...cloudHistory.map(x => ({ ...x, storage: "Cloud" }))].map((item, i) => <button key={item.id || i} onClick={() => { setResult(item); setExample(false); setSnapshot(true); setTab("research"); }}><span className="history-icon">↗</span><span><strong>{item.question}</strong><small>{stamp(item.retrieved_at || item.created_at)} · {item.storage} snapshot · {item.sources?.length || 0} sources</small></span><span>→</span></button>)}</div>}</section>
          <section className="panel"><h2>Saved price observations</h2><p className="muted">Read existing price history. New trusted capture remains disabled pending migration validation.</p><div className="form-grid"><label className="field"><span>Tracked product</span><select value={priceProduct} onChange={e => loadPriceHistory(e.target.value)}><option value="">Select a product</option>{products?.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label><label className="field"><span>Competitor listing</span><select value={priceListing} disabled={!listings.length} onChange={e => loadPriceHistory(priceProduct, e.target.value)}><option value="">Select a listing</option>{listings.map(p => <option key={p.id} value={p.id}>{p.competitor_name}</option>)}</select></label></div>
          {prices?.length ? <div className="table-wrap"><table><thead><tr><th>Observed</th><th>Price</th><th>Match</th><th>Source</th></tr></thead><tbody>{prices.map(p => <tr key={p.id}><td>{stamp(p.observed_at)}</td><td>{money(p.price, p.currency)}</td><td>{p.matching_status?.replaceAll("_", " ") || "Needs review"}</td><td><External url={p.source_url}>Source</External></td></tr>)}</tbody></table></div> : <p className="empty-copy">{prices ? "No observations saved for this listing." : products?.length ? "Choose a product and listing to inspect history." : "No tracked products are available."}</p>}</section>
        </>}
        {tab === "impact" && <>
          <section className="hero"><div className="eyebrow">EXPLORE THE WHAT-IF</div><h1>Turn a price<br /><em>into perspective.</em></h1><p>A simple gross-profit scenario using your inputs. Estimates exclude tax, shipping, overhead, and any change in demand.</p></section>
          <section className="panel impact-panel"><span className="status-pill amber">Hypothetical estimates · not a forecast</span><h2>Financial impact simulator</h2><div className="form-grid">{[["selling", "Selling price per unit"], ["cost", "Product cost per unit"], ["units", "Estimated units sold"]].map(([key, label]) => <Field key={key} label={label} type="number" min="0" step={key === "units" ? "1" : "0.01"} value={simulation[key]} onChange={e => setSimulation({ ...simulation, [key]: e.target.value })} />)}<Field label="Currency" maxLength={3} value={simulation.currency} onChange={e => setSimulation({ ...simulation, currency: e.target.value.toUpperCase() })} /></div>
          {projected ? <div className="impact-results"><div><span>Estimated gross profit</span><strong>{money(projected.grossProfit, simulation.currency)}</strong></div><div><span>Gross margin</span><strong>{projected.margin == null ? "Undefined at zero price" : projected.margin.toFixed(1) + "%"}</strong></div><div><span>Estimated revenue</span><strong>{money(projected.revenue, simulation.currency)}</strong></div></div> : <p className="empty-copy">Enter non-negative prices and a whole number of units to explore a scenario.</p>}</section>
        </>}
      </main>
      <footer className="workspace-footer"><span>RivalSense · Clarity from the live web.</span><span>Sources over assumptions.</span></footer>
    </div>
  </div>;
}
