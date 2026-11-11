const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/bce_web.py','utf8'),nodes=new Map();
const checks=[{value:'International Standard',checked:true},{value:'American Smooth',checked:true},{value:'International Latin',checked:false}];
function element(id){if(!nodes.has(id))nodes.set(id,{value:'',textContent:'',innerHTML:'',listeners:{},classList:{add(){},remove(){}},
  addEventListener(name,fn){this.listeners[name]=fn;},setAttribute(key,value){this[key]=value;},replaceChildren(){},querySelectorAll(selector){return selector==='input:checked'?checks.filter(c=>c.checked):checks;}});return nodes.get(id);}
const catalog=[{cid:1,name:'My BCE Cup',members:[1],source_label:'BCE'},{cid:'o2cm:test',name:'My O2 Cup',members:['o2cm:test'],source_label:'O2CM'},{cid:3,name:'Unrelated Cup',members:[3],source_label:'BCE'}];
const events=[{cid:1,event:'Waltz',partner:'Partner A',place:1,entries:3,made_final:true,rounds_danced:2,url:'https://example.com',category:'Couple-judged'},
  {cid:'o2cm:test',event:'Tango',partner:'Partner B',place:2,entries:4,made_final:true,rounds_danced:1,url:'https://example.com',category:'Couple-judged'}];
const context=vm.createContext({$:element,norm:s=>s.toLowerCase().trim(),esc:String,state:{data:{source:'all',name:'Sam Example',events}},
  VISITOR_ID:'test',clearTimeout(){},setTimeout(){},encodeURIComponent,document:{createElement:()=>({})},
  exploreApi:async()=>({competitions:catalog}),fetch:async()=>({ok:true,json:async()=>({id:'job'})})});
vm.runInContext(source.slice(source.indexOf('function positiveClass('),source.indexOf('function summary(')),context);
vm.runInContext('let catalogData=[],scoreSequence=0,scoreHistory=null,scoreHistorySequence=0,scoreHistoryJob=null,scorePollTimer,scoreDancerTimer,scoreSelected=null,scoreMatches=new Map(),exploreSource="all";',context);
let start=source.indexOf('function selectedLeaderboardStyles()');
vm.runInContext(source.slice(start,source.indexOf('async function loadTexas()',start)),context);
assert.deepEqual(Array.from(context.selectedLeaderboardStyles()),['International Standard','American Smooth']);
context.updateLeaderboardStyles();assert.equal(element('texasStyleSummary').textContent,'2 styles selected');
element('clearTexasStyles').listeners.click();assert.equal(element('texasStyleSummary').textContent,'All styles');
start=source.indexOf('function resetScoreHistory()');
vm.runInContext(source.slice(start,source.indexOf('// ---------------- Upcoming competition',start)),context);
(async()=>{
  await context.loadCatalog();
  assert.match(element('scoreCompetition').innerHTML,/My BCE Cup/);
  assert.match(element('scoreCompetition').innerHTML,/My O2 Cup/);
  assert.doesNotMatch(element('scoreCompetition').innerHTML,/Unrelated Cup/);
  assert.equal(element('scoreDancer').value,'Sam Example');
  assert.equal(element('scoreCompetition').value,'');
  assert.match(element('scoreTable').innerHTML,/Waltz/);
  assert.match(element('scoreTable').innerHTML,/Tango/);
  assert.match(element('scoreStatus').textContent,/All competitions/);
  element('scoreCompetition').value='1';context.showDancerCompetition();
  assert.match(element('scoreTable').innerHTML,/Waltz/);
  assert.doesNotMatch(element('scoreTable').innerHTML,/Tango|<th>Source/);
  element('scoreCompetition').value='';context.showDancerCompetition();
  assert.match(element('scoreTable').innerHTML,/Tango/);
  context.resetScoreHistory();context.state.data.scope_limited=true;
  await context.loadCatalog();
  assert.doesNotMatch(element('scoreCompetition').innerHTML,/My BCE Cup/);
  assert.equal(element('scoreCompetition').disabled,true);
  element('scoreDancer').value='New Person';
  const newEvents=[{...events[0],cid:4,comp:'Newly cached Cup'}];
  context.exploreApi=async url=>url.startsWith('/api/dancers')?{dancers:[{id:321,name:'New Person'}]}:
    url.startsWith('/api/status')?{state:'done',result:{status:'ok',source:'all',name:'New Person',events:newEvents}}:{competitions:catalog};
  await element('scoreDancerForm').listeners.submit({preventDefault(){}});
  await new Promise(setImmediate);
  assert.equal(element('scoreDancer').value,'New Person');
  assert.match(element('scoreCompetition').innerHTML,/Newly cached Cup/);
  assert.doesNotMatch(element('scoreCompetition').innerHTML,/Unrelated Cup/);
  assert.equal(element('scoreLoad').disabled,false);
  console.log('Passed: multi-style selection/reset, personal competition lists across providers, unrelated-competition exclusion, all-event results, source-column removal, and restricted-analysis rejection.');
  console.log('Passed: name-first history lookup and freshly discovered competitions before catalog refresh.');
})().catch(e=>{console.error(e);process.exitCode=1;});
