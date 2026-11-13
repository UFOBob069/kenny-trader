const {test} = require('node:test');
const assert = require('node:assert/strict');
const {parseWatchlist,watchlistVerdict} = require('../app/web/technical-watchlist.js');
const candidate = {eligible:true,score:65,direction:'bullish',trigger:{label:'Price / 200'},
  chart_assessment:{available:true,score:72},readiness:{status:'conditional',reasons:[]}};

test('watchlist validates, deduplicates and preserves manual order; empty removes all', () => {
  assert.deepEqual(parseWatchlist(' nvda, aapl; NVDA\nBRK.B '), ['NVDA','AAPL','BRK.B']);
  assert.deepEqual(parseWatchlist('  '), []);
  assert.throws(()=>parseWatchlist('<script>'));
  assert.throws(()=>parseWatchlist('BAD1'));
  assert.throws(()=>parseWatchlist(Array.from({length:101},(_,i)=>'X'+String.fromCharCode(65+Math.floor(i/26),65+i%26)).join(' ')));
});
test('action uses plan readiness and direction, not high chart score', () => {
  assert.equal(watchlistVerdict(candidate).action,'Buy');
  assert.equal(watchlistVerdict({...candidate,direction:'bearish'}).action,'Sell');
  const wait = watchlistVerdict({...candidate,score:99,readiness:{status:'wait',reasons:['Stop too wide.']}});
  assert.equal(wait.action,'Hold');
  assert.equal(wait.reason,'Stop too wide.');
  assert.equal(watchlistVerdict(candidate).score,65);
  assert.match(watchlistVerdict({...candidate,provisional:true}).reason,/provisional/);
});
test('no trigger gives chart context and Hold; missing/stale data is never a Buy', () => {
  const context = watchlistVerdict({...candidate,eligible:false,trigger:null,readiness:{status:'unavailable',reasons:['No held trigger.']}});
  assert.equal(context.action,'Hold');
  assert.equal(context.label,'Chart');
  assert.equal(context.score,72);
  for (const item of [null, {...candidate,chart_assessment:{available:false}},
    {...candidate,eligible:false,readiness:{status:'unavailable'}},
    {...candidate,current_day:{status:'unavailable'}},
    {...candidate,warnings:['Stale daily history; excluded from ranked signals.']}]) {
    assert.equal(watchlistVerdict(item).action,'Unavailable');
  }
});
