/* Kenny VWAP Trading Cockpit */
let chart, candleSeries, volumeSeries, vwapSeries, pdvSeries;
let priceLines = [];
let activeSymbol = null;
let activeSignalId = null;
let watchItems = [];
let pendingSignals = [];
let lastStatus = {};
let lastPnl = {};
let chartHasBars = false;
let chartPollTimer = null;
let chartGeneration = 0;
let chartInFlight = null;

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function toast(msg, ok = true) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = 'toast show ' + (ok ? 'ok' : 'err');
  setTimeout(() => el.classList.remove('show'), ok ? 6000 : 10000);
}

async function j(url, opts) {
  const r = await fetch(url, opts);
  const data = await r.json();
  if (r.ok === false) throw new Error(data.detail || data.error || 'Request failed');
  return data;
}

function fmtCap(n) {
  if (n == null) return '—';
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${Math.round(n / 1e6)}M`;
  return `$${Math.round(n)}`;
}

function fmtMoney(n) {
  if (n == null || n === '—') return '—';
  const v = Number(n);
  const s = v >= 0 ? '+' : '-';
  return `${s}$${Math.abs(v).toFixed(2)}`;
}

function pnlClass(v) {
  return v >= 0 ? 'pos' : 'neg';
}

/* ── Chart ─────────────────────────────────────────────── */

function initChart() {
  const el = document.getElementById('chart');
  chart = LightweightCharts.createChart(el, {
    layout: { background: { color: '#131722' }, textColor: '#d6dbe6' },
    grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
    timeScale: { timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderColor: '#2a3142' },
  });
  candleSeries = chart.addCandlestickSeries({
    upColor: '#26a69a', downColor: '#ef5350',
    wickUpColor: '#26a69a', wickDownColor: '#ef5350', borderVisible: false,
  });
  volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: 'volume' }, priceScaleId: 'vol', color: '#2e4a66',
  });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  vwapSeries = chart.addLineSeries({ color: '#2bc4e2', lineWidth: 2, priceLineVisible: false });
  pdvSeries = chart.addLineSeries({
    color: '#e6c300', lineWidth: 2, lineStyle: LightweightCharts.LineStyle.Dotted,
    priceLineVisible: false,
  });
  const ro = new ResizeObserver(() => {
    chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
  });
  ro.observe(el.parentElement);
}

function clearPriceLines() {
  priceLines.forEach(pl => { try { candleSeries.removePriceLine(pl); } catch (_) {} });
  priceLines = [];
}

function addPriceLine(price, color, title, style) {
  if (price == null) return;
  priceLines.push(candleSeries.createPriceLine({
    price, color, lineWidth: 2, lineStyle: style ?? LightweightCharts.LineStyle.Solid,
    axisLabelVisible: true, title,
  }));
}

function renderChartData(d) {
  chartHasBars = true;
  candleSeries.setData(d.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
  volumeSeries.setData(d.bars.map(b => ({ time: b.time, value: b.volume })));
  vwapSeries.setData(d.vwap || []);
  pdvSeries.setData(d.prior_vwap || []);
  candleSeries.setMarkers(d.markers || []);
  clearPriceLines();
  const lv = d.levels;
  if (lv) {
    addPriceLine(lv.entry, '#26a69a', 'Entry', LightweightCharts.LineStyle.Solid);
    addPriceLine(lv.stop, '#ef5350', 'Stop', LightweightCharts.LineStyle.Dashed);
    addPriceLine(lv.target, '#26a69a', 'Target', LightweightCharts.LineStyle.Dotted);
  }
  if (d.last_price != null) {
    addPriceLine(d.last_price, '#d6dbe6', 'Last', LightweightCharts.LineStyle.Solid);
  }
  const setupEl = document.getElementById('chart-setup');
  if (d.signal) {
    setupEl.textContent = `${d.signal.setup} · ${d.signal.direction} · ${d.signal.confidence}/100 · R:R ${d.signal.reward_risk}`;
    if (!activeSignalId) activeSignalId = d.signal.id;
  } else {
    setupEl.textContent = '';
  }
}

async function refreshChart() {
  if (!activeSymbol) return;
  const generation = chartGeneration;
  if (chartInFlight === generation) return;
  chartInFlight = generation;
  const symbol = activeSymbol;
  const loading = document.getElementById('chart-loading');
  if (loading && !chartHasBars) loading.style.display = 'flex';
  const q = activeSignalId ? `?signal_id=${activeSignalId}` : '';
  let delay = 250;
  try {
    for (let i = 0; i < 60; i++) {
      if (generation !== chartGeneration) return;
      const d = await j(`/api/chart/${symbol}${q}`);
      if (generation !== chartGeneration) return;
      if (d.loading) {
        await sleep(delay);
        delay = Math.min(delay * 1.4, 2000);
        continue;
      }
      if (d.error) {
        if (loading) loading.textContent = d.error;
        return;
      }
      if (d.bars?.length) {
        renderChartData(d);
        if (loading) loading.style.display = 'none';
        return;
      }
      await sleep(delay);
      delay = Math.min(delay * 1.4, 2000);
    }
    if (loading) loading.textContent = 'Chart timed out';
  } catch (_) {
    if (generation === chartGeneration && loading) loading.textContent = 'Chart failed';
  } finally {
    if (chartInFlight === generation) chartInFlight = null;
  }
}

function startChartPoll() {
  if (chartPollTimer) clearInterval(chartPollTimer);
  chartPollTimer = setInterval(refreshChart, 5000);
}

/* ── Scanner rail ──────────────────────────────────────── */

function renderScanner() {
  const el = document.getElementById('scanner-list');
  const countEl = document.getElementById('scan-count');
  const ready = watchItems.filter(w => w.qualified).length;
  countEl.textContent = `${ready}/${watchItems.length} ready`;
  const health = document.getElementById('scan-health');
  const membership = lastStatus.membership || {};
  const coverage = lastStatus.scan_coverage || {};
  const messages = [];
  if (lastStatus.scan_russell_1000_only !== false && membership.state === 'ready') {
    messages.push(`IWB proxy ${membership.as_of} · ${membership.count} stocks`);
  }
  if (lastStatus.scan_in_progress) messages.push('Refreshing scan');
  if (lastStatus.last_scan_at) messages.push(`Updated ${new Date(lastStatus.last_scan_at).toLocaleTimeString()}`);
  if (coverage.unmonitored_symbols?.length) messages.push(`${coverage.unmonitored_symbols.length} outside active chart limit`);
  messages.push(...(lastStatus.scan_source_errors || []));
  messages.push(...(lastStatus.scan_filter_errors || []));
  if (lastStatus.last_scan_error) messages.push(lastStatus.last_scan_error);
  if (health) health.textContent = messages.join(' · ');
  if (!watchItems.length) {
    const errors = lastStatus.scan_filter_errors || [];
    if (errors.length) {
      el.textContent = errors.join(' ');
      return;
    }
    el.textContent = lastStatus.market_session === 'closed' ? 'Market closed. No symbols in the current filtered scan.' : 'No symbols in the current filtered scan.';
    return;
  }
  el.innerHTML = watchItems.map(w => {
    const cls = [
      'scan-row',
      w.symbol === activeSymbol ? 'active' : '',
      w.qualified ? 'ready' : '',
    ].filter(Boolean).join(' ');
    const st = w.qualified ? '<span class="badge ok">RDY</span>' : '<span class="badge no">—</span>';
    return `<div class="${cls}" onclick="selectSymbol('${w.symbol}')">
      <span class="sym">${w.symbol}</span>
      <span class="sc">${w.score}</span>
      ${st}
      <div class="scan-bar"><div class="scan-bar-fill" style="width:${Math.min(100, w.score)}%"></div></div>
    </div>`;
  }).join('');
}

/* ── Detail / scan tab ─────────────────────────────────── */

function weightedBarRow(label, weightPct, value, scan) {
  const v = Math.min(100, Math.max(0, value ?? 0));
  return `<div class="bd-row">
    <span style="color:var(--muted);font-size:10px">${label} ${weightPct}%</span>
    <div class="bd-bar"><div class="bd-fill ${scan ? 'scan' : ''}" style="width:${v}%"></div></div>
    <span style="text-align:right;font-weight:600">${Math.round(v)}</span>
  </div>`;
}

function checkLine(name, c, weight) {
  if (!c) return '';
  const icon = c.ok ? '✓' : '✗';
  const unit = name === 'gap' || name === 'spread' ? '%' : name === 'rvol' ? 'x' : '';
  const label = name === 'dollar_volume' ? 'Turnover 5m ($)' : name === 'activity' ? 'Active minutes / 5' : name;
  const weighting = weight == null ? '' : ` (${weight}%)`;
  return `<div class="checkline ${c.ok ? 'ok' : 'no'}">${icon} ${label}${weighting}: ${c.value ?? 'unknown'} / ${c.need}${unit}</div>`;
}

function renderDetail(d) {
  const el = document.getElementById('detail-body');
  if (!d || d.error) {
    el.innerHTML = '<div class="empty">No detail.</div>';
    return;
  }
  const gapP = d.checks?.gap ? Math.min(100, Math.abs(d.checks.gap.value) / d.checks.gap.need * 100) : 0;
  const rvolP = d.checks?.rvol ? Math.min(100, d.checks.rvol.value / d.checks.rvol.need * 100) : 0;
  const liquidityKeys = ['dollar_volume', 'spread', 'activity'];
  const liquidityP = liquidityKeys.filter(k => d.checks?.[k]?.ok).length / liquidityKeys.length * 100;
  el.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
      <strong style="font-size:16px">${d.symbol}</strong>
      <span style="color:var(--green);font-weight:700;font-size:18px">${d.score}</span>
    </div>
    <div class="bd-block">
      ${weightedBarRow('Gap', 40, gapP, true)}
      ${weightedBarRow('RVol', 40, rvolP, true)}
      ${weightedBarRow('Liquidity', 20, liquidityP, true)}
    </div>
    <div class="detail-grid">
      <div class="detail-cell"><div class="lbl">Mkt Cap</div><div class="val">${fmtCap(d.market_cap_usd)}</div></div>
      <div class="detail-cell"><div class="lbl">Price</div><div class="val">$${d.price ?? '—'}</div></div>
      <div class="detail-cell"><div class="lbl">Gap</div><div class="val">${d.gap_pct != null ? (d.gap_pct > 0 ? '+' : '') + d.gap_pct + '%' : '—'}</div></div>
      <div class="detail-cell"><div class="lbl">RVol</div><div class="val">${d.relative_volume != null ? d.relative_volume + 'x' : '—'}</div></div>
    </div>
    ${checkLine('gap', d.checks?.gap, 40)}
    ${checkLine('rvol', d.checks?.rvol, 40)}
    ${liquidityKeys.map(k => checkLine(k, d.checks?.[k])).join('')}`;
}

async function selectSymbol(sym, signalId) {
  chartGeneration += 1;
  const generation = chartGeneration;
  activeSymbol = sym;
  if (signalId !== undefined) activeSignalId = signalId;
  else {
    const match = pendingSignals.filter(s => s.symbol === sym).sort((a, b) => b.confidence - a.confidence)[0];
    activeSignalId = match?.id ?? null;
  }
  document.getElementById('chart-symbol').textContent = sym;
  chartHasBars = false;
  const loading = document.getElementById('chart-loading');
  if (loading) {
    loading.style.display = 'flex';
    loading.textContent = 'Loading chart…';
  }
  renderScanner();
  renderOpportunities();
  renderDetail(watchItems.find(w => w.symbol === sym));
  refreshChart();
  j(`/api/watchlist/${sym}`)
    .then(d => { if (generation === chartGeneration) renderDetail(d); })
    .catch(() => { if (generation === chartGeneration) renderDetail(null); });
}
window.selectSymbol = selectSymbol;

function showTab(name) {
  document.querySelectorAll('.drawer-tabs button').forEach((b, i) => {
    b.classList.toggle('active', (name === 'scan' && i === 0) || (name === 'rules' && i === 1));
  });
  document.getElementById('tab-scan').classList.toggle('active', name === 'scan');
  document.getElementById('tab-rules').classList.toggle('active', name === 'rules');
}
window.showTab = showTab;

/* ── Command bar ───────────────────────────────────────── */

const CAP_PRESETS = [
  { label: 'All', millions: 0 }, { label: '$300M', millions: 300 }, { label: '$500M', millions: 500 },
  { label: '$1B', millions: 1000 }, { label: '$2B', millions: 2000 }, { label: '$5B', millions: 5000 },
];

function renderCapSelector(m) {
  const el = document.getElementById('cap-select');
  if (!el) return;
  el.innerHTML = '<span class="lbl">Cap</span>' + CAP_PRESETS.map(p =>
    `<button class="${p.millions === m ? 'active' : ''}" onclick="setMarketCap(${p.millions})">${p.label}</button>`
  ).join('');
}

async function setMarketCap(millions) {
  await j('/api/filters/market-cap', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ millions }),
  });
  refreshAll();
}
window.setMarketCap = setMarketCap;

function renderRussellToggle(on) {
  const el = document.getElementById('russell-toggle');
  if (!el) return;
  el.innerHTML = `<span class="lbl">Universe</span>
    <button class="${on ? 'active' : ''}" onclick="setRussellFilter(true)" title="NYSE/Nasdaq Russell 1000 only">R1K</button>
    <button class="${on ? '' : 'active'}" onclick="setRussellFilter(false)" title="All NYSE/Nasdaq movers">Wide</button>`;
}

async function setRussellFilter(enabled) {
  await j('/api/filters/russell-1000', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  toast(enabled ? 'Russell 1000 filter ON' : 'Wide universe (NYSE/Nasdaq)', true);
  refreshAll();
}
window.setRussellFilter = setRussellFilter;

function setCmd(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = 'val' + (cls ? ' ' + cls : '');
}

async function refreshCommandBar() {
  const [s, pnl, acct] = await Promise.all([j('/api/status'), j('/api/pnl'), j('/api/account')]);
  lastStatus = s;
  lastPnl = pnl;
  const t = pnl.today || {};
  const dash = pnl.dashboard || {};
  setCmd('cmd-pnl', fmtMoney(t.pnl), pnlClass(t.pnl || 0));
  setCmd('cmd-week', fmtMoney(dash.week_pnl ?? pnl.week?.pnl), pnlClass(dash.week_pnl ?? pnl.week?.pnl ?? 0));
  setCmd('cmd-win', t.win_rate != null ? `${t.win_rate}%` : '—');
  setCmd('cmd-trades', String(s.trades_today ?? 0));
  setCmd('cmd-pf', t.profit_factor != null ? String(t.profit_factor) : '—');
  setCmd('cmd-risk', dash.open_risk != null ? `$${dash.open_risk}` : '—');
  const bp = acct.buying_power;
  setCmd('cmd-bp', bp != null ? `$${(bp / 1000).toFixed(1)}K` : '—');
  const broker = document.getElementById('broker-pill');
  broker.textContent = s.broker_connected ? (s.broker || 'broker').toUpperCase() : 'OFFLINE';
  broker.className = 'pill ' + (s.broker_connected ? 'on' : 'off');
  document.getElementById('market-pill').textContent = (s.market_session || '—').toUpperCase();
  const paper = s.execution_mode === 'paper' && s.paper_verified;
  document.getElementById('execution-pill').textContent = paper ? 'PAPER ONLY' : 'RESEARCH';
  document.getElementById('auto-pill').textContent = s.auto_trade_enabled ? 'PAPER AUTO ON' : 'AUTO OFF';
  document.getElementById('auto-pill').className = 'pill ' + (s.auto_trade_enabled ? 'on' : 'off');
  const sw = document.getElementById('auto-switch');
  sw.className = 'switch' + (s.auto_trade_enabled ? ' on' : '');
  sw.setAttribute('aria-checked', s.auto_trade_enabled ? 'true' : 'false');
  sw.disabled = !paper;
  renderRussellToggle(s.scan_russell_1000_only !== false);
  renderCapSelector(s.min_market_cap_millions);
  renderScanner();
}

/* ── Best opportunities ────────────────────────────────── */

function confidenceMini(b) {
  if (!b) return '';
  return `<div class="bd-block" style="margin:4px 0;padding:4px">
    ${weightedBarRow('Setup', 100, b.technical)}
  </div>`;
}

function oppCard(s) {
  const rr = s.target && s.entry && s.stop
    ? (Math.abs(s.target - s.entry) / Math.abs(s.entry - s.stop)).toFixed(1) : '—';
  const thresh = lastStatus.auto_trade_threshold ?? 90;
  const ageMin = s.created_at
    ? Math.max(0, Math.floor((Date.now() - new Date(s.created_at).getTime()) / 60000))
    : null;
  const ageHint = ageMin != null ? `<div class="auto-hint">${ageMin}m ago</div>` : '';
  const autoHint = lastStatus.auto_trade_enabled && s.confidence < thresh
    ? `<div class="auto-hint">Auto needs ${thresh}/100</div>` : '';
  const sel = s.id === activeSignalId ? ' selected' : '';
  const btnCls = s.direction === 'LONG' ? 'buy' : 'short';
  const paper = lastStatus.execution_mode === 'paper' && lastStatus.paper_verified;
  const btnLabel = s.direction === 'LONG' ? 'Paper Buy' : 'Paper Short';
  return `<div class="opp${sel}" onclick="selectSymbol('${s.symbol}','${s.id}')">
    <div class="head">
      <span>${s.symbol} <span style="color:${s.direction === 'LONG' ? 'var(--green)' : 'var(--red)'}">${s.direction}</span></span>
      <span class="conf">${s.confidence}/100</span>
    </div>
    <div style="font-size:11px;color:var(--muted)">${(s.setup || '').replaceAll('_', ' ')}</div>
    ${confidenceMini(s.breakdown)}
    <div class="levels"><span>E ${s.entry}</span><span>S ${s.stop}</span><span>T ${s.target}</span></div>
    <div class="rr">R:R ${rr}</div>
    ${ageHint}
    ${autoHint}
    <div class="actions" onclick="event.stopPropagation()">
      ${paper ? `<button class="${btnCls}" onclick="approve('${s.id}')">${btnLabel}</button>` : ''}
      <button class="ign" onclick="ignore('${s.id}')">Skip</button>
    </div>
  </div>`;
}

function renderOpportunities() {
  const el = document.getElementById('pending');
  const sorted = [...pendingSignals].sort((a, b) => b.confidence - a.confidence);
  el.innerHTML = sorted.length
    ? sorted.map(oppCard).join('')
    : `<div class="empty">${lastStatus.scan_filter_errors?.length || lastStatus.last_scan_error ? 'Scanner unavailable. Check scanner status.' : lastStatus.market_session === 'closed' ? 'Market closed. No fresh morning alerts.' : 'No fresh qualifying VWAP setups.'}</div>`;
}

async function refreshSignals() {
  const d = await j('/api/signals');
  pendingSignals = d.pending || [];
  renderOpportunities();
}

/* ── Orders + positions ────────────────────────────────── */

function renderOrders(rows) {
  const el = document.getElementById('order-chips');
  if (!rows.length) {
    el.innerHTML = '<span class="empty" style="padding:0">No pending orders</span>';
    return;
  }
  el.innerHTML = rows.map(o => {
    const px = o.price != null ? `@ $${o.price}` : '';
    const qty = o.filled_qty > 0 && o.filled_qty < o.qty ? `${o.filled_qty}/${o.qty}` : o.qty;
    return `<span class="order-chip">${o.type} ${o.side} ${o.symbol} ${qty} ${px} · ${o.status}</span>`;
  }).join('');
}

function tradeProgress(t) {
  const cur = t.current_price ?? t.entry;
  const range = t.target - t.entry;
  if (!range) return 0;
  const p = t.direction === 'LONG'
    ? (cur - t.entry) / range
    : (t.entry - cur) / (t.entry - t.target);
  return Math.max(0, Math.min(100, p * 100));
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function riskRemaining(t) {
  const cur = t.current_price ?? t.entry;
  return Math.abs(cur - t.stop) * (t.remaining_quantity ?? 0);
}

function renderPositions(open) {
  const el = document.getElementById('positions');
  if (!open.length) {
    el.innerHTML = '<div class="empty">No open positions</div>';
    return;
  }
  el.innerHTML = open.map(t => {
    const pnl = t.unrealized_pnl ?? 0;
    const prog = tradeProgress(t);
    const risk = riskRemaining(t);
    const pending = ` · ${t.status}`;
    return `<div class="trade-card">
      <div class="head">
        <span>${esc(t.symbol)} ${esc(t.direction)}${esc(pending)}</span>
        <span class="pnl ${pnlClass(pnl)}">${t.reconciliation_error ? 'Unverified' : fmtMoney(pnl)}</span>
      </div>
      <div class="trade-meta">${t.filled_quantity ?? 0}/${t.quantity} filled · ${t.remaining_quantity ?? 0} remaining · avg $${t.entry_fill_price ?? '—'}</div>
      <div class="prog-bar"><div class="prog-fill" style="width:${prog.toFixed(0)}%"></div></div>
      <div class="trade-meta">${esc(t.reconciliation_error || t.protection_warning || `Marked risk $${risk.toFixed(0)}`)}</div>
      <button class="closebtn" onclick="closeTrade('${t.id}')" ${t.close_order_id ? 'disabled' : ''}>${t.close_order_id ? 'Close pending' : t.filled_quantity ? 'Close paper trade' : 'Cancel entry'}</button>
    </div>`;
  }).join('');
}

async function refreshOrders() {
  const d = await j('/api/orders');
  renderOrders(d.open || []);
}

async function refreshTrades() {
  const d = await j('/api/trades');
  renderPositions(d.open || []);
  renderPerformance(d.performance || {}, d.closed || []);
}

function renderPerformance(perf, closed) {
  document.getElementById('tracking-health').textContent = perf.storage_error || `${perf.verified_closed || 0} verified closed · ${perf.pending || 0} pending · ${perf.canceled || 0} unfilled/canceled · ${perf.excluded || 0} legacy excluded · ${perf.unresolved || 0} unresolved · ${perf.persistence || 'unknown'} journal`;
  const rows = (perf.groups || []).map(g => `<tr><td>${esc(g.setup)}<br>${esc(g.direction)} / ${esc(g.version)}<br><small>${esc(g.sample_label)}</small></td><td>${g.trades}</td><td>${g.win_rate}%</td><td>${g.average_r ?? '—'}R</td><td>${fmtMoney(g.expectancy)}</td><td>${fmtMoney(g.pnl)}</td></tr>`).join('');
  document.getElementById('setup-results').innerHTML = rows ? `<div class="result-scroll"><table class="results-table"><thead><tr><th>Setup</th><th>Closed</th><th>Win %</th><th>Avg R</th><th>Avg P&amp;L</th><th>Gross P&amp;L</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<div class="empty">No broker-verified closed trades yet.</div>';
  document.getElementById('closed-journal').innerHTML = `<div class="result-scroll"><table class="results-table"><thead><tr><th>Symbol / closed</th><th>Setup</th><th>Fill / exit</th><th>Exit reason</th><th>Gross P&amp;L</th><th>R</th></tr></thead><tbody>${closed.map(t => `<tr><td>${esc(t.symbol)}<br>${esc(t.closed_at)}</td><td>${esc(t.setup)}</td><td>$${t.entry_fill_price} / $${t.exit_price}</td><td>${esc(t.exit_reason)}</td><td>${fmtMoney(t.realized_pnl)}</td><td>${t.realized_r ?? '—'}</td></tr>`).join('')}</tbody></table></div>`;
}

/* ── Settings ──────────────────────────────────────────── */

const SETTING_LABELS = {
  auto_trade_threshold: 'auto threshold',
  max_trades_per_day: 'max trades/day',
  max_daily_loss: 'max daily loss',
  risk_per_trade: 'risk/trade',
  max_position_size: 'max size',
};
const EDITABLE = ['auto_trade_threshold', 'max_trades_per_day', 'max_daily_loss', 'risk_per_trade', 'max_position_size'];

async function refreshSettings() {
  const s = await j('/api/settings');
  document.getElementById('settings').innerHTML = EDITABLE.map(k =>
    `<div class="settings-row"><span>${SETTING_LABELS[k]}</span>
     <input type="number" id="set-${k}" value="${s[k]}"></div>`
  ).join('') + `<div class="settings-row" style="margin-top:8px">
    <button class="buy" style="width:100%;padding:6px;border:0;border-radius:4px;cursor:pointer" onclick="saveSettings()">Save Rules</button></div>`;
}

async function saveSettings() {
  const patch = {};
  for (const k of EDITABLE) patch[k] = Number(document.getElementById(`set-${k}`).value);
  await j('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
  toast('Rules saved', true);
  refreshSettings();
  refreshAll();
}
window.saveSettings = saveSettings;

async function approve(id) {
  const res = await j(`/api/signals/${id}/approve`, { method: 'POST' });
  if (res.ok) toast(res.message || 'Order placed', true);
  else toast(res.error || 'Order failed', false);
  refreshAll();
}
window.approve = approve;

async function ignore(id) {
  await j(`/api/signals/${id}/ignore`, { method: 'POST' });
  if (activeSignalId === id) activeSignalId = null;
  refreshSignals();
  refreshChart();
}
window.ignore = ignore;

async function closeTrade(id) {
  try {
    const res = await j(`/api/trades/${id}/close`, { method: 'POST' });
    toast(res.ok ? res.message : res.error, res.ok);
  } catch (error) { toast(error.message, false); }
  refreshAll();
}
window.closeTrade = closeTrade;

async function toggleAuto() {
  try {
    await j('/api/automation/toggle', { method: 'POST' });
    await refreshCommandBar();
    toast(lastStatus.auto_trade_enabled ? 'Paper automation ON' : 'Paper automation OFF', true);
  } catch (error) { toast(error.message, false); }
}
window.toggleAuto = toggleAuto;

/* ── Refresh loops ─────────────────────────────────────── */

async function refreshWatchlist() {
  watchItems = await j('/api/watchlist');
  renderScanner();
  if (!activeSymbol && watchItems.length) await selectSymbol(watchItems[0].symbol);
  else renderScanner();
}

async function refreshAll() {
  await Promise.all([refreshWatchlist(), refreshCommandBar(), refreshSignals()]);
  refreshOrders();
  refreshTrades();
}

initChart();
refreshAll();
refreshSettings();
startChartPoll();
setInterval(refreshAll, 10000);
setInterval(refreshSignals, 3000);
