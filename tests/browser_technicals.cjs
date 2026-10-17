// Run against an offline preview; all market responses below are synthetic test fixtures.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.PREVIEW_URL || 'http://127.0.0.1:8012';
const output = process.env.SCREENSHOT_DIR || path.join(process.env.TEMP, 'kenny-technicals-qa');

function fixture(symbol, years, anchorMode='swing_high', anchorDate='') {
  const bars = [];
  for (let i=0; i<1600; i++) {
    const date = new Date(Date.UTC(2020,8,1+i));
    if ([0,6].includes(date.getUTCDay())) continue;
    const close = 70+i*.065+8*Math.sin(i/51)+3*Math.sin(i/13);
    const open = close+1.2*Math.sin(i/3);
    bars.push({time:date.toISOString().slice(0,10),open,high:Math.max(close,open)+2,low:Math.min(close,open)-2,close,volume:2000000+Math.sin(i)*900000});
  }
  const count = Math.min(bars.length,years*252);
  const visible = bars.slice(-count);
  const averages = {};
  for (const w of [20,50,200]) {
    averages[w] = visible.flatMap(bar => {
      const index = bars.indexOf(bar);
      return index >= w-1 ? [{time:bar.time,value:bars.slice(index-w+1,index+1).reduce((s,b)=>s+b.close,0)/w}] : [];
    });
  }
  const direction = symbol === 'MSFT' ? 'bearish' : 'bullish';
  const event = {time:visible.at(-5).time,kind:'ma20_50',label:'SMA 20 / 50',direction,held:true,age:4};
  const summary = {symbol,eligible:true,direction,score:symbol === 'MSFT' ? 64 : 78.5,as_of:visible.at(-1).time,
    close:visible.at(-1).close,change_pct:direction === 'bullish' ? 2.34 : -1.54,history_bars:bars.length,
    sma:Object.fromEntries(Object.entries(averages).map(([w,a])=>[w,a.at(-1).value])),trigger:event,signals:[event],
    warnings:['Synthetic browser test fixture; not market data.'],
    breakdown:[['Recent held trigger',25,30,'SMA 20 / 50'],['Trend alignment + slope',25,25,'Price / 20 / 50 / 200'],
      ['Trigger-day volume',18,20,'1.9x prior 20 sessions'],['63-session strength vs SPY',10.5,15,'7 percentage points'],
      ['SPY trend agreement',10,10,'Price / 200 and 50 / 200'],['Earnings within 7 days',-10,0,'Scheduled date']]
      .map(([label,points,maximum,detail])=>({label,points,maximum,detail}))};
  const start = anchorMode === 'custom' && anchorDate ? anchorDate : visible.at(-150).time;
  let pv=0,v=0;
  const points = visible.filter(b=>b.time>=start).map(b=>{pv+=(b.high+b.low+b.close)/3*b.volume;v+=b.volume;return {time:b.time,value:pv/v};});
  const avwap = {anchor:{available:true,mode:anchorMode,date:start,label:anchorMode},method:'Daily HLC3 estimate',
    value:points.at(-1).value,distance_pct:2.5,slope:'rising',state:'Above anchored average',points};
  summary.avwap = {...avwap,points:undefined};
  summary.discovery = {state:'Inside prior range',above_52w:false,above_history:false,high_52w:180};
  return {symbol,years,bars:visible,averages,events:[event],summary,avwap,feed:'sip',adjustment:'split',interval:'1D'};
}

(async () => {
  fs.mkdirSync(output,{recursive:true});
  const browser = await chromium.launch({headless:true, ...(process.env.BROWSER_CHANNEL ? {channel:process.env.BROWSER_CHANNEL} : {})});
  const page = await browser.newPage({viewport:{width:1440,height:1050}});
  const errors = [];
  page.on('pageerror',error=>errors.push(error.message));
  // First verify the real server's unconfigured state, without a broker connection.
  await page.goto(`${base}/technicals`);
  await page.waitForFunction(()=>document.querySelector('#scan-status').textContent.includes('configure Alpaca'));
  assert.match(await page.locator('#chart-state').innerText(),/not configured/);
  let delay = false;
  await page.route('**/api/technicals/**',async route => {
    const url = new URL(route.request().url());
    const endpoint = url.pathname;
    let data;
    if (endpoint.endsWith('/config')) data = {default_symbols:['AAPL','MSFT','NVDA'],history_configured:true,earnings_configured:true,feed:'sip'};
    if (endpoint.endsWith('/scan')) {
      const symbols = route.request().postDataJSON().symbols.split(' ');
      data = {items:symbols.map(s=>fixture(s,1).summary),generated_at:'2026-10-17T16:00:00Z',feed:'sip'};
    }
    if (endpoint.includes('/chart/')) {
      const symbol = endpoint.split('/').at(-1);
      if (symbol === 'ERROR') return route.fulfill({status:503,json:{detail:'Feed access denied.'}});
      if (delay && symbol === 'AAPL') await new Promise(r=>setTimeout(r,600));
      data = fixture(symbol,Number(url.searchParams.get('years')),url.searchParams.get('anchor') || 'swing_high',url.searchParams.get('anchor_date'));
    }
    if (endpoint.includes('/earnings/')) {
      const symbol = endpoint.split('/').at(-1);
      const chart = fixture(symbol,Number(url.searchParams.get('years')));
      data = {status:'available',message:'Synthetic test dates',events:[
        {symbol,date:chart.bars.at(-120).time,hour:'amc',status:'historical'},
        {symbol,date:chart.bars.at(-55).time,hour:'bmo',status:'historical'},
        {symbol,date:'2025-02-20',hour:'amc',status:'scheduled'},
      ]};
    }
    return route.fulfill({json:data});
  });
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#earnings-state').textContent.includes('3 dates'));
  assert.equal(await page.locator('.rank-row').count(),3);
  assert.equal(await page.locator('#chart-state').isVisible(),false);
  assert(await page.evaluate(() => chart.timeScale().timeToCoordinate('2025-02-20') > chart.timeScale().timeToCoordinate('2025-01-17')),'Future earnings must be after the last real candle');
  const coloredPixels = await page.locator('#daily-chart canvas').first().evaluate(canvas=>{
    const ctx=canvas.getContext('2d'), data=ctx.getImageData(0,0,canvas.width,canvas.height).data;
    let count=0; for(let i=0;i<data.length;i+=4) if(Math.max(data[i],data[i+1],data[i+2])-Math.min(data[i],data[i+1],data[i+2])>60) count++;
    return count;
  });
  assert(coloredPixels>1000,`Expected nonblank colored candles/averages, got ${coloredPixels}`);
  await page.screenshot({path:path.join(output,'daily-desktop.png'),fullPage:true});
  assert(await page.evaluate(()=>avwapSeries.data().length > 0),'AVWAP line must contain data');
  await page.locator('#show-avwap').uncheck();
  assert.equal(await page.evaluate(()=>avwapSeries.options().visible),false);
  await page.locator('#show-avwap').check();
  await page.locator('#anchor-mode').selectOption('ytd');
  await page.waitForFunction(()=>state.chartData?.avwap?.anchor.mode === 'ytd');
  await page.locator('#anchor-mode').selectOption('custom');
  await page.waitForFunction(()=>state.chartData?.avwap?.anchor.mode === 'custom');
  assert.equal(await page.locator('#anchor-date').isVisible(),true);
  await page.locator('#anchor-mode').selectOption('swing_high');
  await page.waitForFunction(()=>state.chartData?.avwap?.anchor.mode === 'swing_high');
  await page.getByRole('button',{name:'Daily review',exact:true}).click();
  await page.waitForFunction(()=>state.reviewActive && state.chartData?.symbol === 'AAPL');
  await page.screenshot({path:path.join(output,'review-desktop.png'),fullPage:true});
  await page.keyboard.press('s');
  await page.waitForFunction(()=>state.chartData?.symbol === 'NVDA');
  assert.equal(await page.evaluate(()=>state.review.decisions.AAPL),'saved');
  await page.keyboard.press('ArrowLeft');
  await page.waitForFunction(()=>state.chartData?.symbol === 'AAPL');
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(()=>state.chartData?.symbol === 'NVDA');
  await page.locator('#symbol-input').focus();
  await page.keyboard.press('ArrowRight');
  assert.equal(await page.evaluate(()=>state.symbol),'NVDA');
  await page.locator('#chart-symbol').click();
  await page.keyboard.press('x');
  await page.waitForFunction(()=>state.chartData?.symbol === 'MSFT');
  await page.getByRole('button',{name:'Reviewed and next',exact:true}).click();
  assert.match(await page.locator('#review-progress').innerText(),/Review complete/);
  await page.getByRole('button',{name:'Exit review',exact:true}).click();
  await page.getByRole('button',{name:'Saved picks',exact:true}).click();
  assert.equal(await page.locator('.rank-row').count(),1);
  await page.getByRole('button',{name:'Saved picks',exact:true}).click();
  await page.getByRole('button',{name:'Bearish',exact:true}).click();
  assert.equal(await page.locator('.rank-row').count(),1);
  await page.getByRole('button',{name:'Review MSFT',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#chart-symbol').textContent==='MSFT' && document.querySelector('#chart-state').hidden);
  await page.getByRole('button',{name:'5Y',exact:true}).click();
  await page.waitForFunction(count=>document.querySelector('#feed-label').textContent.includes(`${count} daily candles`),fixture('MSFT',5).bars.length);
  await page.locator('[data-average="20"]').uncheck();
  await page.locator('#show-earnings').uncheck();
  await page.locator('#show-events').uncheck();
  await page.getByRole('button',{name:'Fit chart',exact:true}).click();
  await page.screenshot({path:path.join(output,'daily-five-years.png'),fullPage:true});
  await page.getByRole('button',{name:'All',exact:true}).click();
  await page.locator('#min-score').fill('70');
  await page.locator('#min-score').dispatchEvent('change');
  assert.equal(await page.locator('.rank-row').count(),2);
  await page.locator('#min-score').fill('0');
  await page.locator('#min-score').dispatchEvent('change');
  delay = true;
  await page.evaluate(()=>chartCache.clear());
  await page.getByRole('button',{name:'Review AAPL',exact:true}).click();
  await page.getByRole('button',{name:'Review NVDA',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#chart-symbol').textContent==='NVDA' && document.querySelector('#chart-state').hidden);
  await page.waitForTimeout(800);
  assert.equal(await page.locator('#chart-symbol').innerText(),'NVDA');
  await page.locator('#symbol-input').fill('ERROR');
  await page.locator('#symbol-input').press('Enter');
  await page.waitForFunction(()=>document.querySelector('#chart-state').textContent==='Feed access denied.');
  assert.equal(await page.locator('#last-price').innerText(),'');
  await page.getByRole('button',{name:'Review NVDA',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#chart-state').hidden);
  await page.locator('[data-average="20"]').check();
  await page.locator('#show-earnings').check();
  await page.locator('#show-events').check();
  for (const width of [390,320]) {
    await page.setViewportSize({width,height:844});
    await page.waitForTimeout(200);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true,`Horizontal overflow at ${width}`);
    const visibleStart = await page.evaluate(()=>chart.timeScale().getVisibleRange().from);
    assert((typeof visibleStart === 'string' ? Number(visibleStart.slice(0,4)) : visibleStart.year) <= 2020,`Five-year view was clipped after resize at ${width}: ${JSON.stringify(visibleStart)}`);
    await page.screenshot({path:path.join(output,`daily-mobile-${width}.png`),fullPage:true});
  }
  await page.getByRole('button',{name:'Daily review',exact:true}).click();
  await page.waitForFunction(()=>state.chartData && state.reviewActive);
  await page.screenshot({path:path.join(output,'review-mobile.png'),fullPage:true});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth),true);
  await page.getByRole('button',{name:'Exit review',exact:true}).click();
  await page.getByRole('button',{name:'Edit scan universe',exact:true}).click();
  await page.locator('#universe-input').fill('NVDA, AMD');
  await page.getByRole('button',{name:'Apply & scan',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#universe-count').textContent==='2 symbols');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#universe-count').textContent==='2 symbols');
  assert.equal(await page.locator('[data-years="5"]').getAttribute('aria-pressed'),'true');
  assert.equal(await page.evaluate(()=>Boolean(state.savedPicks.AAPL)),true);
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,coloredPixels,screenshots:output,checks:['unconfigured state','daily chart pixels','direction and score filters','5 year daily chart','AVWAP anchor selection and overlay','review queue and keyboard actions','saved picks and progress','earnings','fast ticker race','provider error','mobile 390 and 320','saved universe and range']}));
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
