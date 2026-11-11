const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/bce_web.py', 'utf8');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {
    value: '', textContent: '', listeners: {}, children: [],
    classList: {toggle() {}},
    addEventListener(event, fn) { this.listeners[event] = fn; },
    replaceChildren(...children) { this.children = children; },
    setAttribute(key, value) { this[key] = value; },
  });
  return nodes.get(id);
}
const matches = [
  {id: 123, name: 'Sam Example', location: 'Austin, TX'},
  {id: 124, name: 'Sam Example', location: 'Dallas, TX'},
];
const context = vm.createContext({
  $: element, VISITOR_ID: 'test', document: {createElement: () => ({})},
  selectedSource: () => 'all',
  setTimeout() {}, clearTimeout() {}, encodeURIComponent,
  fetch: async () => ({ok: true, json: async () => ({dancers: matches})}),
});
const start = source.indexOf('const dancerLookup =');
assert.match(source, /id="source" value="all"/);
assert.doesNotMatch(source, /id="source(?:All|Bce|O2cm)"|data-explore-source=/);
assert.match(source, /const selectedSource = \(\) => "all"/);
element('source').value = 'all';
element('analysisMode').value = 'individual';
vm.runInContext(source.slice(start, source.indexOf('$("searchForm").addEventListener', start)), context);
(async () => {
  await context.lookupDancers('Sam');
  assert.equal(element('dancerSuggestions').children.length, 2);
  assert.match(element('dancerSuggestions').children[0].value, /ID 123/);
  assert.equal(element('dancerSuggestions').children[1].label, 'Dallas, TX');
  element('name').value = element('dancerSuggestions').children[1].value;
  element('name').listeners.input();
  assert.equal(element('aid').value, 124);
  assert.equal(element('aid').hidden, false);
  assert.equal(element('name').value, 'Sam Example');
  element('name').value = 'Another dancer';
  element('name').listeners.input();
  assert.equal(element('aid').value, '');
  assert.equal(element('aid').hidden, true);
  let release;
  context.fetch = () => new Promise(resolve => { release = resolve; });
  const pending = context.lookupDancers('Sam');
  element('name').value = 'Different dancer';
  element('name').listeners.input();
  release({ok: true, json: async () => ({dancers: matches})});
  await pending;
  assert.equal(element('dancerSuggestions').children.length, 0);
  context.fetch = async () => ({ok: false, json: async () => ({error: 'Try a dancer ID'})});
  await context.lookupDancers('Sam');
  assert.equal(element('dancerLookupStatus').textContent, 'Try a dancer ID');
  element('name').value = 'Jonny Lu';
  element('name').listeners.input();
  assert.equal(element('name').value, 'Jonny Lu');
  assert.equal(element('cids').disabled, true);
  context.state = {requireId: true};
  context.norm = value => value.toLowerCase().trim();
  context.selectPage = () => {};
  context.show = context.setStatus = context.poll = () => {};
  context.fail = message => { throw new Error(message); };
  const submitStart = source.indexOf('$("searchForm").addEventListener', start);
  vm.runInContext(source.slice(submitStart, source.indexOf('$("cancelBtn").addEventListener', submitStart)), context);
  let payload;
  context.fetch = async (url, options) => {
    if (url.startsWith('/api/dancers')) return {ok: true, json: async () => ({dancers: matches})};
    payload = JSON.parse(options.body);
    return {ok: true, json: async () => ({id: 'test-job'})};
  };
  for (const sourceName of ['bce', 'o2cm', 'all']) {
    element('source').value = sourceName;
    element('name').value = '10062';
    await element('searchForm').listeners.submit({preventDefault() {}});
    assert.equal(payload.source, 'all');
    assert.equal(payload.aid, '10062');
    assert.equal(payload.name, '');
  }
  element('name').value = 'Sam Example';
  await element('searchForm').listeners.submit({preventDefault() {}});
  assert.equal(payload.name, 'Sam Example');
  assert.equal(payload.aid, '', 'Unified data must let the backend resolve duplicate names using partnerships');
  element('source').value = 'o2cm';
  element('name').value = 'Jonny Lu';
  await element('searchForm').listeners.submit({preventDefault() {}});
  assert.equal(payload.name, 'Jonny Lu');
  assert.equal(payload.aid, '');
  element('analysisMode').value = 'couple';
  element('analysisMode').listeners.change();
  assert.equal(element('couplePartner').hidden, false);
  assert.equal(element('couplePartner').required, true);
  const pair = {names:['Alex Example','Sam Example'],label:'Alex Example & Sam Example'};
  context.fetch = async () => ({ok:true,json:async()=>({couples:[pair]})});
  element('name').value = 'Sam';
  await context.lookupCouples('Sam');
  assert.equal(element('coupleSuggestions').children[0].value, pair.label);
  element('name').value = pair.label;
  element('name').listeners.input();
  assert.equal(element('name').value, 'Alex Example');
  assert.equal(element('couplePartner').value, 'Sam Example');
  assert.equal(element('aid').hidden, true);
  await context.lookupCouples('Sam', true);
  assert.equal(element('partnerSuggestions').children[0].value, 'Sam Example');
  element('couplePartner').listeners.input();
  assert.equal(element('name').value, 'Alex Example');
  let finishCouple;
  context.fetch = () => new Promise(resolve => {finishCouple=resolve;});
  const staleCouple = context.lookupCouples('Sam');
  element('name').value = 'Changed';
  element('name').listeners.input();
  finishCouple({ok:true,json:async()=>({couples:[pair]})});
  await staleCouple;
  assert.equal(element('coupleSuggestions').children.length, 0);
  context.fetch = async (url,options) => {
    payload = JSON.parse(options.body);
    return {ok:true,json:async()=>({id:'test-job'})};
  };
  context.state.requireId = false;
  element('couplePartner').value = ' Partner Example ';
  element('partner').value = 'Ignored individual filter';
  element('fuzzy').checked = true;
  await element('searchForm').listeners.submit({preventDefault() {}});
  assert.equal(payload.analysis_mode, 'couple');
  assert.equal(payload.partner, 'Partner Example');
  assert.equal(payload.fuzzy, false);
  element('analysisMode').value = 'individual';
  element('analysisMode').listeners.change();
  assert.equal(element('couplePartner').hidden, true);
  assert.equal(element('couplePartner').required, false);
  await element('searchForm').listeners.submit({preventDefault() {}});
  assert.equal(payload.analysis_mode, 'individual');
  assert.equal(payload.partner, 'Ignored individual filter');
  assert.equal(payload.fuzzy, true);
  console.log('Passed: couple autofill, known partner suggestions, stale response rejection, and mode switching.');
  console.log('Passed: name selection, duplicate-name IDs, editing, stale response handling, and lookup errors.');
  console.log('Passed: always-unified name/ID submission despite hidden-field tampering and duplicate-name partnership handoff.');
})().catch(error => { console.error(error); process.exitCode = 1; });
