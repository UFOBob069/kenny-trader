/* VWAP Copilot dashboard */
let chart, candleSeries, volumeSeries, vwapSeries, pdvSeries;
let activeSymbol = null;
let watchItems = [];
let lastStatus = {};
let chartPollTimer = null;

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function toast(msg, ok = true) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = 'toast show ' + (ok ? 'ok' : 'err');
  setTimeout(() => el.classList.remove('show'), ok ? 6000 : 10000);
}

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

function renderChartData(d) {
  candleSeries.setData(d.bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
  volumeSeries.setData(d.bars.map(b => ({ time: b.time, value: b.volume })));
  vwapSeries.setData(d.vwap);
  pdvSeries.setData(d.prior_vwap);
  candleSeries.setMarkers(d.markers || []);
}

async function refreshChart() {
  if (!activeSymbol) return;
  const loading = document.getElementById('chart-loading');
  if (loading) loading.style.display = 'flex';
  try {
    for (let i = 0; i < 40; i++) {
      const d = await j(`/api/chart/${activeSymbol}`);
      if (d.loading) {
        if (loading) loading.textContent = 'Loading chart…';
        await sleep(1500);
        continue;
      }
      if (d.error) {
        if (loading) {
          loading.textContent = d.error;
          loading.style.display = 'flex';
        }
        return;
      }
      if (d.bars?.length) {
        renderChartData(d);
        if (loading) loading.style.display = 'none';
        return;
      }
      await sleep(1500);
    }
    if (loading) loading.textContent = 'Chart timed out — try again';
  } catch (e) {
    if (loading) loading.textContent = 'Chart failed to load';
  }
}

function startChartPoll() {
  if (chartPollTimer) clearInterval(chartPollTimer);
  chartPollTimer = setInterval(refreshChart, 15000);
}

function fmtCap(n) {
  if (n == null) return '—';
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${Math.round(n / 1e6)}M`;
  return `$${Math.round(n)}`;
}

function checkLine(name, c, weight) {
  if (!c) return '';
  const cls = c.ok ? 'ok' : 'no';
  const icon = c.ok ? '✓' : '✗';
  const unit = name === 'gap' ? '%' : name === 'rvol' ? 'x' : '';
  const wt = weight != null ? ` <span class="bd-wt">${weight}%</span>` : '';
  return `<div class="checkline ${cls}">${icon} ${name}${wt}: ${c.value} (need ${c.need}${unit})</div>`;
}

function weightedBarRow(label, weightPct, value, fillClass = '') {
  const v = Math.min(100, Math.max(0, value ?? 0));
  const contrib = (v * weightPct / 100).toFixed(1);
  return `<div class="bd-row">
    <span class="bd-lbl">${label} <span class="bd-wt">${weightPct}%</span></span>
    <div class="bd-bar"><div class="bd-fill ${fillClass}" style="width:${v}%"></div></div>
    <span class="bd-val">${Math.round(v)} <span class="bd-contrib">+${contrib}</span></span>
  </div>`;
}

function scanScoreBlock(checks, total) {
  const gapP = checks?.gap ? Math.min(100, Math.abs(checks.gap.value) / checks.gap.need * 100) : 0;
  const rvolP = checks?.rvol ? Math.min(100, checks.rvol.value / checks.rvol.need * 100) : 0;
  const priceP = checks?.price ? Math.min(100, checks.price.value / checks.price.need * 100) : 0;
  return `<div class="bd-block">
    <div class="bd-title">Scan score breakdown</div>
    ${weightedBarRow('Gap', 40, gapP, 'scan')}
    ${weightedBarRow('RVol', 40, rvolP, 'scan')}
    ${weightedBarRow('Price', 20, priceP, 'scan')}
    <div class="bd-total"><span>Scan total</span><span style="color:var(--green)">${total ?? '—'}</span></div>
  </div>`;
}

function confidenceBlock(b, total) {
  if (!b) return '';
  return `<div class="bd-block">
    <div class="bd-title">Trade confidence breakdown</div>
    ${weightedBarRow('Technical', 45, b.technical)}
    ${weightedBarRow('Fundamental', 25, b.fundamental)}
    ${weightedBarRow('AI', 30, b.ai)}
    <div class="bd-total"><span>Confidence</span><span style="color:var(--blue)">${total ?? b.total}%</span></div>
  </div>`;
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
      <span style="margin-left:auto;text-align:right">
        <span style="font-size:10px;color:var(--muted);text-transform:uppercase">Scan score</span><br>
        <span style="color:var(--green);font-weight:600;font-size:18px">${d.score}</span>
      </span>
    </div>
    ${scanScoreBlock(d.checks, d.score)}
    <div class="detail-grid">
      <div class="detail-cell"><div class="lbl">Market Cap</div><div class="val">${fmtCap(d.market_cap_usd)}</div></div>
      <div class="detail-cell"><div class="lbl">Price</div><div class="val">${d.price != null ? '$' + d.price : '—'}</div></div>
      <div class="detail-cell"><div class="lbl">Gap</div><div class="val">${d.gap_pct != null ? (d.gap_pct > 0 ? '+' : '') + d.gap_pct + '%' : '—'}</div></div>
      <div class="detail-cell"><div class="lbl">Rel Volume</div><div class="val">${d.relative_volume != null ? d.relative_volume + 'x' : '—'}</div></div>
    </div>
    ${checkLine('gap', d.checks?.gap, 40)}
    ${checkLine('rvol', d.checks?.rvol, 40)}
    ${checkLine('price', d.checks?.price, 20)}
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
    empty.textContent = 'No symbols match today’s scan — check FINNHUB_API_KEY or lower the market-cap filter.';
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
      <td class="scan-score" title="Scan: gap 40% · rvol 40% · price 20%">${w.score}</td>
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
  lastStatus = s;
  const pill = document.getElementById('broker-pill');
  const label = (s.broker || 'broker').toUpperCase();
  pill.textContent = s.broker_connected ? `${label} connected` : `${label} offline`;
  pill.className = 'pill ' + (s.broker_connected ? 'on' : 'off');
  const auto = document.getElementById('auto-pill');
  auto.textContent = s.auto_trade_enabled ? 'AUTO ON' : 'AUTO OFF';
  auto.className = 'pill ' + (s.auto_trade_enabled ? 'on' : 'off');
  const autoSwitch = document.getElementById('auto-switch');
  if (autoSwitch) {
    autoSwitch.className = 'switch' + (s.auto_trade_enabled ? ' on' : '');
    autoSwitch.setAttribute('aria-checked', s.auto_trade_enabled ? 'true' : 'false');
  }
  const uniN = Object.keys(s.scan_universe || {}).length;
  const qualN = watchItems.filter(w => w.qualified).length;
  renderCapSelector(s.min_market_cap_millions);
  document.getElementById('risk-pill').textContent =
    `${s.market_session || '—'} · List: ${uniN} · Ready: ${qualN} · Charts: ${(s.watching || []).length}` +
    ` · Trades: ${s.trades_today} · P&L: $${s.realized_pnl_today}` +
    (s.can_trade ? '' : ` · BLOCKED: ${s.blocked_reason}`);
}

const CAP_PRESETS = [
  { label: 'All', millions: 0 },
  { label: '$300M', millions: 300 },
  { label: '$500M', millions: 500 },
  { label: '$1B', millions: 1000 },
  { label: '$2B', millions: 2000 },
  { label: '$5B', millions: 5000 },
];

function renderCapSelector(activeMillions) {
  const el = document.getElementById('cap-select');
  if (!el) return;
  el.innerHTML = '<span class="lbl">Min cap</span>' + CAP_PRESETS.map(p => {
    const active = p.millions === activeMillions ? 'active' : '';
    return `<button class="${active}" onclick="setMarketCap(${p.millions})">${p.label}</button>`;
  }).join('');
}

async function setMarketCap(millions) {
  await j('/api/filters/market-cap', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ millions }),
  });
  refreshAll();
}

function signalCard(s) {
  const reasons = (s.breakdown?.reasons || []).slice(0, 4).join(' · ');
  const thresh = lastStatus.auto_trade_threshold ?? 90;
  const autoHint = lastStatus.auto_trade_enabled && s.confidence < thresh
    ? `<div class="auto-hint">Auto skipped — needs ${thresh}%+ trade confidence</div>`
    : '';
  const b = s.breakdown;
  return `<div class="signal">
    <div class="head">
      <span><span class="sym-link" onclick="selectSymbol('${s.symbol}')">${s.symbol}</span>
        <span style="color:${s.direction === 'LONG' ? 'var(--green)' : 'var(--red)'}">${s.direction}</span></span>
      <span class="conf"><span class="conf-lbl">Trade confidence</span>${s.confidence}%</span>
    </div>
    ${confidenceBlock(b, s.confidence)}
    <div class="levels">
      <span>Entry ${s.entry}</span><span>Stop ${s.stop}</span><span>Target ${s.target}</span>
    </div>
    <div class="reasons">${s.setup.replaceAll('_', ' ')}${reasons ? ' — ' + reasons : ''}</div>
    ${autoHint}
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

async function refreshOrders() {
  const d = await j('/api/orders');
  const tbody = document.querySelector('#pending-orders tbody');
  const empty = document.getElementById('orders-empty');
  const rows = d.open || [];
  if (!rows.length) {
    tbody.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';
  tbody.innerHTML = rows.map(o => {
    const px = o.price != null ? `$${o.price}` : '—';
    const qty = o.filled_qty > 0 && o.filled_qty < o.qty
      ? `${o.filled_qty}/${o.qty}` : o.qty;
    return `<tr>
      <td><strong>${o.symbol}</strong></td>
      <td>${o.side}</td>
      <td>${qty}</td>
      <td>${o.type}${o.order_class ? ' · ' + o.order_class : ''}</td>
      <td>${px}</td>
      <td>${o.status}</td>
    </tr>`;
  }).join('');
}

async function refreshTrades() {
  const d = await j('/api/trades');
  const tbody = document.querySelector('#open-trades tbody');
  document.getElementById('open-empty').style.display = d.open.length ? 'none' : 'block';
  tbody.innerHTML = d.open.map(t => {
    const pnl = t.unrealized_pnl ?? 0;
    const state = t.pending_exits ? ' <span class="badge no">entry pending</span>' : '';
    return `<tr>
      <td>${t.symbol}${state}</td><td>${t.direction}</td><td>${t.quantity}</td>
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
  auto_trade_threshold: 'auto trade threshold',
  max_trades_per_day: 'max trades per day',
  max_daily_loss: 'max daily loss',
  risk_per_trade: 'risk per trade',
  max_position_size: 'max position size',
};

const EDITABLE = [
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
      : `<input type="number" id="set-${k}" value="${v}">`;
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

async function approve(id) {
  const res = await j(`/api/signals/${id}/approve`, { method: 'POST' });
  if (res.ok) toast(res.message || `Order placed (${res.trade_id})`, true);
  else toast(res.error || 'Order failed — check Railway logs', false);
  refreshAll();
}
async function ignore(id)  { await j(`/api/signals/${id}/ignore`,  { method: 'POST' }); refreshSignals(); }
async function closeTrade(id) { await j(`/api/trades/${id}/close`, { method: 'POST' }); refreshAll(); }
async function toggleAuto() {
  await j('/api/automation/toggle', { method: 'POST' });
  await refreshStatus();
  toast(lastStatus.auto_trade_enabled ? 'Auto-trade ON' : 'Auto-trade OFF', true);
}

async function refreshAll() {
  await refreshWatchlist();
  await refreshStatus();
  refreshSignals();
  refreshOrders();
  refreshTrades();
  refreshPnl();
}

initChart();
refreshAll();
refreshSettings();
startChartPoll();
setInterval(refreshAll, 10000);
