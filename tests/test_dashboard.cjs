const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function dashboard() {
  const pending = [];
  const elements = new Map();
  const context = vm.createContext({
    window: {}, rendered: [], details: [],
    document: { getElementById(id) {
      if (!elements.has(id)) elements.set(id, { style: {}, textContent: '' });
      return elements.get(id);
    } },
    fetch(url) {
      return new Promise(resolve => pending.push({ url, resolve: data => resolve({ json: async () => data }) }));
    },
    setTimeout, clearTimeout,
  });
  const source = fs.readFileSync(path.join(__dirname, '../app/web/app.js'), 'utf8');
  vm.runInContext(source.slice(0, source.indexOf('\ninitChart();')), context);
  vm.runInContext(`
    renderScanner = () => {};
    renderOpportunities = () => {};
    renderChartData = data => rendered.push(data.symbol);
    renderDetail = data => { if (data) details.push(data.symbol); };
  `, context);
  return { context, pending };
}

test('a late response for the old ticker cannot overwrite chart or details', async () => {
  const { context, pending } = dashboard();
  await context.selectSymbol('AAA');
  await context.selectSymbol('BBB');
  for (const request of pending.filter(r => r.url.includes('BBB'))) {
    request.resolve({ symbol: 'BBB', bars: [{}] });
  }
  await new Promise(setImmediate);
  for (const request of pending.filter(r => r.url.includes('AAA'))) {
    request.resolve({ symbol: 'AAA', bars: [{}] });
  }
  await new Promise(setImmediate);
  assert.deepEqual(Array.from(context.rendered), ['BBB']);
  assert.deepEqual(Array.from(context.details), ['BBB']);
});

test('poll ticks do not overlap a chart request already in flight', async () => {
  const { context, pending } = dashboard();
  await context.selectSymbol('AAA');
  await context.refreshChart();
  await context.refreshChart();
  assert.equal(pending.filter(r => r.url.includes('/api/chart/')).length, 1);
  for (const request of pending) request.resolve({ symbol: 'AAA', bars: [{}] });
  await new Promise(setImmediate);
});

test('negative P&L retains its minus sign', () => {
  const { context } = dashboard();
  assert.equal(context.fmtMoney(-26.95), '-$26.95');
  assert.equal(context.fmtMoney(26.95), '+$26.95');
});
