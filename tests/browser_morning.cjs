// Offline preview only. All API responses and order controls are intercepted.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const base = process.env.PREVIEW_URL || 'http://127.0.0.1:8013';

(async () => {
  const browser = await chromium.launch({channel: process.env.BROWSER_CHANNEL || 'msedge', headless:true});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let mode = 'paper';
  let paused = false;
  const mutations = [];
  const status = () => ({execution_mode:mode,paper_verified:mode === 'paper',live_trading_allowed:false,
    broker_connected:true,broker:'alpaca',market_session:'regular',auto_trade_enabled:mode === 'paper',
    scan_russell_1000_only:true,min_market_cap_millions:500,trades_today:0,
    membership:{state:'ready',as_of:'2026-10-15',count:1016},
    scan_coverage:{unmonitored_symbols:[]},scan_source_errors:[],
    scan_filter_errors:paused ? ['Russell membership unavailable; scan paused.'] : []});
  const signal = {id:'fixture',symbol:'AAPL',direction:'LONG',setup:'FAUX_SHOW_BRO',entry:100,stop:99,target:102,confidence:92};
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() !== 'GET') {
      mutations.push(url.pathname);
      return route.fulfill({status:403,json:{detail:'Fixture: orders disabled'}});
    }
    let data = {};
    if (url.pathname === '/api/status') data = status();
    if (url.pathname === '/api/watchlist') data = [];
    if (url.pathname === '/api/signals') data = {pending:paused ? [] : [signal],recent:[]};
    if (url.pathname === '/api/trades') data = {open:[{id:'tracked',symbol:'AAPL',direction:'LONG',status:'PENDING',
      quantity:10,filled_quantity:0,remaining_quantity:0,entry:100,stop:99,target:102}],closed:[],performance:{
      verified_closed:4,pending:1,canceled:2,excluded:1,unresolved:0,persistence:'sqlite',groups:[{
        setup:'FAUX_SHOW_BRO',direction:'LONG',version:'morning-v1',trades:4,win_rate:50,average_r:.4,expectancy:4,pnl:16,sample_label:'Small sample'}]}};
    if (url.pathname === '/api/orders') data = {open:[]};
    if (url.pathname === '/api/settings') data = {auto_trade_threshold:90,max_trades_per_day:2,max_daily_loss:100,risk_per_trade:25,max_position_size:1000};
    return route.fulfill({json:data});
  });
  await page.goto(base,{waitUntil:'networkidle'});
  await page.evaluate(async()=>{await refreshCommandBar();await refreshSignals();});
  assert.equal(await page.locator('#execution-pill').innerText(),'PAPER ONLY');
  assert.equal(await page.locator('#auto-pill').innerText(),'PAPER AUTO ON');
  assert.equal(await page.getByRole('button',{name:'Paper Buy',exact:true}).count(),1);
  assert.match(await page.locator('#scan-health').innerText(),/IWB proxy 2026-10-15/);
  assert.match(await page.locator('#tracking-health').innerText(),/4 verified closed/);
  assert.match(await page.locator('#setup-results').innerText(),/Small sample/);
  assert.match(await page.locator('#positions').innerText(),/0\/10 filled/);
  await page.screenshot({path:path.join(process.env.TEMP,'kenny-technicals-qa','morning-paper-mode.png'),fullPage:true});
  mode = 'research';
  await page.evaluate(async()=>{await refreshCommandBar();await refreshSignals();});
  assert.equal(await page.locator('#execution-pill').innerText(),'RESEARCH');
  assert(await page.locator('#auto-switch').isDisabled());
  assert.equal(await page.getByRole('button',{name:'Paper Buy',exact:true}).count(),0);
  paused = true;
  await page.evaluate(async()=>{await refreshCommandBar();await refreshSignals();});
  assert.match(await page.locator('#pending').innerText(),/Scanner unavailable/);
  assert.match(await page.locator('#scanner-list').innerText(),/scan paused/);
  assert.deepEqual(errors,[]);
  assert.deepEqual(mutations,[]);
  console.log(JSON.stringify({passed:true,checks:['paper-only label','paper order labels','membership provenance','research controls blocked','paused scanner distinct from no setup','no browser errors']}));
  await browser.close();
})().catch(error=>{console.error(error);process.exitCode=1;});
