'use strict';

function parseWatchlist(text) {
  const symbols = [...new Set(text.trim().toUpperCase().split(/[\s,;]+/).filter(Boolean))];
  if (symbols.length > 100 || symbols.some(s => !/^[A-Z]{1,5}(?:[.-][A-Z])?$/.test(s))) {
    throw new Error('Enter up to 100 valid tickers separated by spaces or commas.');
  }
  return symbols;
}

function watchlistVerdict(item) {
  const chart = item?.chart_assessment;
  if (!chart?.available || !Number.isFinite(chart.score)) {
    return {action:'Unavailable', tone:'muted', score:null, label:'Score', reason:chart?.reason || 'No current assessment.'};
  }
  const setup = item.eligible && Number.isFinite(item.score);
  const score = setup ? item.score : chart.score;
  const label = setup ? 'Setup' : 'Chart';
  const plan = item.readiness;
  const side = item.direction;
  if (item.current_day?.status === 'unavailable' || (item.warnings || []).some(w => /stale daily history|current-day data missing/i.test(w))) {
    return {action:'Unavailable', tone:'muted', score:null, label:'Score', reason:'Current data not verified. Refresh before acting.'};
  }
  if (setup && plan?.status === 'conditional' && ['bullish','bearish'].includes(side)) {
    return {action:side === 'bullish' ? 'Buy' : 'Sell', tone:side,
      score, label, reason:`Conditional ${item.trigger?.label || 'setup'}${item.provisional ? ' / provisional' : ''}`};
  }
  const reasons = plan?.reasons?.join(' ');
  if (!plan || (plan.status === 'unavailable' && item.trigger)) {
    return {action:'Unavailable', tone:'muted', score, label, reason:reasons || 'Plan not verified.'};
  }
  return {action:'Hold', tone:'hold', score, label,
    reason:reasons || 'No qualifying recent trigger; wait for a setup.'};
}

function initTechnicalWatchlist({request, escapeHtml:esc, selectSymbol, currentSymbol}) {
  const el = id => document.getElementById(id);
  const key = 'kenny.daily.pinned.v1';
  let symbols = [], rows = [], generation = 0, controller, busy = false, checked = 0;
  let problem = '', editing = false;
  new ResizeObserver(entries => {
    document.documentElement.style.setProperty('--pinned-height', `${entries[0].target.getBoundingClientRect().height}px`);
  }).observe(document.querySelector('.pinned-watchlist'));
  try {
    const stored = JSON.parse(localStorage.getItem(key) || '[]');
    if (!Array.isArray(stored) || stored.some(s => typeof s !== 'string')) throw new Error();
    symbols = parseWatchlist(stored.join(' '));
  } catch { problem = 'Saved watchlist could not be read. Edit the list to replace it.'; }

  function render() {
    const stale = checked && Date.now() - checked > 120000;
    el('watchlist-status').textContent = problem || (busy ? 'Updating...' : symbols.length ?
      `${symbols.length} pinned${checked ? ` · Checked ${new Date(checked).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}` : ''}${stale ? ' · Refresh overdue' : ''}` : 'No pinned stocks');
    el('refresh-watchlist').disabled = busy || !symbols.length;
    el('pinned-tickers').innerHTML = symbols.map(symbol => {
      const item = stale || problem ? null : rows.find(row => row.symbol === symbol);
      const v = watchlistVerdict(item);
      const reason = problem || (stale ? 'Refresh overdue; action not verified.' : item ? v.reason : busy ? 'Loading current assessment...' : 'No data returned.');
      return `<button class="pinned-ticker" data-pinned-symbol="${esc(symbol)}" title="${esc(reason)}" aria-label="Open ${esc(symbol)} chart">
        <span class="pinned-head"><b>${esc(symbol)}</b><strong class="${v.tone}">${v.action}</strong></span>
        <span class="pinned-score">${v.label} <b>${v.score == null ? '--' : v.score.toFixed(1)} / 100</b></span>
        <span class="pinned-reason">${esc(reason)}</span>
        <small>${esc(item?.as_of || 'Awaiting data')}${item?.provisional ? ' · Provisional' : item ? ' · Prior close' : ''}</small>
      </button>`;
    }).join('');
  }

  async function refresh() {
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal, id = ++generation;
    if (!symbols.length) { rows = []; busy = false; checked = 0; render(); return; }
    busy = true; problem = ''; render();
    const timeout = setTimeout(() => controller?.signal === signal && controller.abort(), 45000);
    try {
      const result = await request('/api/technicals/scan', {method:'POST', signal,
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbols:symbols.join(' ')})});
      if (id !== generation) return;
      if (!Array.isArray(result.items)) throw new Error('Watchlist response unavailable.');
      rows = result.items; checked = Date.now();
    } catch (error) {
      if (id !== generation) return;
      rows = []; checked = 0;
      problem = error.name === 'AbortError' ? 'Watchlist refresh timed out. Retry.' : error.message;
    } finally {
      clearTimeout(timeout);
      if (id === generation) { busy = false; render(); }
    }
  }

  function save(next) {
    try { localStorage.setItem(key, JSON.stringify(next)); }
    catch { throw new Error('Browser storage unavailable; watchlist was not saved.'); }
    symbols = next; rows = []; checked = 0;
    refresh();
  }

  el('edit-watchlist').onclick = () => {
    el('watchlist-input').value = symbols.join(', ');
    el('watchlist-error').textContent = '';
    editing = true; el('watchlist-dialog').showModal();
  };
  el('close-watchlist').onclick = () => el('watchlist-dialog').close();
  el('watchlist-dialog').addEventListener('close', () => { editing = false; });
  el('watchlist-form').onsubmit = event => {
    event.preventDefault();
    try { save(parseWatchlist(el('watchlist-input').value)); el('watchlist-dialog').close(); }
    catch(error) { el('watchlist-error').textContent = error.message; }
  };
  el('pin-current').onclick = () => {
    const symbol = currentSymbol();
    if (!symbol) { problem = 'Open a chart to pin its ticker.'; render(); return; }
    try { save(parseWatchlist([...symbols, symbol].join(' '))); }
    catch(error) { problem = error.message; render(); }
  };
  el('refresh-watchlist').onclick = refresh;
  el('pinned-tickers').onclick = event => {
    const symbol = event.target.closest('[data-pinned-symbol]')?.dataset.pinnedSymbol;
    if (symbol) selectSymbol(symbol);
  };
  window.addEventListener('storage', event => {
    if (event.key !== key || editing) return;
    try {
      const data = JSON.parse(event.newValue || '[]');
      if (!Array.isArray(data)) throw new Error();
      symbols = parseWatchlist(data.join(' ')); rows = []; checked = 0; refresh();
    } catch { problem = 'Watchlist changed but could not be read. Reload the page.'; render(); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !busy) refresh(); });
  setInterval(() => {
    render();
    if (!document.hidden && !busy && symbols.length) refresh();
  }, 60000);
  render();
  if (symbols.length) refresh();
}

if (typeof module !== 'undefined') module.exports = {parseWatchlist, watchlistVerdict};
