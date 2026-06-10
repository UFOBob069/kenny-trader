/* VWAP Copilot dashboard */
let chart, candleSeries, volumeSeries, vwapSeries, pdvSeries;
let activeSymbol = null;
let watching = [];

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

function renderTabs() {
  const wrap = document.getElementById('symtabs');
  wrap.innerHTML = '';
  for (const s of watching) {
    const b = document.createElement('button');
    b.textContent = s;
    b.className = s === activeSymbol ? 'active' : '';
    b.onclick = () => { activeSymbol = s; renderTabs(); refreshChart(); };
    wrap.appendChild(b);
  }
  if (!watching.length) wrap.innerHTML = '<span class="empty">No symbols being watched yet — waiting on scanner.</span>';
}

async function refreshStatus() {
  const s = await j('/api/status');
  const ibkr = document.getElementById('ibkr-pill');
  ibkr.textContent = s.ibkr_connected ? 'IBKR connected' : 'IBKR offline';
  ibkr.className = 'pill ' + (s.ibkr_connected ? 'on' : 'off');
  const auto = document.getElementById('auto-pill');
  auto.textContent = s.auto_trade_enabled ? 'AUTO ON' : 'AUTO OFF';
  auto.className = 'pill ' + (s.auto_trade_enabled ? 'on' : 'off');
  document.getElementById('risk-pill').textContent =
    `Trades today: ${s.trades_today} · Realized: $${s.realized_pnl_today}` +
    (s.can_trade ? '' : ` · BLOCKED: ${s.blocked_reason}`);
  watching = s.watching;
  if (!activeSymbol && watching.length) { activeSymbol = watching[0]; refreshChart(); }
  renderTabs();
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

const EDITABLE = ['auto_trade_enabled', 'auto_trade_threshold', 'max_trades_per_day',
                  'max_daily_loss', 'risk_per_trade', 'max_position_size'];

async function refreshSettings() {
  const s = await j('/api/settings');
  document.getElementById('settings').innerHTML = EDITABLE.map(k => {
    const v = s[k];
    const input = typeof v === 'boolean'
      ? `<input type="checkbox" id="set-${k}" ${v ? 'checked' : ''}>`
      : `<input type="number" id="set-${k}" value="${v}">`;
    return `<div class="settings-row"><span>${k.replaceAll('_', ' ')}</span>${input}</div>`;
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
  refreshStatus();
}

async function approve(id) { await j(`/api/signals/${id}/approve`, { method: 'POST' }); refreshAll(); }
async function ignore(id)  { await j(`/api/signals/${id}/ignore`,  { method: 'POST' }); refreshSignals(); }
async function closeTrade(id) { await j(`/api/trades/${id}/close`, { method: 'POST' }); refreshAll(); }
async function disableAuto() { await j('/api/automation/disable', { method: 'POST' }); refreshStatus(); refreshSettings(); }

function refreshAll() {
  refreshStatus(); refreshSignals(); refreshTrades(); refreshPnl();
}

initChart();
refreshAll();
refreshSettings();
setInterval(refreshAll, 10000);
setInterval(refreshChart, 30000);
