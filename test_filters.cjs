const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(__dirname + '/bce_web.py', 'utf8');
const nodes = new Map();
function element(id) {
  if (!nodes.has(id)) nodes.set(id, {
    innerHTML: 'old content', textContent: '', checked: false, listeners: {},
    classList: {toggle() {}},
    addEventListener(event, handler) { this.listeners[event] = handler; },
    querySelectorAll() { return []; },
  });
  return nodes.get(id);
}
const events = [1, 2, 8, null, 0].map((entries, i) => ({
  entries, eid: i, category: 'Couple-judged', style: 'International Standard',
  level: 'Newcomer', division: 'Amateur', partner: 'Partner', role: 'Follower',
}));
const context = vm.createContext({
  state: {data: {events}, filters: {}, openOpp: 'old', rivOpen: 'old'},
  $: element, esc: String, render() {},
  document: {querySelectorAll() { return []; }},
});
function load(start, end) {
  vm.runInContext(source.slice(source.indexOf(start), source.indexOf(end, source.indexOf(start))), context);
}
load('function passesEventExclusions(e) {', 'function summary(');
load('function buildFilters() {', 'function renderChart(');
load('function renderYcn() {', '$("ycnRoles").addEventListener');
assert.equal(context.filtered().length, 5);
context.buildFilters();
assert.match(element('filters').innerHTML, /Exclude uncontested events/);
element('excludeUncontested').listeners.change({target: {checked: true}});
assert.deepEqual(Array.from(context.filtered(), e => e.entries), [2, 8, null, 0]);
assert.equal(context.state.openOpp, null);
assert.equal(context.state.rivOpen, null);
context.state.filters.style = 'American Smooth';
assert.equal(context.filtered().length, 0);
element('resetF').listeners.click();
assert.equal(context.state.filters.excludeUncontested, false);
assert.equal(element('excludeUncontested').checked, false);
assert.equal(context.filtered().length, 5);
context.state.filters.excludeUncontested = true;
context.state.data.events = [events[0]];
context.renderYcn();
assert.equal(element('ycnEvents').innerHTML, '');
assert.equal(element('ycnRoles').innerHTML, '');
console.log('Passed: browser filtering, checkbox, reset, and empty YCN state.');

context.avg = values => values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
context.pct = value => value == null ? '-' : Math.round(value) + '%';
context.r1 = value => value == null ? '-' : String(Math.round(value * 10) / 10);
context.applyLimit = rows => rows;
context.renderFoot = () => {};
context.sortHeader = () => '';
context.cmp = (a, b, key, dir) => (a[key] < b[key] ? -1 : a[key] > b[key] ? 1 : 0) * dir;
load('function fieldBeaten(e) {', 'function headToHead(');
context.state.fieldMode = 'total';
assert.equal(context.fieldBeaten({percentile: 81.8, final_percentile: 60}), 81.8);
context.state.fieldMode = 'finals';
assert.equal(context.fieldBeaten({percentile: 81.8, final_percentile: 60}), 60);
assert.equal(context.fieldBeaten({percentile: 20, final_percentile: null}), null);
assert.equal(context.summary([{percentile: 81.8, final_percentile: 60}, {percentile: 20, final_percentile: null}]).avgPct, 60);
context.state.fieldMode = 'total';
load('function renderBreakdown(evs) {', 'const BD_SORTS =');
context.state.bdKey = 'dance';
context.state.bdSort = {key: 'k', dir: 1};
const danceEvents = [
  {dances: ['Waltz', 'Waltz'], place: 1, made_final: true, entries: 10, percentile: 100},
  {dances: ['Waltz', 'Tango'], place: 3, made_final: true, entries: 10, percentile: 80},
  {dances: [], place: null, made_final: false, entries: 8},
];
context.renderBreakdown(danceEvents);
assert.match(element('bdTabs').innerHTML, /data-k="dance" aria-pressed="true">Dance/);
const table = element('bdTable').innerHTML;
assert.match(table, /<td>Waltz<\/td><td class="num">2<\/td><td class="num">1<\/td><td class="num">100%<\/td><td class="num">2<\/td>/);
assert.match(table, /<td>Tango<\/td><td class="num">1<\/td><td class="num">0<\/td>/);
assert.match(table, /<td>Unknown dance<\/td><td class="num">1<\/td>/);
context.state.bdKey = 'category';
context.renderBreakdown([{...danceEvents[0], category: 'Couple-judged'}, {...danceEvents[1], category: 'Couple-judged'}]);
assert.match(element('bdTable').innerHTML, /<td>Couple-judged<\/td><td class="num">2<\/td>/);
context.state.bdKey = 'dance';
context.renderBreakdown([]);
assert.match(element('bdTable').innerHTML, /<tbody><\/tbody>/);
console.log('Passed: dance breakdown statistics, multi-dance entries, duplicate dances, unknown dances, and existing categories.');

context.state.filters = {};
const podiumEvents = [1, 2, 3, null, 4].map((place, eid) => ({...events[0], entries: 3, place, eid}));
podiumEvents.push({...events[0], entries: 4, place: 3, eid: 5}, {...events[0], entries: 2, place: 1, eid: 6},
  {...events[0], entries: null, place: 1, eid: 7}, {...events[0], entries: 1, place: 1, eid: 8},
  {...events[0], entries: 3, place: 1, category: 'Solo', eid: 9},
  {...events[0], entries: 3, place: 1, role: 'Solo', eid: 10});
context.state.data.events = podiumEvents;
context.buildFilters();
element('excludeThreeCouplePodiums').listeners.change({target: {checked: true}});
assert.deepEqual(Array.from(context.filtered(), event => event.eid), [3, 4, 5, 6, 7, 8, 9, 10]);
element('excludeUncontested').listeners.change({target: {checked: true}});
assert.deepEqual(Array.from(context.filtered(), event => event.eid), [3, 4, 5, 6, 7, 9, 10]);
element('resetF').listeners.click();
assert.equal(context.state.filters.excludeThreeCouplePodiums, false);
assert.equal(element('excludeThreeCouplePodiums').checked, false);
assert.equal(context.filtered().length, 11);
console.log('Passed: exact 3-couple podium exclusion, solo and unknown-data preservation, combined filters, and reset.');
