/* VWAP Copilot dashboard */
let chart, candleSeries, volumeSeries, vwapSeries, pdvSeries;
let activeSymbol = null;
let watchItems = [];

function initChart() {
  const el = document.getElementById('chart');
  chart = LightweightCharts.createChart(el, {
    layout: { background: { color: '#131722' }, textColor: '#d6dbe6' },
    grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
    timeScale: { timeVisible: true, secondsVisible: false },
    rightPriceScale: { borderColor: '#2a3142' },
    height: 460,
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
  new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth })).observe(el);
}

async function j(url, opts) {
  const r = await fetch(url, opts);
  return r.json();
}

async function refreshChart() {
  if (!activeSymbol) return;
  try {
    const d = await j(`/api/chart/${activeSymbol}`);
    if (d.error) return;
    candleSeries.setData(d.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
    volumeSeries.setData(d.bars.map(b => ({ time: b.time, value: b.volume })));
    vwapSeries.setData(d.vwap);
    pdvSeries.setData(d.prior_vwap);
    candleSeries.setMarkers(d.markers || []);
  } catch (e) { /* chart not ready */ }
}

function fmtCap(n) {
  if (n == null) return '—';
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${Math.round(n / 1e6)}M`;
  return `$${Math.round(n)}`;
}

function checkLine(name, c) {
  if (!c) return '';
  const cls = c.ok ? 'ok' : 'no';
  const icon = c.ok ? '✓' : '✗';
  return `<div class="checkline ${cls}">${icon} ${name}: ${c.value} (need ${c.need}${name === 'gap' ? '%' : name === 'rvol' ? 'x' : ''})</div>`;
}

function renderDetail(d) {
  const el = document.getElementById('detail-body');
  if (!d || d.error) {
    el.innerHTML = '<div class="empty">No detail available.</div>';
    return;
  }
  const badge = d.qualified
    ? '<span class="badge ok">MEETS CRITERIA</span>'
    : '<span class="badge no">NOT READY</span>';
  const feed = d.watching
    ? '<span class="badge ok">CHART LIVE</span>'
    : '<span class="badge no">TOP 8 CHARTS ONLY</span>';
  const earnings = d.earnings
    ? `<div class="checkline">EPS est ${d.earnings.estimatedEarning ?? '—'} · act ${d.earnings.actualEarningResult ?? '—'}</div>`
    : '';
  const news = (d.headlines || []).length
    ? `<ul class="headlines">${d.headlines.slice(0, 5).map(h => `<li>${h}</li>`).join('')}</ul>`
    : '<div class="empty">No recent headlines loaded.</div>';

  el.innerHTML = `
    <div class="detail-head">
      <span class="sym">${d.symbol}</span>
      <span class="badge">${d.catalyst}</span>
      ${badge}
      ${feed}
      <span style="margin-left:auto;color:var(--blue);font-weight:600">${d.score} score</span>
    </div>
    <div class="detail-grid">
      <div class="detail-cell"><div class="lbl">Market Cap</div><div class="val">${fmtCap(d.market_cap_usd)}</div></div>
      <div class="detail-cell"><div class="lbl">Price</div><div class="val">${d.price != null ? '$' + d.price : '—'}</div></div>
      <div class="detail-cell"><div class="lbl">Gap</div><div class="val">${d.gap_pct != null ? (d.gap_pct > 0 ? '+' : '') + d.gap_pct + '%' : '—'}</div></div>
      <div class="detail-cell"><div class="lbl">Rel Volume</div><div class="val">${d.relative_volume != null ? d.relative_volume + 'x' : '—'}</div></div>
    </div>
    ${checkLine('gap', d.checks?.gap)}
    ${checkLine('rvol', d.checks?.rvol)}
    ${checkLine('price', d.checks?.price)}
    ${earnings}
    <h2 style="font-size:12px;color:var(--muted);margin:12px 0 6px;text-transform:uppercase;letter-spacing:.06em">Headlines</h2>
    ${news}`;
}

async function selectSymbol(sym) {
  activeSymbol = sym;
  document.getElementById('chart-symbol').textContent = sym;
  renderWatchlistRows();
  try {
    const d = await j(`/api/watchlist/${sym}`);
    renderDetail(d);
  } catch (e) {
    renderDetail(null);
  }
  refreshChart();
}
window.selectSymbol = selectSymbol;

function renderWatchlistRows() {
  const tbody = document.querySelector('#watchlist tbody');
  const empty = document.getElementById('watch-empty');
  if (!watchItems.length) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    empty.textContent = 'Waiting for scan — confirm FINNHUB_API_KEY is set.';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = watchItems.map(w => {
    const active = w.symbol === activeSymbol ? 'active' : '';
    const qual = w.qualified ? 'qualified' : '';
    const badge = w.qualified
      ? '<span class="badge ok">READY</span>'
      : '<span class="badge no">not ready</span>';
    const gap = w.gap_pct != null ? `${w.gap_pct > 0 ? '+' : ''}${w.gap_pct}%` : '—';
    const rvol = w.relative_volume != null ? `${w.relative_volume}x` : '—';
    const price = w.price != null ? `$${w.price}` : '—';
    const cap = fmtCap(w.market_cap_usd);
    const gapCls = w.gap_pct > 0 ? 'pos' : (w.gap_pct < 0 ? 'neg' : '');
    return `<tr class="${active} ${qual}" onclick="selectSymbol('${w.symbol}')">
      <td><strong>${w.symbol}</strong></td>
      <td>${w.catalyst}</td>
      <td>${cap}</td>
      <td>${price}</td>
      <td class="${gapCls}">${gap}</td>
      <td>${rvol}</td>
      <td class="score">${w.score}</td>
      <td>${badge}</td>
    </tr>`;
  }).join('');
}

async function refreshWatchlist() {
  watchItems = await j('/api/watchlist');
  renderWatchlistRows();
  if (!activeSymbol && watchItems.length) await selectSymbol(watchItems[0].symbol);
  else if (activeSymbol) renderWatchlistRows();
}

async function refreshStatus() {
  const s = await j('/api/status');
  const pill = document.getElementById('broker-pill');
  const label = (s.broker || 'broker').toUpperCase();
  pill.textContent = s.broker_connected ? `${label} connected` : `${label} offline`;
  pill.className = 'pill ' + (s.broker_connected ? 'on' : 'off');
  const auto = document.getElementById('auto-pill');
  auto.textContent = s.auto_trade_enabled ? 'AUTO ON' : 'AUTO OFF';
  auto.className = 'pill ' + (s.auto_trade_enabled ? 'on' : 'off');
  const toggle = document.getElementById('auto-toggle');
  toggle.textContent = s.auto_trade_enabled ? 'Disable Auto-Trade' : 'Enable Auto-Trade';
  toggle.className = s.auto_trade_enabled ? 'on' : 'off';
  const uniN = Object.keys(s.scan_universe || {}).length;
  const qualN = watchItems.filter(w => w.qualified).length;
  const capPill = document.getElementById('cap-pill');
  if (capPill) {
    const on = s.min_market_cap_filter_enabled;
    capPill.textContent = on
      ? `Cap ≥ $${s.min_market_cap_millions}M`
      : 'Cap filter OFF';
    capPill.className = 'pill ' + (on ? 'on' : 'off');
  }
  const capToggle = document.getElementById('cap-toggle');
  if (capToggle) {
    capToggle.textContent = s.min_market_cap_filter_enabled ? 'Disable Cap Filter' : 'Enable Cap Filter';
    capToggle.className = s.min_market_cap_filter_enabled ? 'on' : 'off';
  }
  document.getElementById('risk-pill').textContent =
    `${s.market_session || '—'} · List: ${uniN} · Ready: ${qualN} · Charts: ${(s.watching || []).length}` +
    ` · Trades: ${s.trades_today} · P&L: $${s.realized_pnl_today}` +
    (s.can_trade ? '' : ` · BLOCKED: ${s.blocked_reason}`);
}

function signalCard(s) {
  const reasons = (s.breakdown?.reasons || []).slice(0, 6).join(' · ');
  return `<div class="signal">
    <div class="head">
      <span>${s.symbol} <span style="color:${s.direction === 'LONG' ? 'var(--green)' : 'var(--red)'}">${s.direction}</span></span>
      <span class="conf">${s.confidence}%</span>
    </div>
    <div class="levels">
      <span>Entry ${s.entry}</span><span>Stop ${s.stop}</span><span>Target ${s.target}</span>
    </div>
    <div class="reasons">${s.setup.replaceAll('_', ' ')} — ${reasons}</div>
    <div class="actions">
      <button class="buy" onclick="approve('${s.id}')">${s.direction === 'LONG' ? 'Buy' : 'Short'}</button>
      <button class="ign" onclick="ignore('${s.id}')">Ignore</button>
    </div>
  </div>`;
}

async function refreshSignals() {
  const d = await j('/api/signals');
  const el = document.getElementById('pending');
  el.innerHTML = d.pending.length
    ? d.pending.map(signalCard).join('')
    : '<div class="empty">No pending signals.</div>';
}

async function refreshTrades() {
  const d = await j('/api/trades');
  const tbody = document.querySelector('#open-trades tbody');
  document.getElementById('open-empty').style.display = d.open.length ? 'none' : 'block';
  tbody.innerHTML = d.open.map(t => {
    const pnl = t.unrealized_pnl ?? 0;
    return `<tr>
      <td>${t.symbol}</td><td>${t.direction}</td><td>${t.quantity}</td>
      <td>${t.entry}</td><td>${t.current_price ?? '—'}</td>
      <td class="${pnl >= 0 ? 'pos' : 'neg'}">$${pnl.toFixed(2)}</td>
      <td>${t.confidence}%</td>
      <td><button class="closebtn" onclick="closeTrade('${t.id}')">Close</button></td>
    </tr>`;
  }).join('');
}

async function refreshPnl() {
  const d = await j('/api/pnl');
  const grid = document.getElementById('pnl-grid');
  const order = ['today', 'week', 'month', 'lifetime'];
  grid.innerHTML = order.map(k => {
    const v = d[k].pnl;
    return `<div class="pnl-cell">
      <div class="label">${k}</div>
      <div class="value" style="color:${v >= 0 ? 'var(--green)' : 'var(--red)'}">$${v.toFixed(2)}</div>
    </div>`;
  }).join('');
  document.querySelector('#pnl-metrics tbody').innerHTML = order.map(k => {
    const m = d[k];
    return `<tr><td>${k}</td><td>${m.trades}</td><td>${m.win_rate}%</td>
      <td class="pos">$${m.avg_winner}</td><td class="neg">$${m.avg_loser}</td>
      <td>${m.profit_factor ?? '—'}</td></tr>`;
  }).join('');
}

const SETTING_LABELS = {
  min_market_cap_filter_enabled: 'market cap filter',
  min_market_cap_millions: 'min market cap ($M)',
  auto_trade_threshold: 'auto trade threshold',
  max_trades_per_day: 'max trades per day',
  max_daily_loss: 'max daily loss',
  risk_per_trade: 'risk per trade',
  max_position_size: 'max position size',
};

const EDITABLE = [
  'min_market_cap_filter_enabled',
  'min_market_cap_millions',
  'auto_trade_threshold',
  'max_trades_per_day',
  'max_daily_loss',
  'risk_per_trade',
  'max_position_size',
];

async function refreshSettings() {
  const s = await j('/api/settings');
  document.getElementById('settings').innerHTML = EDITABLE.map(k => {
    const v = s[k];
    const input = typeof v === 'boolean'
      ? `<input type="checkbox" id="set-${k}" ${v ? 'checked' : ''}>`
      : `<input type="number" id="set-${k}" value="${v}" ${k === 'min_market_cap_millions' && !s.min_market_cap_filter_enabled ? 'disabled' : ''}>`;
    return `<div class="settings-row"><span>${SETTING_LABELS[k] || k}</span>${input}</div>`;
  }).join('') + `<div class="settings-row"><span></span>
    <button class="buy" style="padding:5px 14px;border:0;border-radius:6px;cursor:pointer"
      onclick="saveSettings()">Save</button></div>`;
}

async function saveSettings() {
  const patch = {};
  for (const k of EDITABLE) {
    const el = document.getElementById(`set-${k}`);
    patch[k] = el.type === 'checkbox' ? el.checked : Number(el.value);
  }
  await j('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch) });
  refreshSettings();
  refreshWatchlist();
  refreshStatus();
}

async function approve(id) { await j(`/api/signals/${id}/approve`, { method: 'POST' }); refreshAll(); }
async function ignore(id)  { await j(`/api/signals/${id}/ignore`,  { method: 'POST' }); refreshSignals(); }
async function closeTrade(id) { await j(`/api/trades/${id}/close`, { method: 'POST' }); refreshAll(); }
async function toggleAuto() {
  await j('/api/automation/toggle', { method: 'POST' });
  refreshStatus();
}

async function toggleMarketCapFilter() {
  await j('/api/filters/market-cap/toggle', { method: 'POST' });
  refreshSettings();
  refreshWatchlist();
  refreshStatus();
}

async function refreshAll() {
  await refreshWatchlist();
  refreshStatus();
  refreshSignals();
  refreshTrades();
  refreshPnl();
}

initChart();
refreshAll();
refreshSettings();
setInterval(refreshAll, 10000);
setInterval(refreshChart, 30000);
