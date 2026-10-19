'use strict';

function initTechnicalAlerts({request, escapeHtml:esc, selectSymbol, universe}) {
  const el = id => document.getElementById(id);
  let data = null, formRevision = 0, busy = false, pending = null;
  const json = (method, body) => ({method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});

  function render(result) {
    data = result;
    el('alert-count').textContent = result.unread;
    const enabled = result.config.enabled;
    el('alert-monitor-status').textContent = result.last_error ? 'Monitor needs attention' : !enabled ? 'Monitoring paused' :
      !result.worker_running ? 'Background monitor offline' : `${result.config.symbols.split(' ').length} tickers monitored`;
    el('alert-detail-status').textContent = [enabled ? 'Monitoring enabled' : 'Monitoring paused',
      result.worker_running ? 'Server checks every 60s' : 'Background monitor offline; manual checks only',
      result.last_checked ? `Last check ${new Date(result.last_checked).toLocaleString()}` : 'Awaiting first check',
      result.last_error || ''].join(' · ');
    el('alert-coverage').innerHTML = result.coverage.map(row => `<div class="alert-coverage-row"><b>${esc(row.symbol)}</b><span>${esc(row.status)}${Number.isFinite(row.score) ? ` · ${row.score.toFixed(1)}` : ''}</span></div>`).join('') || '<div class="empty">No check results yet.</div>';
    el('alert-feed').innerHTML = result.alerts.map(alert => `<article class="technical-alert ${alert.read ? '' : 'unread'}">
      <div class="alert-row-head"><button type="button" data-alert-symbol="${esc(alert.symbol)}" data-alert-id="${esc(alert.id)}" aria-label="Open ${esc(alert.symbol)} alert chart">${esc(alert.symbol)}</button><strong class="${alert.direction === 'bullish' ? 'bullish' : 'bearish'}">${esc(alert.action)} setup</strong><strong>${Number(alert.score).toFixed(1)} / 100</strong><span>${esc(alert.phase)}</span></div>
      <div class="alert-reason">${esc(alert.trigger.label)} · Trigger ${esc(alert.trigger.time)} · ${esc(alert.status)}</div>
      <div class="alert-meta">Observed ${esc(new Date(alert.created_at).toLocaleString())} · Data ${esc(alert.as_of)} · $${Number(alert.price).toFixed(2)}</div>
      <details><summary>Signal evidence and risks</summary><ul>${(alert.breakdown || []).filter(row => row.points).map(row => `<li>${esc(row.label)}: ${esc(row.points)}${row.maximum ? ` / ${esc(row.maximum)}` : ''}</li>`).join('')}${(alert.warnings || []).map(w => `<li>${esc(w)}</li>`).join('')}</ul><span>${esc(alert.score_version)} · Research snapshot, not an order</span></details>
    </article>`).join('') || '<div class="empty">No alerts recorded.</div>';
    el('read-alerts').disabled = !result.unread || busy;
    el('check-alerts').disabled = !enabled || busy;
  }

  function fillForm() {
    if (!data) return;
    const config = data.config;
    el('alert-symbols').value = config.symbols;
    el('alert-minimum').value = config.minimum_score;
    el('alert-direction').value = config.direction;
    el('alert-mode').value = config.mode;
    el('alert-enabled').checked = config.enabled;
    formRevision = data.revision;
    el('alerts-fields').disabled = false;
  }

  async function perform(operation) {
    if (busy) return false;
    busy = true;
    el('save-alerts').disabled = el('check-alerts').disabled = el('read-alerts').disabled = true;
    el('alert-error').textContent = '';
    try { render(await operation()); return true; }
    catch (error) {
      el('alert-error').textContent = error.message;
      el('alert-monitor-status').textContent = 'Alerts unavailable; last results may be stale';
      return false;
    } finally {
      busy = false;
      el('save-alerts').disabled = false;
      el('check-alerts').disabled = !data?.config.enabled;
      el('read-alerts').disabled = !data?.unread;
    }
  }

  async function refresh() {
    if (pending) return pending;
    pending = perform(() => request('/api/technicals/alerts'));
    try { return await pending; } finally { pending = null; }
  }
  el('open-alerts').addEventListener('click', async () => {
    el('alerts-dialog').showModal();
    el('alerts-fields').disabled = true;
    if (await refresh()) fillForm();
  });
  el('close-alerts').addEventListener('click', () => el('alerts-dialog').close());
  el('alert-use-universe').addEventListener('click', () => { el('alert-symbols').value = universe().join(', '); });
  el('alerts-form').addEventListener('submit', async event => {
    event.preventDefault();
    const payload = {symbols:el('alert-symbols').value, minimum_score:Number(el('alert-minimum').value),
      direction:el('alert-direction').value, mode:el('alert-mode').value, enabled:el('alert-enabled').checked, revision:formRevision};
    if (payload.enabled && !payload.symbols.trim()) { el('alert-error').textContent = 'Add at least one ticker before enabling alerts.'; return; }
    if (await perform(() => request('/api/technicals/alerts',json('PUT',payload)))) {
      fillForm();
      if (data.config.enabled) await perform(() => request('/api/technicals/alerts/check',{method:'POST'}));
    }
  });
  el('check-alerts').addEventListener('click', () => perform(() => request('/api/technicals/alerts/check',{method:'POST'})));
  el('read-alerts').addEventListener('click', () => perform(() => request('/api/technicals/alerts/read',json('POST',{ids:data.alerts.filter(a => !a.read).map(a => a.id)}))));
  el('alert-feed').addEventListener('click', async event => {
    const button = event.target.closest('[data-alert-symbol]');
    if (!button) return;
    const symbol = button.dataset.alertSymbol, id = button.dataset.alertId;
    el('alerts-dialog').close();
    selectSymbol(symbol);
    await perform(() => request('/api/technicals/alerts/read',json('POST',{ids:[id]})));
  });
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); },60000);
}
