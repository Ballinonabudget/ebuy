const STATUS_LABELS = {
  ready: "READY",
  review: "REVIEW",
  photos: "NEEDS PIX",
  draft: "DRAFTING",
  pass: "PASS",
  listed: "LISTED",
};

const CATEGORY_COLOR = {
  Sneakers: ["#7c5a3a", "#3a2a1c"],
  TCG: ["#d97757", "#3a1f15"],
  Vintage: ["#5d6b4e", "#1f2a1a"],
  Tech: ["#3a5d7c", "#10202e"],
  Apparel: ["#7a6a55", "#2a241c"],
  Toys: ["#a8533e", "#3a1b14"],
  Kitchen: ["#5a7a7d", "#1d2a2b"],
  Bags: ["#7a4d6a", "#28172a"],
  Games: ["#4d6b8a", "#161f2e"],
  Outdoor: ["#506b48", "#1a2317"],
  General: ["#556070", "#1c2430"],
};

const state = {
  items: [],
  counts: {},
  activeQueue: "inbox",
  statusFilter: "all",
  sortBy: "roi",
  searchQuery: "",
  focusedId: null,
  openId: null,
  fullItems: new Map(),
  watcher: { scanning: false, lastSeen: 0 },
};

const queues = [
  ["inbox", "Inbox"],
  ["ready", "Ready"],
  ["draft", "Drafting"],
  ["photos", "Need pix"],
  ["listed", "Listed"],
  ["pass", "Pass"],
];

const filters = [
  ["all", "All"],
  ["ready", "Ready"],
  ["draft", "Drafting"],
  ["photos", "Need pix"],
  ["review", "Review"],
  ["pass", "Pass"],
];

const sorts = [
  ["roi", "ROI ↓"],
  ["net", "Net $ ↓"],
  ["conf", "Confidence ↓"],
  ["age", "Newest first"],
];

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${Math.round(Number(value))}%`;
}

function roiPct(item) {
  if (item.roiPct !== null && item.roiPct !== undefined) return Number(item.roiPct);
  if (!item.ask || !item.cogs) return null;
  return ((item.ask * 0.87 - item.cogs) / item.cogs) * 100;
}

function seedFor(item) {
  return String(item.id || "0").split("").reduce((sum, char) => sum + char.charCodeAt(0), 0);
}

function photoStyle(cat, seed = 0) {
  const [a, b] = CATEGORY_COLOR[cat] || CATEGORY_COLOR.General;
  const angle = 110 + ((seed * 47) % 80);
  return `radial-gradient(circle at ${20 + ((seed * 13) % 60)}% ${30 + ((seed * 17) % 50)}%, ${a} 0%, ${b} 60%, ${b} 100%), linear-gradient(${angle}deg, ${a}, ${b})`;
}

function photoBlock(item, className, label, index = 0) {
  const url = item.photoUrls?.[index];
  const fallback = escapeHtml((label || item.cat || "item").slice(0, 12));
  const escapedUrl = escapeHtml(url || "");
  if (url) {
    return `<div class="ph ${className}" data-photo-url="${escapedUrl}" data-photo-index="${index}"><img src="${escapedUrl}" alt="${escapeHtml(item.brand)} ${escapeHtml(item.model)} photo ${index + 1}" loading="lazy"><span class="sr-only">${fallback}</span></div>`;
  }
  return `<div class="ph ${className}" data-photo-index="${index}" style="background:${photoStyle(item.cat, seedFor(item) + index)}"><span class="photo-label">${fallback}</span></div>`;
}

function sparkSvg(item, hot = false, width = 60, height = 18) {
  const seed = seedFor(item);
  let v = 0.4 + (seed % 5) * 0.05;
  const points = [];
  for (let i = 0; i < 12; i += 1) {
    v += Math.sin(i + seed) * 0.08 + 0.025;
    v = Math.max(0.1, Math.min(0.95, v));
    const x = (i / 11) * (width - 2) + 1;
    const y = height - 2 - v * (height - 4);
    points.push(`${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`);
  }
  return `<svg width="${width}" height="${height}" class="spark" aria-hidden="true"><path d="${points.join(" ")}" fill="none" stroke="${hot ? "var(--amber)" : "var(--ink-3)"}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"></path></svg>`;
}

function compsChart(item, width = 520, height = 150) {
  const series = item.market?.sold?.series?.length
    ? item.market.sold.series.map((point) => Number(point.price || 0)).filter(Boolean)
    : [item.market?.sold?.rangeLow, item.market?.sold?.median, item.market?.sold?.average, item.ask, item.market?.sold?.rangeHigh].map(Number).filter(Boolean);
  const values = series.length >= 2 ? series : [0, Number(item.ask || 1)];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(1, max - min);
  const padL = 36;
  const padR = 10;
  const padT = 14;
  const padB = 22;
  const xs = (i) => padL + (i / Math.max(1, values.length - 1)) * (width - padL - padR);
  const ys = (val) => padT + (1 - (val - min) / spread) * (height - padT - padB);
  const line = values.map((val, i) => `${i === 0 ? "M" : "L"} ${xs(i)} ${ys(val)}`).join(" ");
  const area = `${line} L ${xs(values.length - 1)} ${height - padB} L ${xs(0)} ${height - padB} Z`;
  const median = item.market?.sold?.median || values[Math.floor(values.length / 2)] || 0;
  const last = values[values.length - 1] || 0;
  const gradId = `price-grad-${String(item.id || "x").replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const tone = valueTone(item.net, roiPct(item));
  return `
    <svg width="100%" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="display:block;max-height:${height}px">
      <defs>
        <linearGradient id="area-grad-live" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--moss)" stop-opacity="0.24"></stop>
          <stop offset="50%" stop-color="var(--amber)" stop-opacity="0.14"></stop>
          <stop offset="100%" stop-color="var(--rose)" stop-opacity="0.06"></stop>
        </linearGradient>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--moss)"></stop>
          <stop offset="48%" stop-color="var(--amber)"></stop>
          <stop offset="100%" stop-color="var(--rose)"></stop>
        </linearGradient>
      </defs>
      ${[0.25, 0.5, 0.75].map((t) => `<line x1="${padL}" y1="${padT + (1 - t) * (height - padT - padB)}" x2="${width - padR}" y2="${padT + (1 - t) * (height - padT - padB)}" stroke="var(--line-1)" stroke-width="1" stroke-dasharray="2 4"></line>`).join("")}
      <text x="${padL - 6}" y="${padT + 4}" font-family="var(--font-mono)" font-size="9" fill="var(--ink-3)" text-anchor="end">${money(max)}</text>
      <text x="${padL - 6}" y="${height - padB}" font-family="var(--font-mono)" font-size="9" fill="var(--ink-3)" text-anchor="end">${money(min)}</text>
      ${["30d", "20d", "10d", "now"].map((label, i) => `<text x="${padL + (i / 3) * (width - padL - padR)}" y="${height - 4}" font-family="var(--font-mono)" font-size="9" fill="var(--ink-3)" text-anchor="middle">${label}</text>`).join("")}
      <line x1="${padL}" y1="${ys(median)}" x2="${width - padR}" y2="${ys(median)}" stroke="var(--ink-4)" stroke-width="1" stroke-dasharray="3 5"></line>
      <text x="${width - padR - 4}" y="${ys(median) - 4}" font-family="var(--font-mono)" font-size="9" fill="var(--ink-3)" text-anchor="end">median ${money(median)}</text>
      <path d="${area}" fill="url(#area-grad-live)"></path>
      <path d="${line}" fill="none" stroke="url(#${gradId})" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"></path>
      <circle cx="${xs(values.length - 1)}" cy="${ys(last)}" r="6" fill="var(--${tone === "good" ? "moss" : tone === "bad" ? "rose" : "amber"})" opacity="0.25"></circle>
      <circle cx="${xs(values.length - 1)}" cy="${ys(last)}" r="3" fill="var(--${tone === "good" ? "moss" : tone === "bad" ? "rose" : "amber"})"></circle>
      <text x="${xs(values.length - 1) - 8}" y="${ys(last) - 8}" font-family="var(--font-mono)" font-size="10" fill="var(--${tone === "good" ? "moss" : tone === "bad" ? "rose" : "amber"})" text-anchor="end" font-weight="600">${money(last)}</text>
    </svg>
  `;
}

function valueTone(net, roi) {
  if (Number(net || 0) < 0 || Number(roi || 0) < 0) return "bad";
  if (Number(roi || 0) >= 50 || Number(net || 0) >= 25) return "good";
  return "warn";
}

function gauge(value = 0, size = 150) {
  const r = size * 0.42;
  const cx = size / 2;
  const cy = size * 0.62;
  const clamped = Math.max(0, Math.min(100, Number(value || 0)));
  const ang = (v) => Math.PI * (1 - v / 100);
  const arcPt = (v) => [cx + r * Math.cos(ang(v)), cy - r * Math.sin(ang(v))];
  const [sx, sy] = arcPt(0);
  const [ex, ey] = arcPt(100);
  const [vx, vy] = arcPt(clamped);
  return `
    <svg width="${size}" height="${size * 0.78}" style="display:block">
      <path d="M ${sx} ${sy} A ${r} ${r} 0 0 1 ${ex} ${ey}" fill="none" stroke="var(--line-2)" stroke-width="6" stroke-linecap="round"></path>
      <path d="M ${sx} ${sy} A ${r} ${r} 0 ${clamped > 50 ? 1 : 0} 1 ${vx} ${vy}" fill="none" stroke="var(--amber)" stroke-width="6" stroke-linecap="round"></path>
      ${[0, 25, 50, 75, 100].map((tick) => {
        const a = ang(tick);
        const x1 = cx + (r + 6) * Math.cos(a);
        const y1 = cy - (r + 6) * Math.sin(a);
        const x2 = cx + (r + 11) * Math.cos(a);
        const y2 = cy - (r + 11) * Math.sin(a);
        return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="var(--ink-4)" stroke-width="1"></line>`;
      }).join("")}
      <text x="${cx}" y="${cy - 4}" font-family="var(--font-mono)" font-size="26" font-weight="600" text-anchor="middle" fill="var(--ink-1)">${Math.round(clamped)}<tspan font-size="14" fill="var(--ink-3)">%</tspan></text>
      <text x="${cx}" y="${cy + 14}" font-family="var(--font-mono)" font-size="9" letter-spacing="0.12em" text-anchor="middle" fill="var(--ink-3)">SELL-THRU 30D</text>
    </svg>
  `;
}

function roiBar(item) {
  if (!item.ask) return `<div class="mono" style="font-size:11px;color:var(--ink-3)">No ask price yet.</div>`;
  const ask = Number(item.ask);
  const cogs = Number(item.cogs || 0);
  const feeAmt = ask * (item.financial?.feesPct || 0.136);
  const net = ask - cogs - feeAmt;
  const cogsPct = Math.max(0, Math.min(100, (cogs / ask) * 100));
  const feePct = Math.max(0, Math.min(100, (feeAmt / ask) * 100));
  const netPct = Math.max(0, 100 - cogsPct - feePct);
  return `
    <div style="display:flex;flex-direction:column;gap:8px">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div class="mono" style="font-size:10px;color:var(--ink-3);letter-spacing:0.1em;text-transform:uppercase">ROI · ${money(cogs)} → ${money(ask)}</div>
        <div class="mono" style="font-size:12px;color:${net >= 0 ? "var(--moss)" : "var(--rust)"};font-weight:600">NET ${money(net)} · ${cogs ? Math.round((net / cogs) * 100) : 0}%</div>
      </div>
      <div style="display:flex;height:14px;border-radius:4px;overflow:hidden;border:1px solid var(--line-2)">
        <div style="width:${cogsPct}%;background:var(--rust);display:flex;align-items:center;justify-content:center;font-family:var(--font-mono);font-size:9px;color:#fff">${cogsPct > 14 ? `COGS ${money(cogs)}` : ""}</div>
        <div style="width:${feePct}%;background:var(--ink-4);display:flex;align-items:center;justify-content:center;font-family:var(--font-mono);font-size:9px;color:var(--ink-1)">${feePct > 8 ? "FEES" : ""}</div>
        <div style="width:${netPct}%;background:${net >= 0 ? "var(--moss)" : "var(--rust)"};display:flex;align-items:center;justify-content:center;font-family:var(--font-mono);font-size:9px;color:#0c1118;font-weight:600">NET ${money(net)}</div>
      </div>
    </div>
  `;
}

function sortedVisibleItems() {
  let items = state.items;
  if (state.activeQueue !== "inbox") {
    items = items.filter((item) => item.status === state.activeQueue);
  } else if (state.statusFilter !== "all") {
    items = items.filter((item) => item.status === state.statusFilter);
  }
  const query = state.searchQuery.trim().toLowerCase();
  if (query) {
    items = items.filter((item) => {
      const haystack = [
        item.brand,
        item.model,
        item.cat,
        item.status,
        item.condition,
        item.folderName,
        item.styleCode,
        item.sourcePath,
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }
  const copy = [...items];
  if (state.sortBy === "roi") copy.sort((a, b) => (roiPct(b) ?? -999) - (roiPct(a) ?? -999));
  if (state.sortBy === "net") copy.sort((a, b) => Number(b.net ?? -999) - Number(a.net ?? -999));
  if (state.sortBy === "conf") copy.sort((a, b) => Number(b.conf ?? 0) - Number(a.conf ?? 0));
  return copy;
}

function renderShell() {
  document.body.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">E</div>
          <div>
            <div class="brand-name">Ebuy</div>
            <div class="brand-ver">v0.4 · LOCAL</div>
          </div>
        </div>
        <div>
          <div class="section-label">Queues</div>
          <div id="queue-list" style="display:flex;flex-direction:column;gap:1px"></div>
        </div>
        <div>
          <div class="section-label"><span>Watching</span><span class="mono" style="font-size:9px;color:var(--ink-3)">•••</span></div>
          <div class="watcher">
            <div class="watcher-path" id="watcher-path">~/eBay_Drop</div>
            <div class="watcher-status"><span class="live-dot"></span><span id="watcher-status">idle · 0 new</span></div>
          </div>
        </div>
        <hr class="div">
        <div class="kpi-card">
          <div class="kpi-sub">Net · current queue</div>
          <div class="kpi-value" id="kpi-net">$0</div>
          <div class="kpi-bars">${[3, 4, 5, 3, 7, 6, 8].map((v, i) => `<b style="height:${v * 10}%" class="${i === 6 ? "h" : ""}"></b>`).join("")}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-sub">Listings · local DB</div>
          <div class="kpi-value" id="kpi-items">0</div>
          <div class="mono" style="font-size:10px;color:var(--moss)">SQLite · live bindings</div>
        </div>
        <div style="margin-top:auto">
          <hr class="div">
          <div class="mono" style="font-size:10px;color:var(--ink-3);line-height:1.6">
            eBay engine · <span style="color:var(--moss)">ok</span><br>
            local API · <span style="color:var(--moss)">ok</span><br>
            <a href="/" style="color:var(--ink-2);text-decoration:none">legacy dashboard</a>
          </div>
        </div>
      </aside>
      <main class="main">
        <div class="topbar">
          <div class="topbar-title">
            <h1 class="topbar-h">Inbox</h1>
            <div class="topbar-sub" id="topbar-sub">watching · 0 active</div>
          </div>
          <div class="tape" id="tape"></div>
          <div class="topbar-actions">
            <button class="btn ghost sm" id="search-btn" title="Search">⌘K</button>
            <button class="btn sm" id="scan-btn">+ Add photos</button>
          </div>
        </div>
        <div class="listview">
          <div class="list-header">
            <div class="list-headcount"><span class="n" id="list-count">0</span><span class="l" id="list-label">items · inbox</span></div>
            <div class="list-controls">
              <div class="chips" id="filter-chips"></div>
              <div class="sort-select" id="sort-select"><span style="color:var(--ink-3)">SORT:</span><span id="sort-label">ROI ↓</span></div>
              <button class="btn primary sm" id="approve-ready" style="display:none">APPROVE READY · 0</button>
            </div>
          </div>
          <div class="tbl">
            <table>
              <thead>
                <tr>
                  <th style="width:60px"></th>
                  <th>Item</th>
                  <th style="width:110px">Status</th>
                  <th class="r" style="width:80px">Comps</th>
                  <th class="r" style="width:100px">Sell-thru</th>
                  <th class="r" style="width:120px">COGS → Ask</th>
                  <th class="r" style="width:90px">Net</th>
                  <th class="r" style="width:90px">ROI</th>
                  <th style="width:80px">Conf</th>
                  <th style="width:70px">Trend</th>
                  <th style="width:60px">Age</th>
                  <th style="width:80px"></th>
                </tr>
              </thead>
              <tbody id="item-rows"></tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
    <div class="toasts" id="toasts"></div>
  `;
  $("#scan-btn").addEventListener("click", scanDropZone);
  $("#search-btn").addEventListener("click", openCommandPalette);
  $("#sort-select").addEventListener("click", () => {
    const idx = sorts.findIndex(([key]) => key === state.sortBy);
    state.sortBy = sorts[(idx + 1) % sorts.length][0];
    render();
  });
  $("#approve-ready").addEventListener("click", approveReady);
}

function render() {
  const c = state.counts;
  $("#queue-list").innerHTML = queues.map(([key, label]) => `
    <div class="nav-row ${state.activeQueue === key ? "active" : ""}" data-queue="${key}">
      <span class="dot"></span>
      <span class="nav-name">${label}</span>
      <span class="nav-count">${c[key] ?? 0}</span>
    </div>
  `).join("");
  $$(".nav-row").forEach((row) => row.addEventListener("click", () => {
    state.activeQueue = row.dataset.queue;
    render();
  }));

  $("#tape").innerHTML = [
    ["Ready", c.ready ?? 0, "amber", ""],
    ["Drafting", c.draft ?? 0, "teal", ""],
    ["Need pix", c.photos ?? 0, "", "optional"],
    ["Pot. Net", money(c.potNet ?? 0), "", ""],
    ["Listed", c.listed ?? 0, "moss", ""],
    ["Approval Rate", c.inbox ? `${Math.round(((c.ready ?? 0) / c.inbox) * 100)}%` : "0%", "", "optional-2"],
  ].map(([label, value, color, optional]) => `
    <div class="tape-cell ${optional}">
      <div class="l">${label}</div>
      <div class="v ${color}">${value}</div>
    </div>
  `).join("");

  $("#filter-chips").innerHTML = state.activeQueue === "inbox" ? filters.map(([key, label]) => `
    <span class="chip ${state.statusFilter === key ? "active" : ""}" data-filter="${key}">
      ${label}<span class="count">${key === "all" ? state.items.length : state.items.filter((item) => item.status === key).length}</span>
    </span>
  `).join("") : "";
  $$(".chip").forEach((chip) => chip.addEventListener("click", () => {
    state.statusFilter = chip.dataset.filter;
    render();
  }));

  const visible = sortedVisibleItems();
  $("#list-count").textContent = visible.length;
  $("#list-label").textContent = `items · ${state.searchQuery ? `search: ${state.searchQuery}` : state.activeQueue === "inbox" ? "inbox" : STATUS_LABELS[state.activeQueue] || state.activeQueue}`;
  $("#sort-label").textContent = sorts.find(([key]) => key === state.sortBy)?.[1] || "ROI ↓";
  $("#topbar-sub").textContent = state.watcher.scanning ? "scanning folder · new item arriving" : `watching · ${c.inbox ?? 0} active`;
  $("#watcher-status").textContent = state.watcher.scanning ? "scanning..." : `idle · ${state.watcher.lastSeen} new`;
  $("#kpi-net").textContent = money(c.potNet ?? 0);
  $("#kpi-items").textContent = c.inbox ?? 0;

  const approveButton = $("#approve-ready");
  if ((c.ready ?? 0) > 0) {
    approveButton.style.display = "";
    approveButton.textContent = `APPROVE READY · ${state.items.filter((item) => item.status === "ready").length}`;
  } else {
    approveButton.style.display = "none";
  }

  $("#item-rows").innerHTML = visible.length ? visible.map((item) => {
    const roi = roiPct(item);
    const focused = state.focusedId === item.id ? "focused" : "";
    return `
      <tr data-id="${escapeHtml(item.id)}" class="${focused}">
        <td>${photoBlock(item, "ph-thumb", item.cat)}</td>
        <td>
          <div class="item-name-stack">
            <div class="item-name">${escapeHtml(item.model)}</div>
            <div class="item-meta">${escapeHtml(item.brand).toUpperCase()} · ${escapeHtml(item.cat).toUpperCase()}</div>
          </div>
        </td>
        <td><span class="pill ${escapeHtml(item.status)}"><i class="d"></i>${STATUS_LABELS[item.status] || item.status}</span></td>
        <td class="r">${item.comps ?? "—"}</td>
        <td class="r">${pct(item.sellThru)}</td>
        <td class="r">${money(item.cogs)} → ${money(item.ask)}</td>
        <td class="r">${money(item.net)}</td>
        <td class="r"><span class="roi-val ${roi != null && roi > 100 ? "hi" : roi != null && roi < 50 ? "lo" : ""}">${roi != null ? `${Math.round(roi)}%` : "—"}</span></td>
        <td>
          <div class="conf-bar ${item.conf < 0.6 ? "lo" : ""}"><i style="width:${Math.round((item.conf || 0) * 100)}%"></i></div>
          <span class="mono" style="font-size:10px;color:var(--ink-3);margin-left:6px">${Math.round((item.conf || 0) * 100)}</span>
        </td>
        <td>${sparkSvg(item, item.status === "ready")}</td>
        <td style="color:var(--ink-3)">${escapeHtml(item.age)}</td>
        <td class="r"><span class="mono" style="font-size:11px;color:var(--ink-3)">→</span></td>
      </tr>
    `;
  }).join("") : `<tr><td colspan="12" style="padding:40px"><div class="empty"><div>no items match</div><div class="mono" style="font-size:10px">try a different filter or queue</div></div></td></tr>`;

  $$("#item-rows tr[data-id]").forEach((row) => {
    row.addEventListener("mouseenter", () => {
      state.focusedId = row.dataset.id;
      $$("#item-rows tr").forEach((tr) => tr.classList.toggle("focused", tr.dataset.id === row.dataset.id));
    });
    row.addEventListener("click", () => openOverlay(row.dataset.id));
  });
}

async function loadItems() {
  const response = await fetch("/api/items");
  if (!response.ok) throw new Error("Failed to load items");
  const data = await response.json();
  state.items = data.items || [];
  state.counts = data.counts || {};
  state.watcher.lastSeen = state.items.length;
  if (data.dropZone) $("#watcher-path").textContent = data.dropZone.replace(/^\/Users\/[^/]+/, "~");
  render();
}

function replaceItemsFromApi(data) {
  state.items = data.items || [];
  if (data.counts) {
    state.counts = data.counts;
  } else {
    state.counts = {
      inbox: state.items.length,
      ready: state.items.filter((item) => item.status === "ready").length,
      draft: state.items.filter((item) => item.status === "draft").length,
      photos: state.items.filter((item) => item.status === "photos").length,
      review: state.items.filter((item) => item.status === "review").length,
      pass: state.items.filter((item) => item.status === "pass").length,
      listed: state.items.filter((item) => item.status === "listed").length,
      potNet: state.items.reduce((sum, item) => item.status !== "pass" ? sum + Number(item.net || 0) : sum, 0),
    };
  }
  state.watcher.lastSeen = state.items.length;
  state.fullItems.clear();
  render();
}

async function scanDropZone() {
  state.watcher.scanning = true;
  render();
  try {
    const data = await postJson("/api/scan", {});
    replaceItemsFromApi(data);
    toast(`Scan complete · ${data.scan?.imported || 0} imported · ${data.scan?.skipped || 0} skipped`, "amber");
  } catch (error) {
    toast(`Scan failed · ${error.message}`, "teal");
  } finally {
    state.watcher.scanning = false;
    render();
  }
}

async function approveReady() {
  const ids = state.items.filter((item) => item.status === "ready").map((item) => item.id);
  if (!ids.length) return;
  const data = await postJson("/api/items/bulk-status", { ids, status: "listed" });
  replaceItemsFromApi(data);
  toast(`Listed ${data.updated || 0} ready item(s)`, "moss");
}

async function fetchFullItem(id) {
  if (state.fullItems.has(id)) return state.fullItems.get(id);
  const response = await fetch(`/api/items/${id}`);
  if (!response.ok) throw new Error("Failed to load item");
  const data = await response.json();
  state.fullItems.set(id, data.item);
  return data.item;
}

function toast(message, kind = "moss") {
  const id = `toast-${Date.now()}`;
  $("#toasts").insertAdjacentHTML("beforeend", `<div class="toast ${kind}" id="${id}"><span style="width:8px;height:8px;border-radius:50%;background:var(--${kind === "amber" ? "amber" : kind === "teal" ? "teal" : "moss"})"></span><span>${escapeHtml(message)}</span></div>`);
  setTimeout(() => {
    const node = $(`#${id}`);
    if (!node) return;
    node.classList.add("fade");
    setTimeout(() => node.remove(), 240);
  }, 2400);
}

function openCommandPalette() {
  $(".command-overlay")?.remove();
  document.body.insertAdjacentHTML("beforeend", `
    <div class="overlay command-overlay">
      <div class="review" style="max-width:640px;max-height:360px;margin:9vh auto;flex:none;border:1px solid var(--line-2);border-radius:var(--radius-4)">
        <div class="review-top">
          <div>
            <div class="crumb"><span>COMMAND</span><span>·</span><span>Filter live inventory</span></div>
            <h1 class="review-title">Search Ebuy</h1>
            <div class="review-sub">brand, model, category, status, condition, folder, or style code</div>
          </div>
          <div class="review-actions"><button class="btn ghost icon" data-close title="Close">✕</button></div>
        </div>
        <div style="padding:18px 24px;display:flex;flex-direction:column;gap:12px">
          <input class="draft-input" id="command-search" value="${escapeHtml(state.searchQuery)}" placeholder="Search items..." autofocus>
          <div class="chips">
            ${["ready", "review", "photos", "draft", "pass", "listed"].map((key) => `<span class="chip" data-command-filter="${key}">${STATUS_LABELS[key]}</span>`).join("")}
            <span class="chip" data-clear-search>Clear search</span>
          </div>
          <div class="hint">Press Enter to apply. Esc closes.</div>
        </div>
      </div>
    </div>
  `);
  const overlay = $(".command-overlay");
  const input = $("#command-search");
  const close = () => overlay.remove();
  $$(".command-overlay [data-close]").forEach((node) => node.addEventListener("click", close));
  overlay.addEventListener("click", (event) => {
    if (event.target.classList.contains("command-overlay")) close();
  });
  input.focus();
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      state.searchQuery = input.value.trim();
      close();
      render();
    }
    if (event.key === "Escape") close();
  });
  $$(".command-overlay [data-command-filter]").forEach((chip) => chip.addEventListener("click", () => {
    state.activeQueue = chip.dataset.commandFilter;
    state.searchQuery = "";
    close();
    render();
  }));
  $(".command-overlay [data-clear-search]").addEventListener("click", () => {
    state.searchQuery = "";
    input.value = "";
    close();
    render();
  });
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error("Save failed");
  return response.json();
}

function updateSummary(item) {
  state.fullItems.set(item.id, item);
  const index = state.items.findIndex((candidate) => candidate.id === item.id);
  if (index >= 0) {
    state.items[index] = {
      id: item.id,
      engineStatus: item.engineStatus,
      status: item.status,
      queue: item.queue,
      folderName: item.folderName,
      sourcePath: item.sourcePath,
      ingestedAt: item.ingestedAt,
      updatedAt: item.updatedAt,
      age: item.age,
      brand: item.brand,
      model: item.model,
      styleCode: item.styleCode,
      cat: item.cat,
      condition: item.condition,
      size: item.size,
      color: item.color,
      conf: item.conf,
      photos: item.photos,
      photoUrls: item.photoUrls,
      defects: item.defects,
      cogs: item.cogs,
      ask: item.ask,
      net: item.net,
      roiPct: item.roiPct,
      sellThru: item.sellThru,
      comps: item.comps,
      decision: item.decision,
      rationale: item.rationale,
    };
  }
}

function overlayHtml(item, index, total) {
  const roi = roiPct(item);
  const isReady = item.financial?.verdict === "approve" || item.status === "ready";
  const tone = valueTone(item.net, roi);
  const verdict = item.financial?.verdict || (tone === "bad" ? "pass" : tone === "good" ? "approve" : "review");
  const verdictLabel = verdict === "pass" ? "Pass" : verdict === "approve" ? "Approve" : verdict;
  const verdictColor = verdict === "approve" ? "moss" : verdict === "pass" ? "rose" : "amber";
  const sold = item.market?.sold || {};
  const activeCount = item.market?.competition?.activeCount ?? 0;
  const listingRows = item.market?.competition?.listings || [];
  return `
    <div class="overlay">
      <div class="review">
        <div class="review-top">
          <div>
            <div class="crumb">
              <a data-close>← Inbox</a>
              <span>·</span>
              <span>Item ${index + 1} of ${total}</span>
              <span style="color:var(--ink-4);margin-left:auto">J/K nav · A approve · Esc close</span>
            </div>
            <h1 class="review-title">${escapeHtml(item.model)}</h1>
            <div class="review-sub">id ${escapeHtml(item.id)} · ${escapeHtml(item.brand)} · ${escapeHtml(item.cat)} · ingested ${escapeHtml(item.age)} ago from <span style="color:var(--ink-2)">${escapeHtml(item.sourcePath || "/watch/uploads")}</span></div>
          </div>
          <div class="review-actions">
            <span class="pill ${escapeHtml(item.status)}"><i class="d"></i>${STATUS_LABELS[item.status] || item.status}</span>
            <button class="btn sm" data-prev title="Previous">←</button>
            <button class="btn sm" data-next title="Next">→</button>
            <button class="btn ghost icon" data-close title="Close (Esc)">✕</button>
          </div>
        </div>
        <div class="review-body">
          <div class="review-left">
            <div class="carousel" data-active-photo="0">
              <div id="carousel-hero">${photoBlock(item, "carousel-hero", item.cat, 0)}</div>
              <div class="carousel-actions">
                <button class="btn sm" data-open-photo>View larger</button>
                <button class="btn sm" data-set-cover>Make hero shot</button>
              </div>
              <div class="carousel-strip">
                ${Array.from({ length: Math.max(1, item.photos || item.photoUrls?.length || 1) }).slice(0, 8).map((_, i) => `<div class="carousel-thumb-wrap" data-photo-index="${i}">${photoBlock(item, `carousel-thumb ${i === 0 ? "active" : ""}`, item.cat, i)}</div>`).join("")}
              </div>
            </div>
            <div class="ai-log">
              <div class="ai-log-title">CV Agent · ${Math.round((item.conf || 0) * 100)}% conf</div>
              <ul>${(item.ai?.agentLog || []).map((entry) => `<li>${escapeHtml(entry.line)}</li>`).join("")}</ul>
            </div>
            <div class="attr-grid">
              <div class="attr-grid-title">AI · Detected Attributes</div>
              ${(item.ai?.attributes || []).map((attr) => `
                <div class="attr-row">
                  <span class="k">${escapeHtml(attr.key)}</span>
                  <span class="v">${escapeHtml(attr.value)}</span>
                  <span class="c ${attr.confidence > 0.9 ? "hi" : attr.confidence > 0.7 ? "md" : "lo"}">${Math.round(attr.confidence * 100)}%</span>
                </div>
              `).join("")}
            </div>
          </div>
          <div class="review-right">
            <div class="reco" style="background:linear-gradient(135deg,var(--${verdictColor === "moss" ? "moss-tint" : verdictColor === "rose" ? "rust-tint" : "amber-tint"}),transparent);border-color:var(--${verdictColor === "moss" ? "moss" : verdictColor === "rose" ? "rose" : "amber"})">
              <div class="reco-badge" style="color:var(--${verdictColor});border-color:var(--${verdictColor})">${escapeHtml(verdictLabel)}</div>
              <div class="reco-body">
                <div class="reco-headline">${escapeHtml(item.financial?.headline || `${money(item.net)} · ${pct(roi)} ROI`)}</div>
                <div class="reco-reason">${escapeHtml(item.financial?.reason || item.rationale || "Review before listing")}</div>
              </div>
            </div>
            <div>
              <div class="section-h">
                <div><span class="section-num">01</span><span class="section-title">Market research</span></div>
                <span class="hint">eBay finding API · ${escapeHtml(item.market?.fetchedAt || "not fetched")}</span>
              </div>
              <div class="stat-grid">
                <div class="stat"><div class="l">30d Sold Median</div><div class="v ${tone === "good" ? "tone-good" : tone === "bad" ? "tone-bad" : "tone-warn"}">${money(sold.median || item.ask)}</div><div class="d ${tone === "bad" ? "dn" : "up"}">range ${money(sold.rangeLow)}–${money(sold.rangeHigh)}</div></div>
                <div class="stat"><div class="l">Sell-thru</div><div class="v ${Number(item.sellThru || 0) >= 50 ? "tone-good" : Number(item.sellThru || 0) ? "tone-warn" : ""}">${pct(item.sellThru)}</div><div class="d">${item.comps ?? "—"} comps · ${activeCount} active</div></div>
                <div class="stat"><div class="l">Net after fees</div><div class="v ${tone === "good" ? "tone-good" : tone === "bad" ? "tone-bad" : "tone-warn"}">${money(item.net)}</div><div class="d">eBay ${Math.round((item.financial?.feesPct || 0.136) * 100)}% · local defaults</div></div>
              </div>
              <div class="chart-card" style="margin-top:12px">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                  <div class="mono" style="font-size:10px;color:var(--ink-3);letter-spacing:0.1em;text-transform:uppercase">30-Day Sold Comps</div>
                  <div class="mono" style="font-size:11px;color:var(--ink-3)">n=${item.comps ?? "—"}</div>
                </div>
                ${compsChart(item)}
              </div>
              <div style="display:grid;grid-template-columns:1fr 1.4fr;gap:12px;margin-top:12px;align-items:stretch">
                <div class="chart-card" style="display:flex;flex-direction:column;align-items:center;justify-content:center">${gauge(item.sellThru || 0)}</div>
                <div class="chart-card" style="display:flex;flex-direction:column;justify-content:center;gap:14px">
                  ${roiBar(item)}
                  <hr class="div">
                  <div class="mono" style="font-size:10px;color:var(--ink-3);letter-spacing:0.1em;text-transform:uppercase">Recommendation logic</div>
                  <div class="mono" style="font-size:11px;color:var(--ink-2);line-height:1.55">
                    ${(item.financial?.checks || []).map((check) => `${escapeHtml(check.label)} ${check.pass ? "✓" : "✗"} ${escapeHtml(check.rule)}`).join("<br>")}
                  </div>
                </div>
              </div>
              <div class="chart-card" style="margin-top:12px">
                <div class="mono" style="font-size:10px;color:var(--ink-3);letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">Active Competition · ${activeCount} listings live now</div>
                <table class="comps-table">
                  <thead><tr><th>Active Comp</th><th>Cond.</th><th class="r">Asking</th><th class="r">Watch</th></tr></thead>
                  <tbody>${listingRows.length ? listingRows.map((row) => `<tr><td style="max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${row.url ? `<a href="${escapeHtml(row.url)}" target="_blank" rel="noreferrer" style="color:inherit;text-decoration:none">${escapeHtml(row.title)}</a>` : escapeHtml(row.title)}</td><td>${escapeHtml(row.condition)}</td><td class="r">${money(row.price)}</td><td class="r" style="color:var(--ink-3)">${row.watchers ?? "—"}</td></tr>`).join("") : `<tr><td colspan="4" style="padding:14px;color:var(--ink-3)">No per-listing competition rows stored yet. Add rows through POST /api/items/${escapeHtml(item.id)}/competition or extend the scraper to save active listings.</td></tr>`}</tbody>
                </table>
              </div>
            </div>
            <div>
              <div class="section-h"><div><span class="section-num">02</span><span class="section-title">Listing draft</span></div><span class="hint">auto-drafted · editable</span></div>
              <form id="draft-form" style="display:flex;flex-direction:column;gap:14px">
                <div class="draft-field"><div class="lbl"><span>SEO Title · ${(item.draft?.seoTitle || "").length}/80</span><span class="hint">save</span></div><input class="draft-input" name="title" maxlength="80" value="${escapeHtml(item.draft?.seoTitle || "")}"></div>
                <div class="draft-field"><div class="lbl"><span>HTML Description</span><span class="hint">preview · edit</span></div><textarea class="draft-textarea" name="description">${escapeHtml(item.draft?.htmlDescription || "")}</textarea></div>
                <div class="field-row">
                  <div class="draft-field"><div class="lbl"><span>Category</span></div><input class="draft-input" name="category" value="${escapeHtml(item.draft?.category || item.cat)}"></div>
                  <div class="draft-field"><div class="lbl"><span>Shipping</span></div><input class="draft-input" name="shipping_service" value="${escapeHtml(item.draft?.shipping?.service || "calculated_buyer_paid")}"></div>
                  <div class="draft-field"><div class="lbl"><span>Start price</span></div><input class="draft-input" name="start_price" value="${escapeHtml(item.draft?.format?.startPrice || item.ask || "")}" inputmode="decimal"></div>
                </div>
              </form>
            </div>
            <div style="height:20px"></div>
          </div>
        </div>
        <div class="cta-bar">
          <div class="cta-left">
            <span class="pill ${escapeHtml(item.status)}" style="font-size:11px;padding:5px 9px"><i class="d"></i>${STATUS_LABELS[item.status] || item.status}</span>
            <div class="cta-stat"><div class="l">Net</div><div class="v ${Number(item.net || 0) >= 0 ? "hi" : ""}">${money(item.net)}</div></div>
            <div class="cta-stat"><div class="l">ROI</div><div class="v">${pct(roi)}</div></div>
            <div class="cta-stat"><div class="l">Conf</div><div class="v">${pct((item.conf || 0) * 100)}</div></div>
            <div class="cta-stat"><div class="l">Sell-thru</div><div class="v">${pct(item.sellThru)}</div></div>
          </div>
          <div class="cta-actions">
            <button class="btn danger sm" data-status="archived">Reject<span class="kbd">X</span></button>
            <button class="btn sm" data-status="needs_info">Need pix</button>
            <button class="btn sm" data-research>More research</button>
            <button class="btn sm" data-save-draft>Save draft</button>
            <button class="btn primary" data-status="listed" ${isReady ? "" : "disabled style=\"opacity:.45;cursor:not-allowed\""}>Approve & list <span class="kbd">A</span></button>
          </div>
        </div>
      </div>
    </div>
  `;
}

async function openOverlay(id) {
  state.openId = id;
  const visible = sortedVisibleItems();
  const index = visible.findIndex((item) => item.id === id);
  const item = await fetchFullItem(id);
  document.body.insertAdjacentHTML("beforeend", overlayHtml(item, Math.max(0, index), visible.length));
  wireOverlay(item);
}

function closeOverlay() {
  $(".overlay")?.remove();
  state.openId = null;
}

function wireOverlay(item) {
  $$(".overlay [data-close]").forEach((node) => node.addEventListener("click", closeOverlay));
  $(".overlay").addEventListener("click", (event) => {
    if (event.target.classList.contains("overlay")) closeOverlay();
  });
  $(".overlay [data-next]")?.addEventListener("click", () => navOverlay(1));
  $(".overlay [data-prev]")?.addEventListener("click", () => navOverlay(-1));
  $(".overlay [data-save-draft]")?.addEventListener("click", () => saveDraft(item.id));
  $(".overlay [data-research]")?.addEventListener("click", () => runResearch(item.id));
  $(".overlay [data-open-photo]")?.addEventListener("click", () => openLightbox(item));
  $("#carousel-hero")?.addEventListener("click", () => openLightbox(item));
  $(".overlay [data-set-cover]")?.addEventListener("click", () => setCurrentCover(item));
  $$(".overlay .carousel-thumb-wrap[data-photo-index]").forEach((thumbWrap) => thumbWrap.addEventListener("click", () => {
    const index = Number(thumbWrap.dataset.photoIndex || 0);
    $(".carousel").dataset.activePhoto = String(index);
    $("#carousel-hero").innerHTML = photoBlock(item, "carousel-hero", item.cat, index);
    $$(".carousel-thumb").forEach((thumb) => thumb.classList.remove("active"));
    $(".carousel-thumb", thumbWrap)?.classList.add("active");
  }));
  $$(".overlay [data-status]").forEach((button) => button.addEventListener("click", async () => {
    if (button.disabled) return;
    const data = await postJson(`/api/items/${item.id}/status`, { status: button.dataset.status });
    updateSummary(data.item);
    await loadItems();
    closeOverlay();
    toast(`Status set to ${button.dataset.status}`, button.dataset.status === "approved" ? "moss" : "teal");
  }));
}

async function saveDraft(id) {
  const form = $("#draft-form");
  const body = Object.fromEntries(new FormData(form).entries());
  body.format_kind = "fixed";
  const data = await postJson(`/api/items/${id}/draft`, body);
  updateSummary(data.item);
  render();
  toast("Draft saved", "amber");
  await refreshOpenOverlay(id);
}

function activePhotoIndex() {
  return Number($(".carousel")?.dataset.activePhoto || 0);
}

function activePhotoUrl(item) {
  return item.photoUrls?.[activePhotoIndex()] || item.photoUrls?.[0] || "";
}

async function setCurrentCover(item) {
  const photoUrl = activePhotoUrl(item);
  const photoId = photoUrl ? new URL(photoUrl, window.location.href).searchParams.get("id") : "";
  if (!photoId) {
    toast("No real photo selected to make hero", "teal");
    return;
  }
  try {
    const data = await postJson(`/api/items/${item.id}/cover`, { photo_id: photoId });
    updateSummary(data.item);
    await loadItems();
    toast("Hero shot updated", "amber");
    await refreshOpenOverlay(item.id);
  } catch (error) {
    toast(`Hero update failed · ${error.message}`, "teal");
  }
}

function openLightbox(item) {
  const index = activePhotoIndex();
  const photoUrl = activePhotoUrl(item);
  $(".lightbox")?.remove();
  if (!photoUrl) {
    toast("No full-size photo available", "teal");
    return;
  }
  document.body.insertAdjacentHTML("beforeend", `
    <div class="lightbox" role="dialog" aria-modal="true" aria-label="Photo preview">
      <div class="lightbox-top">
        <div>
          <div class="crumb"><span>PHOTO ${index + 1} OF ${item.photoUrls?.length || 1}</span><span>·</span><span>${escapeHtml(item.brand)} ${escapeHtml(item.model)}</span></div>
          <div class="lightbox-caption">${escapeHtml(photoUrl)}</div>
        </div>
        <button class="btn ghost icon" data-lightbox-close title="Close">✕</button>
      </div>
      <div class="lightbox-stage">
        <img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(item.brand)} ${escapeHtml(item.model)} large photo ${index + 1}">
      </div>
      <div class="lightbox-actions">
        <div class="hint">Click outside or press Esc to close</div>
        <div style="display:flex;gap:8px">
          <button class="btn sm" data-lightbox-prev>← Previous</button>
          <button class="btn sm" data-lightbox-cover>Make hero shot</button>
          <button class="btn sm" data-lightbox-next>Next →</button>
        </div>
      </div>
    </div>
  `);
  const lightbox = $(".lightbox");
  const close = () => lightbox?.remove();
  $("[data-lightbox-close]")?.addEventListener("click", close);
  lightbox.addEventListener("click", (event) => {
    if (event.target.classList.contains("lightbox")) close();
  });
  $("[data-lightbox-cover]")?.addEventListener("click", () => setCurrentCover(item));
  $("[data-lightbox-prev]")?.addEventListener("click", () => stepLightbox(item, -1));
  $("[data-lightbox-next]")?.addEventListener("click", () => stepLightbox(item, 1));
}

function stepLightbox(item, delta) {
  const total = item.photoUrls?.length || 1;
  const next = Math.max(0, Math.min(total - 1, activePhotoIndex() + delta));
  $(".carousel").dataset.activePhoto = String(next);
  $("#carousel-hero").innerHTML = photoBlock(item, "carousel-hero", item.cat, next);
  $$(".carousel-thumb").forEach((thumb) => thumb.classList.remove("active"));
  const wrap = $(`.carousel-thumb-wrap[data-photo-index="${next}"]`);
  $(".carousel-thumb", wrap)?.classList.add("active");
  openLightbox(item);
}

async function runResearch(id) {
  const button = $(".overlay [data-research]");
  if (button) {
    button.disabled = true;
    button.textContent = "Researching...";
  }
  try {
    const data = await postJson(`/api/items/${id}/research`, {});
    updateSummary(data.item);
    await loadItems();
    toast("Market research updated", "amber");
    await refreshOpenOverlay(id);
  } catch (error) {
    toast(`Research failed · ${error.message}`, "teal");
  } finally {
    const freshButton = $(".overlay [data-research]");
    if (freshButton) {
      freshButton.disabled = false;
      freshButton.textContent = "More research";
    }
  }
}

async function refreshOpenOverlay(id) {
  if (state.openId !== id) return;
  state.fullItems.delete(id);
  const current = $(".overlay");
  if (current) current.remove();
  await openOverlay(id);
}

async function navOverlay(delta) {
  const visible = sortedVisibleItems();
  const index = visible.findIndex((item) => item.id === state.openId);
  const next = visible[Math.max(0, Math.min(visible.length - 1, index + delta))];
  if (!next || next.id === state.openId) return;
  closeOverlay();
  await openOverlay(next.id);
}

document.addEventListener("keydown", (event) => {
  const tag = event.target.tagName?.toLowerCase();
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    openCommandPalette();
    return;
  }
  if (tag === "input" || tag === "textarea") return;
  if (event.key === "Escape" && $(".lightbox")) {
    $(".lightbox")?.remove();
    return;
  }
  if (event.key === "Escape" && state.openId) closeOverlay();
  if ((event.key === "j" || event.key === "ArrowDown") && state.openId) navOverlay(1);
  if ((event.key === "k" || event.key === "ArrowUp") && state.openId) navOverlay(-1);
  if ((event.key === "x" || event.key === "X") && state.openId) {
    const reject = $(".overlay [data-status='archived']");
    reject?.click();
  }
  if ((event.key === "a" || event.key === "A") && state.openId) {
    const approve = $(".overlay [data-status='listed']");
    if (approve && !approve.disabled) approve.click();
  }
});

renderShell();
loadItems().catch((error) => {
  $("#item-rows").innerHTML = `<tr><td colspan="12" style="padding:40px"><div class="empty">${escapeHtml(error.message)}</div></td></tr>`;
});
setInterval(() => {
  if (!state.openId && !$(".command-overlay")) {
    loadItems().catch(() => {});
  }
}, 15000);
