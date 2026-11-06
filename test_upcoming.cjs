const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/bce_web.py','utf8');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id,{value:'243',innerHTML:'',textContent:'',listeners:{},
    addEventListener(event,fn){this.listeners[event]=fn;}});
  return nodes.get(id);
}
const esc = s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const history={meetings:1,wins:1,losses:0,ties:0,unplaced:0,together:0,matches:[{date:'2025-01-01',competition:'Past',event:'Waltz',category:'Couple-judged',your_partner:'Partner',opposing_entry:'Other & Partner',your_place:1,their_place:2,url:'https://example.com'}]};
const data={competition:'<Unsafe name>',dancer:'Sam',sessions:['Session'],warnings:[],url:'https://example.com',schedule_url:'https://example.com',history_events:10,checked_at:'2026-11-06T00:00:00Z',cache_minutes:15,
  events:[{number:12,time:'10:00 AM',title:'Waltz',round:'Final',entries:2,session:'Morning',role:'Leading',partner:'Partner',category:'Couple-judged',opponents:[{bib:'2',entry:'Other & Partner',partnership_history:history,people_history:[{name:'Other',history}]}]}]};
const context=vm.createContext({$:element,esc,norm:s=>s.toLowerCase(),state:{resultJobId:'job'},VISITOR_ID:'test',
  fetch:async()=>({ok:true,json:async()=>data})});
const start=source.indexOf('// ---------------- Upcoming competition');
vm.runInContext(source.slice(start,source.indexOf('// ---------------- Dancer comparison',start)),context);
context.renderUpcoming(data);
assert.match(element('upcomingResults').innerHTML,/&lt;Unsafe name&gt;/);
assert.match(element('upcomingResults').innerHTML,/1 distinct previous opponents/);
assert.doesNotMatch(element('upcomingResults').innerHTML,/<table>/,'History tables must load on expansion');
const table={innerHTML:''};
element('upcomingResults').listeners.toggle({target:{open:true,dataset:{history:'0'},querySelector:()=>table}});
assert.match(table.innerHTML,/<table>/);
assert.match(table.innerHTML,/Other &amp; Partner/);
assert.match(context.meetingSummary(null),/Ambiguous/);
(async()=>{
  await element('upcomingForm').listeners.submit({preventDefault(){}});
  assert.equal(element('upcomingGo').disabled,false);
  assert.match(element('upcomingStatus').textContent,/cached for 15 minutes/);
  context.fetch=async()=>({ok:false,json:async()=>({error:'Expired analysis'})});
  await element('upcomingForm').listeners.submit({preventDefault(){}});
  assert.equal(element('upcomingStatus').textContent,'Expired analysis');
  let release;
  context.fetch=()=>new Promise(resolve=>{release=resolve;});
  const pending=element('upcomingForm').listeners.submit({preventDefault(){}});
  vm.runInContext('++upcomingSequence',context);
  release({ok:true,json:async()=>data});
  await pending;
  assert.equal(element('upcomingResults').textContent,'');
  console.log('Passed: upcoming summary, HTML escaping, lazy meeting tables, errors, successful requests, and stale response handling.');
})().catch(error=>{console.error(error);process.exitCode=1;});
