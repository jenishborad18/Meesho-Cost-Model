"use strict";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const API = window.API_BASE || "";
const COLORS = {
  "AWS (managed cache/DB)": "#f59e0b",
  "GCP (managed cache/DB)": "#4f8cff",
  "GCP (self-hosted cache/DB, Meesho-style)": "#38b985",
  "Hybrid (GCP edge + own cache/DB)": "#9a6aff",
  "On-premises (all, lower bound)": "#ef647a",
};
const GROUP_COLORS = [
  "#4f8cff",
  "#38b985",
  "#f6b34f",
  "#ef647a",
  "#9a6aff",
  "#94a3b8",
];
const SHORT = {
  "AWS (managed cache/DB)": "AWS managed",
  "GCP (managed cache/DB)": "GCP managed",
  "GCP (self-hosted cache/DB, Meesho-style)": "GCP self-hosted",
  "Hybrid (GCP edge + own cache/DB)": "Hybrid",
  "On-premises (all, lower bound)": "On-prem (lower bound)",
};
const NAMES = {
  aws: "AWS (managed cache/DB)",
  gcp: "GCP (managed cache/DB)",
  self: "GCP (self-hosted cache/DB, Meesho-style)",
  hyb: "Hybrid (GCP edge + own cache/DB)",
  onp: "On-premises (all, lower bound)",
};
const GROUPS = [
  [
    "Workload",
    "A clear picture of traffic, storage, and object size.",
    ["storage_tb", "cdn_requests_per_day", "avg_object_kb"],
  ],
  [
    "CDN and caching",
    "Tune edge delivery and the memory needed to keep hot data close.",
    ["cache_hit", "cache_ram_gb"],
  ],
  [
    "Compute",
    "Capture baseline capacity, sale-day peaks, and database sizing.",
    [
      "baseline_vcpu",
      "peak_ratio",
      "peak_time_fraction",
      "db_vcpu",
      "db_ssd_tb",
    ],
  ],
  [
    "Infrastructure",
    "Model ownership footprint and operational investment.",
    ["onprem_sites", "migration_usd", "selfhost_staff", "onprem_case"],
  ],
  [
    "Pricing",
    "Set commercial commitments, discounts, currency, and the planning horizon.",
    ["commit", "commit_share", "egress_discount", "fx", "horizon_months"],
  ],
];
const state = {
  schema: null,
  values: {},
  defaults: {},
  data: null,
  prices: null,
  charts: {},
  pricesLoaded: false,
  timer: null,
  seq: 0,
  currentPage: "overview",
};

const nf = new Intl.NumberFormat("en-US");
const usd = (v) => "$" + nf.format(Math.round(v));
const usdK = (v) => "$" + nf.format(Math.round(v / 1e3)) + "k";
const usdM = (v, d = 1) => "$" + (v / 1e6).toFixed(d) + "M";
const inrCr = (v) => v.toFixed(2);
const beText = (m, h) =>
  m === null || m === undefined ? `none within ${h} months` : `month ${m}`;
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const decimals = (step) => (String(step).split(".")[1] || "").length;

function setStatus(text, cls = "") {
  const el = $("#status");
  el.textContent = text;
  el.className = `status ${cls}`;
}
function setConfigState(text, dirty = false) {
  const el = $("#config-state");
  el.textContent = text;
  el.classList.toggle("dirty", dirty);
}
function showError(msg) {
  const el = $("#error");
  el.hidden = !msg;
  el.textContent = msg || "";
}
function chartTokens() {
  const cs = getComputedStyle(document.documentElement);
  return {
    text: cs.getPropertyValue("--chart-text").trim(),
    grid: cs.getPropertyValue("--chart-grid").trim(),
    surface: cs.getPropertyValue("--tooltip-bg").trim(),
  };
}

async function getJSON(url, opts) {
  const r = await fetch(API + url, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = Array.isArray(j.detail)
        ? j.detail
            .map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg}`)
            .join("\n")
        : j.detail || detail;
    } catch (_) {
      /* readable status is enough */
    }
    const e = new Error(detail);
    e.status = r.status;
    throw e;
  }
  return r.json();
}

function getField(name) {
  return (
    state.schema.fields.find((f) => f.name === name) ||
    state.schema.selects.find((f) => f.name === name)
  );
}
function makeNumberField(f) {
  const d = decimals(f.step),
    wrap = document.createElement("div");
  wrap.className = "field";
  wrap.innerHTML = `<div class="field-label"><label for="f-${f.name}">${esc(f.label)}</label><span class="unit">${esc(f.unit)}</span></div><div class="input-row"><input type="number" id="f-${f.name}" name="${f.name}" min="${f.min}" max="${f.max}" step="${f.step}" inputmode="decimal"><span class="input-unit">${esc(f.unit)}</span></div><input class="range" type="range" id="r-${f.name}" min="${f.min}" max="${f.max}" step="${f.step}" aria-label="${esc(f.label)} slider"><small>${esc(f.help)}</small>`;
  const num = $("#f-" + f.name, wrap),
    rng = $("#r-" + f.name, wrap);
  const set = (value) => {
    const v = Number(value);
    num.value = v.toFixed(d);
    rng.value = String(v);
    state.values[f.name] = v;
  };
  const initial = Number(Number(f.default).toFixed(Math.max(d, 3)));
  state.defaults[f.name] = initial;
  set(initial);
  rng.addEventListener("input", () => {
    set(rng.value);
    touch();
  });
  num.addEventListener("input", () => {
    const value = Number(num.value);
    if (!Number.isFinite(value)) return;
    if (value < Number(f.min) || value > Number(f.max)) {
      num.setCustomValidity(`Enter a value from ${f.min} to ${f.max}.`);
      touch("Fix the highlighted value before calculating.", true);
      return;
    }
    num.setCustomValidity("");
    rng.value = String(value);
    state.values[f.name] = value;
    touch();
  });
  // Keep an exact value typed by the user. Slider moves retain their defined precision.
  return wrap;
}
function makeSelectField(f) {
  const wrap = document.createElement("div");
  wrap.className = "field select-field";
  wrap.innerHTML = `<div class="field-label"><label for="f-${f.name}">${esc(f.label)}</label></div><select id="f-${f.name}" name="${f.name}">${f.options.map((o) => `<option value="${esc(o)}">${esc(o.replaceAll("_", " "))}</option>`).join("")}</select><small>${f.name === "commit" ? "Commitment changes the cloud rate used in the model." : "Select the cost assumption to evaluate."}</small>`;
  state.defaults[f.name] = f.default;
  state.values[f.name] = f.default;
  const select = $("select", wrap);
  select.value = f.default;
  select.addEventListener("change", () => {
    state.values[f.name] = select.value;
    touch();
  });
  return wrap;
}
function buildForm(schema) {
  const form = $("#form");
  form.innerHTML = "";
  GROUPS.forEach(([title, description, names], index) => {
    const fields = names.map(getField).filter(Boolean);
    if (!fields.length) return;
    const section = document.createElement("section");
    section.className = "config-group";
    section.innerHTML = `<div class="config-group-head"><span class="group-index">0${index + 1}</span><div><h2>${title}</h2><p>${description}</p></div></div><div class="fields-grid"></div>`;
    const grid = $(".fields-grid", section);
    fields.forEach((f) =>
      grid.appendChild(
        "options" in f ? makeSelectField(f) : makeNumberField(f),
      ),
    );
    form.appendChild(section);
  });
}
function formIsValid() {
  /* `step` is a slider convenience, not a backend restriction. The API only
     constrains type and min/max, so exact typed values inside those bounds work. */
  return $$("#form input[type=number]").every((el) => {
    const value = Number(el.value);
    return (
      el.value !== "" &&
      Number.isFinite(value) &&
      value >= Number(el.min) &&
      value <= Number(el.max)
    );
  });
}
function touch(message, invalid = false) {
  setConfigState(message || "Unsaved changes", true);
  if (!invalid) scheduleEvaluate();
}
function resetForm() {
  state.schema.fields.forEach((f) => {
    const d = decimals(f.step),
      v = state.defaults[f.name];
    state.values[f.name] = v;
    $("#f-" + f.name).value = Number(v).toFixed(d);
    $("#r-" + f.name).value = v;
  });
  state.schema.selects.forEach((f) => {
    state.values[f.name] = state.defaults[f.name];
    $("#f-" + f.name).value = state.defaults[f.name];
  });
  setConfigState("Defaults restored", true);
  scheduleEvaluate(0);
}
function requestBody() {
  const body = {};
  state.schema.fields.forEach((f) => {
    body[f.name] = state.values[f.name] * f.scale;
  });
  state.schema.selects.forEach((f) => {
    body[f.name] = state.values[f.name];
  });
  state.schema.fields
    .filter((f) => f.type === "int")
    .forEach((f) => {
      body[f.name] = Math.round(body[f.name]);
    });
  return body;
}
function scheduleEvaluate(delay = 450) {
  clearTimeout(state.timer);
  state.timer = setTimeout(evaluate, delay);
}
async function evaluate() {
  if (!formIsValid()) {
    showError(
      "Please correct values that fall outside the allowed range before recalculating.",
    );
    setStatus("Needs input", "err");
    return;
  }
  const seq = ++state.seq;
  setStatus("Calculating", "busy");
  try {
    const data = await getJSON("/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody()),
    });
    if (seq !== state.seq) return;
    state.data = data;
    showError("");
    render(data);
    setStatus("Up to date", "ok");
    setConfigState("Synced");
  } catch (e) {
    if (seq !== state.seq) return;
    showError(
      e.status === 422
        ? "Some inputs are out of range:\n" + e.message
        : "Could not reach the backend: " + e.message,
    );
    setStatus("Connection error", "err");
  }
}

function card(cls, label, value, support) {
  return `<article class="card ${cls}"><span class="card-glow"></span><span class="card-label">${esc(label)}</span><strong class="card-value">${value}</strong><span class="card-support">${support}</span></article>`;
}
function renderKpis(d) {
  const S = d.scenarios,
    fx = d.fx;
  const html =
    card(
      "",
      "CDN egress / month",
      nf.format(Math.round(d.egress_tb_month)) + " TB",
      "Requests × object size",
    ) +
    card(
      "aws",
      "AWS monthly",
      usdK(S[NAMES.aws].monthly_usd),
      "INR " + inrCr((S[NAMES.aws].monthly_usd * fx) / 1e7) + " Cr",
    ) +
    card(
      "gcp",
      "GCP monthly",
      usdK(S[NAMES.gcp].monthly_usd),
      "INR " + inrCr((S[NAMES.gcp].monthly_usd * fx) / 1e7) + " Cr",
    ) +
    card(
      "onp",
      "On-prem monthly",
      usdK(S[NAMES.onp].monthly_usd),
      "Plus " + usdM(S[NAMES.onp].capex_usd, 2) + " up-front",
    ) +
    card(
      "violet",
      "GCP / on-prem break-even",
      beText(d.breakeven_months_vs_onprem[NAMES.gcp], d.horizon_months),
      { "3y": "3-year", "1y": "1-year", on_demand: "on-demand" }[d.commit] +
        " cloud pricing",
    );
  $("#kpis").innerHTML = html;
  $("#analysis-kpis").innerHTML = html;
}
function scenarioRows(d) {
  const S = d.scenarios,
    fx = d.fx;
  return Object.keys(S)
    .map(
      (n) =>
        `<tr><td class="scenario-name"><span class="provider-dot" style="background:${COLORS[n]}"></span>${esc(n)}</td><td class="num">${usd(S[n].monthly_usd)}</td><td class="num">${inrCr((S[n].monthly_usd * fx) / 1e7)}</td><td class="num">${S[n].capex_usd ? usd(S[n].capex_usd) : "—"}</td><td class="num">${usdM(S[n].tco5_usd)}</td><td class="num">${usdM(S[n].tco10_usd)}</td></tr>`,
    )
    .join("");
}
function renderScenarioTable(d) {
  const html = `<thead><tr><th>Scenario</th><th class="num">Monthly (USD)</th><th class="num">Monthly (INR Cr)</th><th class="num">Up-front (USD)</th><th class="num">5-year TCO</th><th class="num">10-year TCO</th></tr></thead><tbody>${scenarioRows(d)}</tbody>`;
  $("#scenario-table").innerHTML = html;
  $("#analysis-scenario-table").innerHTML = html;
}
function renderFindings(d) {
  const S = d.scenarios,
    cloudDelta = S[NAMES.gcp].monthly_usd - S[NAMES.onp].monthly_usd,
    be = d.breakeven_months_vs_onprem[NAMES.gcp];
  $("#findings").innerHTML =
    `<div class="section-heading"><div><span class="eyebrow">Signal, not noise</span><h2>Key findings</h2></div></div><div class="finding"><span class="finding-number">${usdK(cloudDelta)}</span><p>monthly difference between GCP managed and the on-premises lower bound.</p></div><div class="finding"><span class="finding-icon">↗</span><p><strong>${beText(be, d.horizon_months)}</strong> is the modeled crossover for GCP managed versus on-premises.</p></div><div class="finding"><span class="finding-icon">◎</span><p>Hybrid keeps cloud edge delivery while moving cache and databases into your control.</p></div><button class="text-button page-link" data-goto="analysis" type="button">Open detailed analysis <span aria-hidden="true">→</span></button>`;
}
function makeChart(key, canvasId, config) {
  if (typeof Chart === "undefined") {
    $("#" + canvasId).parentElement.insertAdjacentHTML(
      "beforeend",
      "<p class='note'>Chart library not loaded.</p>",
    );
    return;
  }
  if (state.charts[key]) state.charts[key].destroy();
  state.charts[key] = new Chart($("#" + canvasId), config);
}
function renderGroupsChart(d) {
  const S = d.scenarios,
    names = Object.keys(S),
    groups = [...new Set(names.flatMap((n) => Object.keys(S[n].groups)))],
    t = chartTokens();
  makeChart("groups", "chart-groups", {
    type: "bar",
    data: {
      labels: names.map((n) => SHORT[n]),
      datasets: groups.map((g, i) => ({
        label: g,
        data: names.map((n) => (S[n].groups[g] || 0) / 1e3),
        backgroundColor: GROUP_COLORS[i % GROUP_COLORS.length],
        borderRadius: 5,
        borderSkipped: false,
        maxBarThickness: 60,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 420 },
      scales: {
        x: {
          stacked: true,
          grid: { display: false },
          ticks: { color: t.text, font: { family: "Manrope", weight: "600" } },
          border: { display: false },
        },
        y: {
          stacked: true,
          title: {
            display: true,
            text: "USD thousands / month",
            color: t.text,
          },
          ticks: { color: t.text },
          grid: { color: t.grid },
          border: { display: false },
        },
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            color: t.text,
            boxWidth: 9,
            boxHeight: 9,
            padding: 18,
            usePointStyle: true,
          },
        },
        tooltip: {
          backgroundColor: `rgba(17, 17, 17, 0.8)`,
          titleColor: "white",
          bodyColor: "white",
          padding: 12,
          callbacks: {
            label: (c) =>
              `${c.dataset.label}: $${Math.round(c.parsed.y).toLocaleString("en-US")}k`,
          },
        },
      },
    },
  });
}
function breakevenCard(label, m, h) {
  return card(
    m === null ? "" : "gcp",
    label,
    beText(m, h),
    m === null
      ? "Cloud stays cheaper over this horizon"
      : "Cumulative on-prem cost falls below cloud",
  );
}
function renderBreakeven(d) {
  const a = d.breakeven_months_vs_onprem,
    b = d.breakeven_months_vs_hybrid;
  $("#breakeven-cards").innerHTML =
    breakevenCard("GCP vs on-prem", a[NAMES.gcp], d.horizon_months) +
    breakevenCard("AWS vs on-prem", a[NAMES.aws], d.horizon_months) +
    breakevenCard("GCP vs hybrid", b[NAMES.gcp], d.horizon_months) +
    breakevenCard("Self-hosted GCP vs hybrid", b[NAMES.self], d.horizon_months);
}
function renderCumulativeChart(d) {
  const S = d.scenarios,
    names = Object.keys(S),
    be = d.breakeven_months_vs_onprem[NAMES.gcp],
    t = chartTokens();
  const datasets = names.map((n) => ({
    label: n,
    data: S[n].cumulative_usd.map((v, i) => ({ x: i, y: v / 1e6 })),
    borderColor: COLORS[n],
    backgroundColor: COLORS[n],
    borderWidth: n === NAMES.onp || n === NAMES.gcp ? 3 : 1.75,
    pointRadius: 0,
    pointHoverRadius: 4,
    tension: 0.18,
  }));
  if (be !== null && be !== undefined)
    datasets.push({
      label: `Break-even: month ${be}`,
      data: [{ x: be, y: S[NAMES.gcp].cumulative_usd[be] / 1e6 }],
      borderColor: "#f6b34f",
      backgroundColor: "#f6b34f",
      pointRadius: 6,
      pointStyle: "rectRot",
      showLine: false,
    });
  makeChart("cumulative", "chart-cumulative", {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 420 },
      parsing: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "linear",
          min: 0,
          max: d.horizon_months,
          title: { display: true, text: "Months", color: t.text },
          ticks: { color: t.text },
          grid: { color: t.grid },
          border: { display: false },
        },
        y: {
          title: {
            display: true,
            text: "Cumulative cost (USD millions)",
            color: t.text,
          },
          ticks: { color: t.text },
          grid: { color: t.grid },
          border: { display: false },
        },
      },
      plugins: {
        legend: {
          position: "bottom",
          labels: {
            color: t.text,
            boxWidth: 10,
            boxHeight: 10,
            padding: 16,
            usePointStyle: true,
          },
        },
        tooltip: {
          backgroundColor: `rgba(17, 17, 17, 0.8)`,
          titleColor: "white",
          bodyColor: "white",
          padding: 12,
        },
      },
    },
  });
}
function renderItems(d) {
  const n = $("#item-scenario").value,
    S = d.scenarios[n],
    items = Object.entries(S.items),
    total = items.reduce((a, [, v]) => a + v, 0) || 1;
  const rows = items
    .sort((a, b) => b[1] - a[1])
    .map(
      ([k, v]) =>
        `<tr><td>${esc(k)}</td><td class="num">${usd(v)}</td><td><span class="share"><i style="width:${Math.max(3, (v / total) * 100)}%"></i></span><span class="share-label">${((v / total) * 100).toFixed(1)}%</span></td></tr>`,
    )
    .join("");
  $("#items-table").innerHTML =
    `<thead><tr><th>Line item</th><th class="num">USD / month</th><th>Share of scenario</th></tr></thead><tbody>${rows}<tr class="total-row"><td>Total</td><td class="num">${usd(total)}</td><td></td></tr></tbody>`;
  const od = d.onprem_detail;
  $("#onprem-detail").textContent =
    n === NAMES.onp
      ? `On-premises sizing: ${od.servers} servers, ${od.racks} racks, ${od.kw.toFixed(0)} kW, peak bandwidth ${od.peak_gbps.toFixed(0)} Gbps per site, ${od.staff} IT staff.`
      : "";
}
function render(d) {
  renderKpis(d);
  renderScenarioTable(d);
  renderFindings(d);
  renderGroupsChart(d);
  renderBreakeven(d);
  renderCumulativeChart(d);
  const sel = $("#item-scenario"),
    prev = sel.value || NAMES.gcp;
  sel.innerHTML = Object.keys(d.scenarios)
    .map((n) => `<option value="${esc(n)}">${esc(n)}</option>`)
    .join("");
  sel.value = d.scenarios[prev] ? prev : NAMES.gcp;
  renderItems(d);
}

async function loadPrices() {
  if (state.pricesLoaded) return;
  try {
    state.prices = await getJSON("/prices");
    state.pricesLoaded = true;
    $("#prices-note").textContent =
      `Price registry retrieved ${state.prices.retrieved}. ${state.prices.note}`;
    renderPrices();
  } catch (e) {
    $("#prices-note").textContent = "Could not load prices: " + e.message;
  }
}
function renderPrices() {
  const filter = $("#status-filter").value;
  const rows = state.prices.rows
    .filter(
      (r) =>
        !filter ||
        r.status.toUpperCase().startsWith(filter) ||
        (filter === "SOURCED" &&
          r.status.toUpperCase().includes("SOURCED") &&
          !r.status.toUpperCase().startsWith("PARTLY")),
    )
    .map((r) => {
      const cls = r.status.toUpperCase().startsWith("PARTLY")
        ? "PARTLY"
        : r.status.toUpperCase().split(" ")[0];
      return `<tr><td>${esc(r.item)}</td><td>${esc(r.value)}</td><td><span class="badge ${cls}">${esc(r.status)}</span></td><td>${esc(r.source)}</td></tr>`;
    })
    .join("");
  $("#prices-table").innerHTML =
    `<thead><tr><th>Item</th><th>Value</th><th>Evidence</th><th>Source / note</th></tr></thead><tbody>${rows}</tbody>`;
}
function selectTab(name) {
  $$(".tabs [role=tab]").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.tab === name)),
  );
  $$(".tabpanel").forEach((p) => {
    p.hidden = p.id !== "tab-" + name;
  });
  if (name === "prices") loadPrices();
  setTimeout(() => Object.values(state.charts).forEach((c) => c.resize()), 60);
}
function showPage(name) {
  state.currentPage = name;
  if (window.__switchWorkspace) window.__switchWorkspace(name);
  else {
    $$(".app-page").forEach((p) => {
      p.hidden = p.id !== "page-" + name;
    });
    $$(".app-nav-link").forEach((b) =>
      b.classList.toggle("active", b.dataset.page === name),
    );
  }
  if (name === "analysis")
    setTimeout(
      () => Object.values(state.charts).forEach((c) => c.resize()),
      60,
    );
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function enableLocalLiveReload() {
  if (!["localhost", "127.0.0.1"].includes(location.hostname)) return;
  const files = {
      "index.html": "page",
      "app.js": "page",
      "style.css": "style",
    },
    stamps = {};
  async function check() {
    await Promise.all(
      Object.entries(files).map(async ([file, kind]) => {
        try {
          const r = await fetch(file, { method: "HEAD", cache: "no-store" });
          const stamp = r.headers.get("last-modified") || r.headers.get("etag");
          if (!stamp) return;
          if (stamps[file] && stamps[file] !== stamp) {
            if (kind === "style") {
              const link = $("link[href^='style.css']");
              if (link) link.href = `style.css?live=${Date.now()}`;
            } else location.reload();
          }
          stamps[file] = stamp;
        } catch (_) {
          /* development polling must never affect the app */
        }
      }),
    );
  }
  check();
  window.setInterval(check, 1500);
}
async function init() {
  $$(".app-nav-link").forEach((b) =>
    b.addEventListener("click", () => showPage(b.dataset.page)),
  );
  $$(".page-link").forEach((b) =>
    b.addEventListener("click", () => showPage(b.dataset.goto)),
  );
  $(".brand").addEventListener("click", (e) => {
    e.preventDefault();
    showPage("overview");
  });
  $$(".tabs [role=tab]").forEach((b) =>
    b.addEventListener("click", () => selectTab(b.dataset.tab)),
  );
  $("#reset").addEventListener("click", resetForm);
  $("#apply").addEventListener("click", () => {
    clearTimeout(state.timer);
    evaluate();
  });
  $("#item-scenario").addEventListener(
    "change",
    () => state.data && renderItems(state.data),
  );
  $("#status-filter").addEventListener(
    "change",
    () => state.prices && renderPrices(),
  );
  try {
    state.schema = await getJSON("/schema");
    buildForm(state.schema);
    await evaluate();
  } catch (e) {
    showError("Could not load the model from the backend: " + e.message);
    setStatus("Connection error", "err");
  }
  enableLocalLiveReload();
}
if (typeof window !== "undefined") {
  window.addEventListener(
    "chartjs-ready",
    () => state.data && render(state.data),
  );
  window.addEventListener(
    "themechange",
    () => state.data && render(state.data),
  );
  window.addEventListener("DOMContentLoaded", init);
}
