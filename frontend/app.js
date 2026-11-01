"use strict";

const $ = (s, r = document) => r.querySelector(s);
const API = window.API_BASE || "";

const COLORS = {
  "AWS (managed cache/DB)": "#f59e0b",
  "GCP (managed cache/DB)": "#4f8cff",
  "GCP (self-hosted cache/DB, Meesho-style)": "#38b985",
  "Hybrid (GCP edge + own cache/DB)": "#9a6aff",
  "On-premises (all, lower bound)": "#ef647a",
};
const NAMES = {
  aws: "AWS (managed cache/DB)",
  gcp: "GCP (managed cache/DB)",
  onp: "On-premises (all, lower bound)",
};

const nf = new Intl.NumberFormat("en-US");
const usd = (v) => "$" + nf.format(Math.round(v));
const usdK = (v) => "$" + nf.format(Math.round(v / 1e3)) + "k";
const usdM = (v, d = 1) => "$" + (v / 1e6).toFixed(d) + "M";
const inrCr = (v) => v.toFixed(2);
const beText = (m, h) => (m === null || m === undefined ? `none within ${h} months` : `month ${m}`);
const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function setStatus(text, cls = "") {
  const el = $("#status");
  el.textContent = text;
  el.className = `status ${cls}`;
}
function showError(msg) {
  const el = $("#error");
  el.hidden = !msg;
  el.textContent = msg || "";
}

async function getJSON(url, opts) {
  const r = await fetch(API + url, opts);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

function defaultBody(schema) {
  const body = {};
  schema.fields.forEach((f) => {
    body[f.name] = f.type === "int" ? Math.round(f.default * f.scale) : f.default * f.scale;
  });
  schema.selects.forEach((f) => {
    body[f.name] = f.default;
  });
  return body;
}

function card(label, value, support) {
  return `<article class="card"><span class="card-glow"></span><span class="card-label">${esc(label)}</span><strong class="card-value">${value}</strong><span class="card-support">${support}</span></article>`;
}
function renderKpis(d) {
  const S = d.scenarios, fx = d.fx;
  $("#kpis").innerHTML =
    card("CDN egress / month", nf.format(Math.round(d.egress_tb_month)) + " TB", "Requests × object size") +
    card("AWS monthly", usdK(S[NAMES.aws].monthly_usd), "INR " + inrCr((S[NAMES.aws].monthly_usd * fx) / 1e7) + " Cr") +
    card("GCP monthly", usdK(S[NAMES.gcp].monthly_usd), "INR " + inrCr((S[NAMES.gcp].monthly_usd * fx) / 1e7) + " Cr") +
    card("On-prem monthly", usdK(S[NAMES.onp].monthly_usd), "Plus " + usdM(S[NAMES.onp].capex_usd, 2) + " up-front") +
    card("GCP / on-prem break-even", beText(d.breakeven_months_vs_onprem[NAMES.gcp], d.horizon_months), "cloud pricing");
}
function renderScenarioTable(d) {
  const S = d.scenarios, fx = d.fx;
  const rows = Object.keys(S)
    .map(
      (n) =>
        `<tr><td class="scenario-name"><span class="provider-dot" style="background:${COLORS[n]}"></span>${esc(n)}</td><td class="num">${usd(S[n].monthly_usd)}</td><td class="num">${inrCr((S[n].monthly_usd * fx) / 1e7)}</td><td class="num">${S[n].capex_usd ? usd(S[n].capex_usd) : "—"}</td><td class="num">${usdM(S[n].tco5_usd)}</td><td class="num">${usdM(S[n].tco10_usd)}</td></tr>`,
    )
    .join("");
  $("#scenario-table").innerHTML =
    `<thead><tr><th>Scenario</th><th class="num">Monthly (USD)</th><th class="num">Monthly (INR Cr)</th><th class="num">Up-front (USD)</th><th class="num">5-year TCO</th><th class="num">10-year TCO</th></tr></thead><tbody>${rows}</tbody>`;
}

async function init() {
  setStatus("Calculating", "busy");
  try {
    const schema = await getJSON("/schema");
    const data = await getJSON("/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(defaultBody(schema)),
    });
    renderKpis(data);
    renderScenarioTable(data);
    showError("");
    setStatus("Up to date", "ok");
  } catch (e) {
    showError("Could not reach the backend: " + e.message);
    setStatus("Connection error", "err");
  }
}
window.addEventListener("DOMContentLoaded", init);
