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
  });
  return nodes.get(id);
}
const matches = [
  {id: 123, name: 'Sam Example', location: 'Austin, TX'},
  {id: 124, name: 'Sam Example', location: 'Dallas, TX'},
];
const context = vm.createContext({
  $: element, VISITOR_ID: 'test', document: {createElement: () => ({})},
  setTimeout() {}, clearTimeout() {}, encodeURIComponent,
  fetch: async () => ({ok: true, json: async () => ({dancers: matches})}),
});
const start = source.indexOf('const dancerLookup =');
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
  console.log('Passed: name selection, duplicate-name IDs, editing, stale response handling, and lookup errors.');
})().catch(error => { console.error(error); process.exitCode = 1; });
