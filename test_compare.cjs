const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/bce_web.py', 'utf8');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {value: '', textContent: '', innerHTML: '', listeners: {},
    classList: {toggle() {}}, addEventListener(name, fn) {this.listeners[name] = fn;}, replaceChildren() {}});
  return nodes.get(id);
}
const norm = text => String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
const context = vm.createContext({$: element, norm, esc: String, VISITOR_ID: 'test',
  avg: a => a.length ? a.reduce((a,b)=>a+b,0)/a.length : null,
  pct: value => value == null ? '–' : Math.round(value) + '%', r1: String,
  state: {fieldMode:'total', filters:{}},
  clearTimeout(){}, setTimeout(){}, encodeURIComponent,
  fetch: async () => ({ok:true,json:async()=>({id:'job'})}), document:{createElement:()=>({})}
});
function load(start, end) {
  vm.runInContext(source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))), context);
}
load('function passesEventExclusions(', 'function headToHead(');
load('// ---------------- Dancer comparison', '// ---------------- Rendering');
function event(changes={}) {
  return {source:'bce',cid:1,eid:1,entry:'You & Partner',place:2,entries:8,made_final:true,
    percentile:85.7,final_percentile:80,comp:'Competition',event:'Waltz',date:'2026-01-01',url:'https://example.com',...changes};
}
const ours = [event(),event({eid:2}),event({eid:3}),event({eid:4}),event({eid:5,place:null}),event({eid:6})];
const theirs = [event({entry:'Other & Partner',place:3}),event({eid:2,entry:'Other & Partner',place:1}),
  event({eid:3,entry:'Other & Partner'}),event({eid:4}),event({eid:5,entry:'Other & Partner',place:null}),
  event({eid:6,source:'o2cm',entry:'Other & Partner'})];
const shared = context.sharedComparisonEvents(ours,theirs);
assert.deepEqual(Array.from(shared,row=>row.outcome),['Win','Loss','Tie','Together','Unplaced']);
assert.equal(context.sharedComparisonEvents([event({cid:2})],theirs).length,0);
context.state.data = {name:'You',aid:1,source:'bce',events:ours};
vm.runInContext('comparison.data = {name:"Other",aid:2,events:[]}',context);
context.renderComparison();
assert.match(element('compareEvents').innerHTML,/No shared event IDs/);
assert.match(element('compareStats').innerHTML,/Other/);
vm.runInContext('comparison.data.events = []',context);
context.state.filters.excludeUncontested = true;
assert.equal(context.filterEvents([event({entries:1}),event()]).length,1);
context.state.fieldMode = 'finals';
assert.equal(context.summary([event(),event({final_percentile:null})]).avgPct,80);
context.clearComparison();
assert.equal(element('compareName').value,'');
assert.equal(element('compareGo').disabled,false);
assert.equal(element('compareStats').textContent,'');
(async()=>{
  element('compareName').value='1';
  await element('compareForm').listeners.submit({preventDefault(){}});
  assert.match(element('compareStatus').textContent,/different dancer/);
  assert.equal(element('compareGo').disabled,false);
  console.log('Passed: comparison outcomes, source/competition isolation, missing placements, shared partnerships, filters, field mode, clear, and same-profile rejection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
