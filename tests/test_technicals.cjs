const {test} = require('node:test');
const assert = require('node:assert/strict');
const {filteredItems,chartMarkers,hourLabel,escapeHtml,reviewQueue} = require('../app/web/technicals.js');

test('filters separate direction, current held events and minimum score', () => {
  const items = [
    {symbol:'UP',eligible:true,direction:'bullish',score:70,signals:[{held:true,kind:'price200',direction:'bullish'}]},
    {symbol:'DOWN',eligible:true,direction:'bearish',score:60,signals:[{held:true,kind:'ma20_50',direction:'bearish'}]},
    {symbol:'OLD',eligible:false,direction:'bullish',score:40,signals:[]},
  ];
  assert.deepEqual(filteredItems(items,'all','all',0,true).map(x=>x.symbol),['UP','DOWN']);
  assert.deepEqual(filteredItems(items,'bearish','ma20_50',50,true).map(x=>x.symbol),['DOWN']);
  assert.equal(filteredItems(items,'bullish','ma20_50',0,true).length,0);
  assert.equal(filteredItems(items,'all','all',65,true).length,1);
});

test('earnings markers preserve exact dates and toggles do not change event data', () => {
  const data = {bars:[{time:'2026-01-01'}],events:[{kind:'ma20_50',time:'2026-02-01',direction:'bullish',label:'SMA 20 / 50'}]};
  const earnings = [{date:'2026-01-20',hour:'amc'},{date:'2027-01-01',hour:'bmo'},{date:'2025-01-01',hour:'unknown'}];
  const markers = chartMarkers(data,earnings,true,true);
  assert.deepEqual(markers.map(m=>m.time),['2026-01-20','2026-02-01','2027-01-01']);
  assert.equal(chartMarkers(data,earnings,false,true).length,2);
  assert.equal(chartMarkers(data,earnings,true,false).length,1);
  assert.equal(hourLabel('amc'),'after close');
  assert.equal(escapeHtml('<script>'),'&lt;script&gt;');
});

test('review queue is ranked, bounded and excludes stale or scoreless setups', () => {
  const items = [{symbol:'OLD',eligible:false,score:99},{symbol:'LOW',eligible:true,score:40},
    {symbol:'BEST',eligible:true,score:80},{symbol:'ZERO',eligible:true,score:0}];
  assert.deepEqual(reviewQueue(items,1),['BEST']);
  assert.deepEqual(reviewQueue(items,20),['BEST','LOW']);
  assert.equal(items[0].symbol,'OLD');
});

test('discovery and AVWAP filters require corresponding evidence', () => {
  const item = {eligible:true,score:60,direction:'bullish',discovery:{above_52w:true},
    signals:[{kind:'avwap',direction:'bullish',held:true}]};
  assert.equal(filteredItems([item],'all','discovery',0,true).length,1);
  assert.equal(filteredItems([item],'all','avwap',0,true).length,1);
  assert.equal(filteredItems([{...item,discovery:{}}],'all','discovery',0,true).length,0);
});
