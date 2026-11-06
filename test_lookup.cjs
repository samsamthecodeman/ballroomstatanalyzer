const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/bce_web.py', 'utf8');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {
    value: '', textContent: '', listeners: {}, children: [],
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
  selectedSource: () => element('source').value || 'bce',
  setTimeout() {}, clearTimeout() {}, encodeURIComponent,
  fetch: async () => ({ok: true, json: async () => ({dancers: matches})}),
});
const start = source.indexOf('const dancerLookup =');
assert.match(source, /id="source" value="all"/);
assert.match(source, /id="sourceAll" aria-pressed="true">Unified data/);
element('source').value = 'all';
vm.runInContext(source.slice(start, source.indexOf('$("searchForm").addEventListener', start)), context);
(async () => {
  await context.lookupDancers('Sam');
  assert.equal(element('dancerSuggestions').children.length, 2);
  assert.match(element('dancerSuggestions').children[0].value, /ID 123/);
  assert.equal(element('dancerSuggestions').children[1].label, 'Dallas, TX');
  element('name').value = element('dancerSuggestions').children[1].value;
  element('name').listeners.input();
  assert.equal(element('aid').value, 124);
  assert.equal(element('name').value, 'Sam Example');
  element('name').value = 'Another dancer';
  element('name').listeners.input();
  assert.equal(element('aid').value, '');
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
  element('source').value = 'o2cm';
  element('source').listeners.change();
  assert.equal(element('fuzzy').disabled, true);
  element('name').value = 'Jonny Lu';
  element('name').listeners.input();
  assert.equal(element('name').value, 'Jonny Lu');
  element('sourceAll').listeners.click();
  assert.equal(element('source').value, 'all');
  assert.equal(element('cids').disabled, true);
  assert.equal(element('sourceAll')['aria-pressed'], 'true');
  assert.equal(element('name').value, 'Jonny Lu');
  element('source').value = 'bce';
  element('source').listeners.change();
  assert.equal(element('aid').value, '');
  assert.equal(element('cids').disabled, false);
  context.state = {requireId: true};
  context.norm = value => value.toLowerCase().trim();
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
    assert.equal(payload.source, sourceName);
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
  console.log('Passed: name selection, duplicate-name IDs, editing, stale response handling, and lookup errors.');
  console.log('Passed: unified name/ID submission for all three sources and duplicate-name partnership handoff.');
})().catch(error => { console.error(error); process.exitCode = 1; });
