const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/bce_web.py','utf8'),nodes=new Map();
function element(id){
  if(!nodes.has(id)) nodes.set(id,{value:'',textContent:'',innerHTML:'',children:[],options:[],listeners:{},
    addEventListener(event,fn){this.listeners[event]=fn;},setAttribute(k,v){this[k]=v;},
    replaceChildren(...children){this.children=children;},querySelectorAll(){return [];}});
  return nodes.get(id);
}
let requested,scheduled;
const context=vm.createContext({$:element,esc:String,positiveClass:n=>n>0?'positive':'',
  URLSearchParams,encodeURIComponent,clearTimeout(){},setTimeout(fn){scheduled=fn;},
  document:{createElement:()=>({})},exploreSource:'all',texasSequence:0,
  exploreApi:async url=>{
    requested=url;
    return {mode:'couple',region:'texas',competitions:[],total_names:1,matching_names:1,
      rows:[{rank:1,name:'Alex Example & Sam Example',wins:2,events:3,competitions:1}],
      years:[],unknown_venues:0,deduplicated:1,unclassified_events:0};
  }});
const start=source.indexOf('function selectedLeaderboardStyles()');
vm.runInContext(source.slice(start,source.indexOf('function resetScoreHistory()',start)),context);
(async()=>{
  element('texasCategory').value='Solo';
  element('leaderMode').value='couple';
  context.updateLeaderboardMode();
  assert.equal(element('texasCategory').value,'Couple-judged');
  assert.equal(element('texasCategory').disabled,true);
  assert.equal(element('leaderCoupleNote').hidden,false);
  assert.equal(element('texasName').list,'leaderCoupleSuggestions');
  element('leaderRegion').value='texas';
  await context.loadTexas();
  assert.equal(new URL('https://example.com'+requested).searchParams.get('mode'),'couple');
  assert.match(element('texasTable').innerHTML,/<th>Couple<\/th>/);
  assert.match(element('texasTable').innerHTML,/Alex Example & Sam Example/);
  assert.match(element('texasTable').innerHTML,/class="positive">2/);
  assert.match(element('texasStatus').textContent,/1 couples/);
  scheduled=null;
  element('texasName').value='Sa';
  element('texasName').listeners.input();
  assert.equal(scheduled,null);
  element('texasName').value='Sam';
  element('texasName').listeners.input();
  context.exploreApi=async()=>({couples:[{label:'Alex Example & Sam Example'}]});
  await scheduled();
  assert.equal(element('leaderCoupleSuggestions').children[0].value,'Alex Example & Sam Example');
  let finish;
  context.exploreApi=()=>new Promise(resolve=>{finish=resolve;});
  element('texasName').listeners.input();
  const pending=scheduled();
  element('leaderMode').value='individual';
  context.updateLeaderboardMode();
  finish({couples:[{label:'Outdated couple'}]});
  await pending;
  assert.equal(element('leaderCoupleSuggestions').children.length,0);
  assert.equal(element('texasCategory').value,'Solo');
  assert.equal(element('texasCategory').disabled,false);
  assert.equal(element('leaderCoupleNote').hidden,true);
  console.log('Passed: couple leaderboard mode, category restoration, API request, pair labels, green wins, three-character suggestions, and stale response rejection.');
})().catch(error=>{console.error(error);process.exitCode=1;});
