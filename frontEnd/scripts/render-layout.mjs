// Static responsive-layout review only. No auth tokens, effects, or live API calls.
import { createServer } from "vite";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const server = await createServer({ server: { middlewareMode: true }, appType: "custom" });
try {
  const { default: Dashboard, ResearchResult } = await server.ssrLoadModule("/src/DashBoard.jsx");
  const { default: App } = await server.ssrLoadModule("/src/App.jsx");
  const welcome = renderToStaticMarkup(React.createElement(App));
  if (!welcome.includes("RivalSense")) throw new Error("Signed-out/loading shell failed to render");
  console.log("App shell render passed (no user account or API request).");
  const sample = JSON.parse(await readFile(new URL("../public/verified-example.json", import.meta.url), "utf8"));
  const historyMarkup = renderToStaticMarkup(React.createElement(ResearchResult, { result: sample, historical: true }));
  if (!historyMarkup.includes("Saved research snapshot") || historyMarkup.includes("Live provider response")) throw new Error("Historical response mislabeled as live");
  const exampleMarkup = renderToStaticMarkup(React.createElement(ResearchResult, { result: sample, savedExample: true }));
  if (!exampleMarkup.includes("NOT LIVE")) throw new Error("Example response mislabeled");
  console.log("Historical/example provenance render checks passed.");
  const markup = renderToStaticMarkup(React.createElement(Dashboard, {
    session: { user: { id: "static-layout-review-only", user_metadata: { full_name: "Layout preview" } } },
    audience: null, signOut() {},
  }));
  const css = await readFile(new URL("../src/App.css", import.meta.url), "utf8");
  const output = join(tmpdir(), "RivalSense-layout-review.html");
  await writeFile(output, '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style></head><body><div style="position:fixed;bottom:5px;right:5px;z-index:100;background:#fff0cc;padding:8px;font:11px sans-serif">STATIC LAYOUT REVIEW · NOT SIGNED IN · NO LIVE DATA</div>'+markup+'</body></html>', "utf8");
  console.log("Static layout artifact: " + output);
} finally { await server.close(); }
