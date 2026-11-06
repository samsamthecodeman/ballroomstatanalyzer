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
vm.runInContext('comparison.data = [{name:"Other",aid:2,events:[]}]',context);
context.renderComparison();
assert.match(element('compareEvents').innerHTML,/No shared event IDs/);
assert.match(element('compareStats').innerHTML,/Other/);
vm.runInContext('comparison.data[0].events = []',context);
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
  let addedId;
  context.fetch = async (url, options) => {
    if (url === '/api/start') {
      addedId = Number(JSON.parse(options.body).aid);
      return {ok:true,json:async()=>({id:'job'})};
    }
    return {ok:true,json:async()=>({state:'done',result:{status:'ok',name:'Dancer '+addedId,aid:addedId,source:'bce',events:[event({entry:'Dancer '+addedId,place:addedId})]}})};
  };
  for (const id of [2,3,4]) {
    element('compareName').value=String(id);
    await element('compareForm').listeners.submit({preventDefault(){}});
    await new Promise(setImmediate);
  }
  assert.equal(vm.runInContext('comparison.data.length',context),3);
  for (const name of ['You (you)','Dancer 2','Dancer 3','Dancer 4']) assert.ok(element('compareStats').innerHTML.includes(name));
  assert.equal((element('compareEvents').innerHTML.match(/<details>/g)||[]).length,3);
  assert.equal((element('compareRoster').innerHTML.match(/data-remove=/g)||[]).length,3);
  element('compareName').value='2';
  await element('compareForm').listeners.submit({preventDefault(){}});
  assert.match(element('compareStatus').textContent,/already in/);
  assert.equal(vm.runInContext('comparison.data.length',context),3);
  element('compareStop').listeners.click();
  assert.equal(vm.runInContext('comparison.data.length',context),3);
  element('compareRoster').listeners.click({target:{closest:()=>({dataset:{remove:'1'}})}});
  assert.deepEqual(Array.from(vm.runInContext('comparison.data.map(d=>d.aid)',context)),[2,4]);
  context.clearComparison();
  assert.equal(vm.runInContext('comparison.data.length',context),0);
  console.log('Passed: comparison outcomes, source/competition isolation, missing placements, shared partnerships, filters, field mode, clear, and same-profile rejection.');
  console.log('Passed: three retained comparison dancers, combined columns, individual head-to-head sections, duplicate rejection, stop preservation, removal, and clear all.');
})().catch(error=>{console.error(error);process.exitCode=1;});
