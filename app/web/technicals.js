'use strict';

const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const price = value => Number.isFinite(value) ? value.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:value < 1 ? 4 : 2}) : '--';
const signed = value => Number.isFinite(value) ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : '--';
const state = {items:[], visible:[], universe:[], defaults:[], symbol:'', years:1, direction:'all', chartData:null, earnings:[], generation:0, scanGeneration:0, controller:null,
  anchor:'swing_high', anchorDate:'', reviewActive:false, review:null, reviewDate:'', savedPicks:{}, savedOnly:false};
let chart, candles, volume, earningsSeries, avwapSeries;
const averages = {};
const chartCache = new Map();
let planLines = [];
let refreshing = false;
let refreshGeneration = 0;

function renderTradePlan(plan) {
  planLines.forEach(line => candles?.removePriceLine(line));
  planLines = [];
  $('plan-status').textContent = plan ? `${plan.direction || ''} / ${plan.status}${plan.provisional ? ' / provisional' : ''}` : 'No plan available';
  if (!plan) { $('trade-plan').textContent = ''; return; }
  const levels = plan.entry ? `<div class="plan-levels"><div><span>Entry trigger</span><strong>$${price(plan.entry)}</strong></div><div><span>Stop loss</span><strong class="negative">$${price(plan.stop)}</strong></div><div><span>2R objective</span><strong>$${price(plan.target)}</strong></div><div><span>Risk / share</span><strong>$${price(plan.risk_per_share)}</strong><span>${plan.risk_pct}% / ${plan.reward_risk}R</span></div></div>` : '';
  const notes = [...(plan.reasons || []), plan.entry_rule, plan.stop_rule, plan.target_rule,
    plan.nearby_level ? `Nearby price structure $${price(plan.nearby_level)} (${plan.room_r}R away).` : '',
    plan.validity, ...(plan.warnings || [])].filter(Boolean);
  $('trade-plan').innerHTML = levels + `<ul class="plan-notes">${notes.map(n => `<li>${escapeHtml(n)}</li>`).join('')}</ul>`;
  if (candles && plan.entry) {
    for (const [key, title, color] of [['entry','Plan entry','#7ab9ee'],['stop','Plan stop','#f47b7d'],['target','2R objective','#54c8a0']]) {
      planLines.push(candles.createPriceLine({price:plan[key],color,lineWidth:1,lineStyle:2,axisLabelVisible:true,title}));
    }
  }
}

function saved(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function persist(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Private browsing can disable storage. */ }
}
async function request(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Request failed. Check the ticker and try again.');
  return data;
}

function filteredItems(items, direction, kind, minimum, recentOnly) {
  return items.filter(item => (!recentOnly || item.eligible) && item.score >= minimum &&
    (direction === 'all' || item.direction === direction) &&
    (kind === 'discovery' ? item.discovery?.above_52w || item.discovery?.above_history : kind === 'all' || (item.signals || []).some(e => e.held && e.direction === item.direction &&
      (direction === 'all' || e.direction === direction) && (kind === 'range' ? e.kind.startsWith('range') : e.kind === kind))));
}

function renderRankings() {
  const source = state.savedOnly ? Object.entries(state.savedPicks).map(([symbol,item]) => state.items.find(i => i.symbol === symbol) || item) : state.items;
  state.visible = filteredItems(source, state.direction, $('signal-filter').value,
    Number($('min-score').value) || 0, state.savedOnly ? false : $('recent-only').checked).sort((a,b) => b.score - a.score);
  $('rankings').innerHTML = state.visible.map(item => `<button class="rank-row ${item.symbol === state.symbol ? 'selected' : ''}" data-symbol="${escapeHtml(item.symbol)}" aria-label="Review ${escapeHtml(item.symbol)}">
    <span><b>${escapeHtml(item.symbol)}</b><small>${escapeHtml(item.trigger?.label || (item.history_bars < 220 ? 'Insufficient history' : 'No recent held signal'))}${item.trigger ? ` &middot; ${item.trigger.age}d` : ''}</small><small>${escapeHtml(item.as_of || 'No bars')}${item.provisional ? ' &middot; provisional' : ' &middot; prior sessions'}</small>${state.savedPicks[item.symbol] ? '<small class="saved-label">Saved</small>' : ''}</span>
    <span class="score ${item.direction}">${item.score.toFixed(0)}</span><span class="${item.change_pct >= 0 ? 'positive' : 'negative'}">${signed(item.change_pct)}</span></button>`).join('') || '<div class="empty">No charts match these filters.</div>';
  $('result-count').textContent = `${state.visible.length} / ${state.items.length} charts`;
  $('universe-count').textContent = `${state.universe.length} symbols`;
  const navigation = navigationSymbols();
  const index = navigation.indexOf(state.symbol);
  $('previous').disabled = index <= 0;
  $('next').disabled = index >= navigation.length - 1 || !navigation.length;
  $('save-pick').setAttribute('aria-pressed', Boolean(state.savedPicks[state.symbol]));
  $('save-pick').disabled = !state.chartData;
  $('start-review').disabled = !state.visible.some(i => state.items.includes(i) && i.eligible && i.score > 0);
  renderReview();
}

function navigationSymbols() {
  return state.reviewActive ? state.review.symbols : state.visible.map(i => i.symbol);
}

function reviewQueue(items, count) {
  return items.filter(i => i.eligible && i.score > 0).slice().sort((a,b) => b.score - a.score).slice(0,count).map(i => i.symbol);
}

function renderReview() {
  $('review-session').hidden = !state.reviewActive;
  document.body.classList.toggle('reviewing', state.reviewActive);
  if (!state.reviewActive) return;
  const {symbols,decisions,date} = state.review;
  const complete = symbols.filter(s => decisions[s]).length;
  const index = symbols.indexOf(state.symbol);
  $('review-progress').textContent = complete === symbols.length ? `Review complete · ${complete}/${symbols.length}` : `${Math.max(0,index + 1)} / ${symbols.length} · ${complete} reviewed`;
  $('review-date').textContent = `${date} · ${symbols.filter(s => decisions[s] === 'saved').length} saved`;
  for (const id of ['review-done','review-save','review-pass']) $(id).disabled = !state.chartData || index < 0;
}

function startReview() {
  const symbols = reviewQueue(state.visible.filter(i => state.items.includes(i)), Number($('review-limit').value));
  if (!symbols.length) return;
  const date = state.reviewDate || state.items.find(i => i.as_of)?.as_of || '';
  const previous = saved('kenny.daily.review',{});
  const decisions = previous.date === date && previous.decisions && typeof previous.decisions === 'object' ? previous.decisions : {};
  state.review = {date,symbols,decisions};
  state.reviewActive = true;
  persist('kenny.daily.review',state.review);
  selectSymbol(symbols.find(s => !decisions[s]) || symbols[0]);
}

function savePick() {
  if (!state.chartData) return;
  if (state.savedPicks[state.symbol]) delete state.savedPicks[state.symbol];
  else state.savedPicks[state.symbol] = state.chartData.summary;
  persist('kenny.daily.picks',state.savedPicks);
  renderRankings();
}

function recordReview(decision) {
  if (!state.reviewActive || !state.chartData || !state.review.symbols.includes(state.symbol)) return;
  state.review.decisions[state.symbol] = decision;
  if (decision === 'saved') {
    state.savedPicks[state.symbol] = state.chartData.summary;
    persist('kenny.daily.picks',state.savedPicks);
  }
  persist('kenny.daily.review',state.review);
  const symbols = state.review.symbols;
  const index = symbols.indexOf(state.symbol);
  const remaining = [...symbols.slice(index + 1),...symbols.slice(0,index)].find(s => !state.review.decisions[s]);
  renderRankings();
  if (remaining) selectSymbol(remaining);
}

function cachedChart(symbol) {
  const params = new URLSearchParams({years:String(state.years),anchor:state.anchor});
  if (state.anchor === 'custom') params.set('anchor_date',state.anchorDate);
  const url = `/api/technicals/chart/${encodeURIComponent(symbol)}?${params}`;
  const existing = chartCache.get(url);
  if (existing && Date.now() - existing.at < 30000) return existing.promise;
  const promise = request(url).catch(error => { if (chartCache.get(url)?.promise === promise) chartCache.delete(url); throw error; });
  chartCache.set(url,{promise,at:Date.now()});
  while (chartCache.size > 40) chartCache.delete(chartCache.keys().next().value);
  return promise;
}

function prefetchNext() {
  const symbols = navigationSymbols();
  const index = symbols.indexOf(state.symbol);
  if (index >= 0) for (const symbol of symbols.slice(index + 1,index + 3)) cachedChart(symbol).catch(() => {});
}

async function scan({background = false} = {}) {
  if (background && $('rescan').disabled) return;
  chartCache.clear();
  const generation = ++state.scanGeneration;
  $('rescan').disabled = true;
  $('scan-status').classList.remove('error');
  if (!background) $('scan-status').textContent = `Scanning ${state.universe.length} symbols...`;
  renderRankings();
  try {
    const result = await request('/api/technicals/scan', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({symbols:state.universe.join(' ')})});
    if (generation !== state.scanGeneration) return;
    state.items = result.items;
    state.reviewDate = result.review_date || result.items.find(i => i.as_of)?.as_of || '';
    $('scan-status').textContent = `${result.feed.toUpperCase()} feed · ${result.current_day_count || 0}/${result.items.length} with today's provisional candle · Checked ${new Date(result.generated_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    renderRankings();
    if (!state.symbol && state.visible.length) selectSymbol(state.visible[0].symbol);
  } catch (error) {
    if (generation !== state.scanGeneration) return;
    $('scan-status').textContent = `Refresh failed; rankings may be stale. ${error.message}`;
    $('scan-status').classList.add('error');
  } finally {
    if (generation === state.scanGeneration) $('rescan').disabled = false;
  }
  if (generation === state.scanGeneration) await refreshCurrentChart();
}

function drawChartData(data) {
  for (const w of [20,50,200]) averages[w].setData(data.averages[w] || []);
  avwapSeries.setData(data.avwap?.points || []);
  avwapSeries.setMarkers(data.avwap?.anchor?.available && data.avwap.points.some(p => p.time === data.avwap.anchor.date) ? [{time:data.avwap.anchor.date,position:'aboveBar',shape:'square',color:'#f5a07f',text:'Anchor',size:.5}] : []);
  volume.setData(data.bars.map(b => ({time:b.time,value:b.volume,color:b.close >= b.open ? '#54c8a045' : '#f47b7d45'})));
  updateMarkers();
}

async function refreshCurrentChart() {
  if (!state.chartData) return;
  const generation = state.generation;
  const refresh = ++refreshGeneration;
  try {
    const data = await cachedChart(state.symbol);
    if (generation !== state.generation || refresh !== refreshGeneration) return;
    const range = chart?.timeScale().getVisibleLogicalRange();
    state.chartData = data;
    renderSummary(data);
    if (chart && data.bars.length) {
      drawChartData(data);
      if (range) chart.timeScale().setVisibleLogicalRange(range);
    }
  } catch (error) {
    if (generation !== state.generation || refresh !== refreshGeneration) return;
    $('as-of').textContent = `Through ${state.chartData?.summary.as_of || '--'} · Refresh failed; data may be stale`;
    renderTradePlan(null);
    $('plan-status').textContent = 'Unavailable until refresh succeeds';
  }
}

async function refreshDaily() {
  if (document.hidden || refreshing || $('rescan').disabled) return;
  refreshing = true;
  try { await scan({background:true}); } finally { refreshing = false; }
}

function initChart() {
  if (!window.LightweightCharts) {
    $('chart-state').textContent = 'Chart library could not load. Check your connection and reload.';
    return;
  }
  chart = LightweightCharts.createChart($('daily-chart'), {
    layout:{background:{color:'#141617'}, textColor:'#a0aaae', fontFamily:'Segoe UI, sans-serif'},
    grid:{vertLines:{color:'#202527'}, horzLines:{color:'#252a2c'}},
    rightPriceScale:{borderColor:'#34393c', scaleMargins:{top:.1,bottom:.22}},
    timeScale:{borderColor:'#34393c', timeVisible:false, rightOffset:8, minBarSpacing:.05, lockVisibleTimeRangeOnResize:true},
    crosshair:{mode:0}, handleScroll:true, handleScale:true,
  });
  candles = chart.addCandlestickSeries({upColor:'#54c8a0', downColor:'#f47b7d', borderVisible:false, wickUpColor:'#54c8a0', wickDownColor:'#f47b7d'});
  avwapSeries = chart.addLineSeries({color:'#f5a07f',lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:true});
  // A separate invisible series anchors future events on their actual dates, not the last candle.
  earningsSeries = chart.addLineSeries({color:'transparent', lineVisible:false, lastValueVisible:false,
    priceLineVisible:false, crosshairMarkerVisible:false, autoscaleInfoProvider:() => null});
  volume = chart.addHistogramSeries({priceFormat:{type:'volume'}, priceScaleId:'volume', lastValueVisible:false, priceLineVisible:false});
  chart.priceScale('volume').applyOptions({scaleMargins:{top:.83,bottom:0}, visible:false});
  for (const [window, color] of Object.entries({20:'#62c8ee',50:'#edb85e',200:'#c29bef'})) {
    averages[window] = chart.addLineSeries({color,lineWidth:2, priceLineVisible:false, lastValueVisible:false, crosshairMarkerVisible:false});
  }
  new ResizeObserver(entries => {
    const {width,height} = entries[0].contentRect;
    if (width && height) chart.resize(width,height);
  }).observe($('daily-chart'));
  chart.subscribeCrosshairMove(param => {
    if (!param.time || !state.chartData) { $('crosshair-info').textContent = ''; return; }
    const time = typeof param.time === 'string' ? param.time : `${param.time.year}-${String(param.time.month).padStart(2,'0')}-${String(param.time.day).padStart(2,'0')}`;
    const bar = param.seriesData.get(candles);
    const event = state.earnings.filter(e => e.date === time).map(e => `Earnings ${hourLabel(e.hour)}`).join(' · ');
    const avwap = param.seriesData.get(avwapSeries)?.value;
    $('crosshair-info').textContent = `${time}${bar?.close != null ? `  O ${price(bar.open)}  H ${price(bar.high)}  L ${price(bar.low)}  C ${price(bar.close)}` : ''}${avwap ? ` · AVWAP ${price(avwap)}` : ''}${event ? ` · ${event}` : ''}`;
  });
}

function hourLabel(hour) {
  return ({bmo:'before open',amc:'after close',dmh:'during market',unknown:'time unknown'})[hour] || 'time unknown';
}

function chartMarkers(data, earnings, showEvents, showEarnings) {
  const first = data.bars[0]?.time;
  const markers = showEvents ? data.events.filter(e => e.kind.startsWith('ma') || ['price200','avwap','range252'].includes(e.kind)).map(e => ({
    time:e.time, position:e.direction === 'bullish' ? 'belowBar' : 'aboveBar',
    color:e.direction === 'bullish' ? '#54c8a0' : '#f47b7d', shape:e.direction === 'bullish' ? 'arrowUp' : 'arrowDown',
    text:e.label.replace('SMA ','') + (e.provisional ? ' (provisional)' : ''), size:.5,
  })) : [];
  if (showEarnings) for (const e of earnings.filter(e => first && e.date >= first)) {
    markers.push({time:e.date, position:'aboveBar', color:'#edb85e', shape:'circle', text:'E', size:.6});
  }
  return markers.sort((a,b) => a.time.localeCompare(b.time));
}

function updateMarkers() {
  if (!candles || !state.chartData) return;
  const data = state.chartData;
  candles.setData(data.bars);
  candles.setMarkers(chartMarkers(data, [], $('show-events').checked, false));
  const markers = chartMarkers(data, state.earnings, false, $('show-earnings').checked);
  const points = markers.map(marker => {
    const anchor = data.bars.findLast(bar => bar.time <= marker.time) || data.bars[0];
    return {time:marker.time, value:anchor.high};
  });
  earningsSeries.setData(points);
  earningsSeries.setMarkers(markers);
}

function fitChart() {
  if (!chart || !state.chartData?.bars.length) return;
  const bars = state.chartData.bars;
  const next = state.earnings.find(e => e.date > bars.at(-1).time);
  const eventDates = $('show-earnings').checked ? state.earnings.filter(e => e.date >= bars[0].time).map(e => e.date) : [];
  const dates = [...new Set([...bars.map(b => b.time), ...eventDates])].sort();
  const end = $('show-earnings').checked && next ? next.date : bars.at(-1).time;
  chart.timeScale().setVisibleLogicalRange({from:-2,to:dates.indexOf(end) + 6});
}

function renderSummary(data) {
  renderTradePlan(data.trade_plan);
  const summary = data.summary;
  $('chart-symbol').textContent = data.symbol;
  $('last-price').textContent = `$${price(summary.close)}`;
  $('day-change').textContent = signed(summary.change_pct);
  $('day-change').className = summary.change_pct >= 0 ? 'positive' : 'negative';
  const current = data.current_day;
  const checked = current?.fetched_at ? ` · Checked ${new Date(current.fetched_at).toLocaleTimeString()}` : '';
  $('as-of').textContent = `Through ${summary.as_of || '--'} · ${summary.provisional ? 'Today / provisional' : 'Prior sessions'}${checked}`;
  $('as-of').title = current?.trade_at ? `Latest feed trade: ${new Date(current.trade_at).toLocaleString()}. Snapshot check time is not the last trade time.` : 'Last trade timestamp unavailable.';
  for (const w of [20,50,200]) $(`ma${w}-value`).textContent = price(summary.sma?.[w]);
  $('feed-label').textContent = `${data.feed.toUpperCase()} · Split adjusted · ${data.bars.length} daily candles`;
  $('total-score').textContent = `${summary.score.toFixed(1)} / 100`;
  $('total-score').className = summary.direction;
  $('score-context').textContent = `${summary.direction.toUpperCase()} · ${summary.provisional ? 'Provisional score' : summary.eligible ? 'Recent held signal' : 'Not ranked'} · Not a win probability`;
  $('score-breakdown').innerHTML = summary.breakdown.map(row => `<div class="score-row"><div>${escapeHtml(row.label)}<small>${escapeHtml(row.detail)}</small>${row.maximum ? `<div class="score-meter"><span style="width:${Math.min(100,Math.max(0,row.points / row.maximum * 100))}%"></span></div>` : ''}</div><strong class="${row.points < 0 ? 'negative' : ''}">${row.points}${row.maximum ? ` / ${row.maximum}` : ''}</strong></div>`).join('');
  $('risk-flags').innerHTML = summary.warnings.map(w => `<li>${escapeHtml(w)}</li>`).join('') + (data.feed === 'iex' ? '<li>IEX-only volume, not consolidated market liquidity.</li>' : '');
  $('signal-events').innerHTML = summary.signals.slice().reverse().map(e => `<div class="event-row"><time>${e.time}</time><span class="${e.direction}">${escapeHtml(e.label)} ${e.direction === 'bullish' ? 'up' : 'down'}</span><small>${e.provisional ? 'Provisional' : e.held ? 'Held' : 'Failed'}</small></div>`).join('') || '<div class="empty">No crosses or range breaks in the last 10 sessions.</div>';
  const vwap = data.avwap;
  $('avwap-value').textContent = price(vwap?.value);
  $('anchor-info').textContent = vwap?.anchor?.available ? `${vwap.anchor.date} · ${vwap.method}` : vwap?.anchor?.reason || 'Anchored VWAP unavailable';
  $('anchor-info').title = 'A traded-price average, not the cost basis of current holders. Scores always use the confirmed swing-high anchor.';
  const context = [`<span class="${summary.direction}">Score ${summary.score.toFixed(1)} / 100 · ${escapeHtml(summary.direction)}</span>`];
  if (vwap?.value) context.push(`<span class="${vwap.distance_pct >= 0 ? 'positive' : 'negative'}">${escapeHtml(vwap.state)} ${signed(vwap.distance_pct)} · ${escapeHtml(vwap.slope)}</span>`);
  if (summary.discovery) context.push(`<span>${escapeHtml(summary.discovery.state)}${summary.discovery.high_52w ? ` · Prior 52W $${price(summary.discovery.high_52w)}` : ''}</span>`);
  if (summary.next_earnings) context.push(`<span class="caution">Earnings ${escapeHtml(summary.next_earnings.date)}</span>`);
  else context.push('<span class="caution">Upcoming earnings unconfirmed</span>');
  if (vwap?.calendar_status && vwap.calendar_status !== 'available') context.push('<span class="caution">Earnings-anchor calendar incomplete</span>');
  for (const warning of summary.warnings) context.push(`<span class="caution">${escapeHtml(warning)}</span>`);
  if (data.feed === 'iex') context.push('<span class="caution">IEX-only volume</span>');
  $('quick-context').innerHTML = context.join('');
  renderRankings();
}

async function selectSymbol(symbol) {
  symbol = symbol.trim().toUpperCase();
  if (!/^[A-Z]{1,5}(?:[.-][A-Z])?$/.test(symbol)) {
    $('chart-state').hidden = false;
    $('chart-state').textContent = 'Enter a valid ticker symbol.';
    return;
  }
  const generation = ++state.generation;
  state.controller?.abort();
  state.controller = new AbortController();
  const {signal} = state.controller;
  state.symbol = symbol;
  state.chartData = null;
  renderTradePlan(null);
  state.earnings = [];
  $('symbol-input').value = symbol;
  $('chart-symbol').textContent = symbol;
  for (const id of ['last-price','day-change','as-of','crosshair-info','score-breakdown','signal-events','earnings-list','risk-flags','quick-context','avwap-value','anchor-info']) $(id).textContent = '';
  for (const w of [20,50,200]) $(`ma${w}-value`).textContent = '--';
  $('total-score').textContent = '-- / 100';
  $('score-context').textContent = 'Loading...';
  $('earnings-state').textContent = 'Loading earnings...';
  $('chart-state').hidden = false;
  $('chart-state').textContent = 'Loading daily history...';
  persist('kenny.daily.symbol', symbol);
  renderRankings();
  try {
    const data = await cachedChart(symbol);
    if (generation !== state.generation) return;
    state.chartData = data;
    renderSummary(data);
    if (chart && data.bars.length) {
      drawChartData(data);
      fitChart();
      $('chart-state').hidden = true;
      prefetchNext();
    } else {
      $('chart-state').textContent = chart ? 'No candles in this date range.' : 'Chart library unavailable. Reload to retry.';
    }
    const calendar = await request(`/api/technicals/earnings/${encodeURIComponent(symbol)}?years=${state.years}`, {signal});
    if (generation !== state.generation) return;
    state.earnings = calendar.events;
    $('earnings-state').textContent = `Earnings: ${calendar.status} · ${calendar.events.length} dates`;
    $('earnings-state').title = calendar.message;
    const lastDate = data.bars.at(-1)?.time || '';
    const upcoming = calendar.events.filter(e => e.date > lastDate);
    const historical = calendar.events.filter(e => e.date <= lastDate).slice().reverse();
    $('earnings-list').innerHTML = [...upcoming,...historical].map(e => `<div class="event-row"><time>${e.date}</time><span>${escapeHtml(hourLabel(e.hour))}</span><small>${escapeHtml(e.status)}</small></div>`).join('') || `<div class="empty">${escapeHtml(calendar.message)} No dates returned.</div>`;
    if (calendar.status !== 'available') $('risk-flags').insertAdjacentHTML('beforeend', `<li>${escapeHtml(calendar.message)}</li>`);
    updateMarkers();
    fitChart();
  } catch (error) {
    if (generation !== state.generation || error.name === 'AbortError') return;
    if (state.chartData) {
      $('earnings-state').textContent = 'Earnings unavailable';
      $('earnings-list').textContent = error.message;
    } else {
      $('chart-state').hidden = false;
      $('chart-state').textContent = error.message;
      $('score-context').textContent = 'Chart unavailable';
      $('earnings-state').textContent = 'Earnings not loaded';
    }
  }
}

function moveSelection(delta) {
  const symbols = navigationSymbols();
  const i = symbols.indexOf(state.symbol);
  const next = symbols[i + delta];
  if (next) selectSymbol(next);
}

async function init() {
  window.lucide?.createIcons();
  initChart();
  const storedPicks = saved('kenny.daily.picks',{});
  state.savedPicks = storedPicks && typeof storedPicks === 'object' && !Array.isArray(storedPicks) ? storedPicks : {};
  const savedYears = Number(saved('kenny.daily.years',1));
  state.years = [1,2,3,4,5].includes(savedYears) ? savedYears : 1;
  document.querySelectorAll('[data-years]').forEach(button => button.setAttribute('aria-pressed',Number(button.dataset.years) === state.years));
  $('rankings').addEventListener('click', e => { const row = e.target.closest('[data-symbol]'); if (row) selectSymbol(row.dataset.symbol); });
  $('symbol-form').addEventListener('submit', e => { e.preventDefault(); selectSymbol($('symbol-input').value); });
  $('rescan').addEventListener('click', scan);
  $('previous').addEventListener('click', () => moveSelection(-1));
  $('next').addEventListener('click', () => moveSelection(1));
  $('fit-chart').addEventListener('click', fitChart);
  $('start-review').addEventListener('click',startReview);
  $('review-done').addEventListener('click',() => recordReview('reviewed'));
  $('review-save').addEventListener('click',() => recordReview('saved'));
  $('review-pass').addEventListener('click',() => recordReview('passed'));
  $('end-review').addEventListener('click',() => {state.reviewActive=false;renderRankings();});
  $('save-pick').addEventListener('click',savePick);
  $('saved-only').addEventListener('click',() => {state.savedOnly=!state.savedOnly;$('saved-only').setAttribute('aria-pressed',state.savedOnly);renderRankings();});
  $('show-avwap').addEventListener('change',() => avwapSeries?.applyOptions({visible:$('show-avwap').checked}));
  function changeAnchor() {
    state.anchor = $('anchor-mode').value;
    if (state.anchor === 'custom' && !$('anchor-date').value) $('anchor-date').value = state.chartData?.avwap?.anchor?.date || state.chartData?.bars[0]?.time || '';
    state.anchorDate = $('anchor-date').value;
    $('anchor-date').hidden = state.anchor !== 'custom';
    if (state.anchor === 'custom' && !state.anchorDate) {
      $('anchor-info').textContent = 'Choose an anchor date.';
      avwapSeries?.setData([]);
      $('avwap-value').textContent = '--';
      return;
    }
    if (state.symbol) selectSymbol(state.symbol);
  }
  $('anchor-mode').addEventListener('change',changeAnchor);
  $('anchor-date').addEventListener('change',changeAnchor);
  document.addEventListener('keydown',event => {
    if (event.repeat || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.target.closest('input,textarea,select,[contenteditable=true]') || $('universe-dialog').open) return;
    if (event.key === 'ArrowRight') {event.preventDefault();moveSelection(1);}
    if (event.key === 'ArrowLeft') {event.preventDefault();moveSelection(-1);}
    if (state.reviewActive && ['d','s','x'].includes(event.key.toLowerCase())) {
      event.preventDefault();recordReview({d:'reviewed',s:'saved',x:'passed'}[event.key.toLowerCase()]);
    }
  });
  for (const id of ['signal-filter','min-score','recent-only']) $(id).addEventListener('change', renderRankings);
  $('directions').addEventListener('click', e => {
    const button = e.target.closest('[data-direction]'); if (!button) return;
    state.direction = button.dataset.direction;
    document.querySelectorAll('[data-direction]').forEach(b => b.setAttribute('aria-pressed', b === button));
    renderRankings();
  });
  $('years').addEventListener('click', e => {
    const button = e.target.closest('[data-years]'); if (!button) return;
    state.years = Number(button.dataset.years);
    persist('kenny.daily.years',state.years);
    document.querySelectorAll('[data-years]').forEach(b => b.setAttribute('aria-pressed',b === button));
    if (state.symbol) selectSymbol(state.symbol);
  });
  document.querySelectorAll('[data-average]').forEach(input => input.addEventListener('change', () => averages[input.dataset.average]?.applyOptions({visible:input.checked})));
  for (const id of ['show-events','show-earnings']) $(id).addEventListener('change', updateMarkers);
  $('edit-universe').addEventListener('click', () => { $('universe-input').value = state.universe.join(', '); $('universe-error').textContent = ''; $('universe-dialog').showModal(); });
  $('close-universe').addEventListener('click', () => $('universe-dialog').close());
  $('default-universe').addEventListener('click', () => { $('universe-input').value = state.defaults.join(', '); });
  $('universe-form').addEventListener('submit', e => {
    e.preventDefault();
    const symbols = [...new Set($('universe-input').value.trim().toUpperCase().split(/[\s,;]+/))];
    if (!symbols.length || symbols.length > 100 || symbols.some(s => !/^[A-Z]{1,5}(?:[.-][A-Z])?$/.test(s))) {
      $('universe-error').textContent = 'Enter 1 to 100 valid ticker symbols.'; return;
    }
    state.universe = symbols;
    persist('kenny.daily.universe',symbols);
    $('universe-dialog').close();
    scan();
  });
  try {
    const config = await request('/api/technicals/config');
    state.defaults = config.default_symbols;
    const stored = saved('kenny.daily.universe', state.defaults);
    state.universe = Array.isArray(stored) && stored.length && stored.length <= 100 ? stored : state.defaults;
    renderRankings();
    if (!config.history_configured) {
      $('scan-status').textContent = 'Daily history unavailable: configure Alpaca credentials on the server.';
      $('scan-status').classList.add('error');
      $('chart-state').textContent = 'Alpaca daily-history connection is not configured.';
      return;
    }
    const last = saved('kenny.daily.symbol', '');
    if (typeof last === 'string' && last) selectSymbol(last);
    scan();
    setInterval(refreshDaily, 60000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshDaily(); });
  } catch (error) {
    $('scan-status').textContent = error.message;
    $('scan-status').classList.add('error');
  }
}

if (typeof module !== 'undefined') module.exports = {filteredItems, chartMarkers, hourLabel, escapeHtml, reviewQueue};
else init();
