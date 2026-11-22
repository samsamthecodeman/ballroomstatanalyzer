const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(__dirname+'/bce_web.py','utf8');
let buttons=[];
const context=vm.createContext({$:()=>({querySelectorAll:()=>buttons})});
const start=source.indexOf('let scoreSort =');
vm.runInContext(source.slice(start,source.indexOf('function scoreVisibleRows()',start)),context);
const rows=[
 {id:'a',date:'2026-01-01',comp:'First',event:'Event 10',partner:'Zoe',place:10,entries:20,made_final:false,rounds_danced:1},
 {id:'b',date:'2026-11-21',comp:'Second',event:'Event 2',partner:'Alex',place:2,entries:8,made_final:true,rounds_danced:3},
 {id:'c',date:null,event:'Event 1',partner:'',place:null,entries:12,made_final:false,rounds_danced:null},
 {id:'d',date:'2026-11-20',comp:'Second',event:'Event 3',partner:'Sam',place:2,entries:4,made_final:true,rounds_danced:2}
];
const sorted=(key,dir=1)=>Array.from(context.sortScoreRows(rows,{key,dir}),r=>r.id);
assert.deepEqual(sorted('date',-1),['b','d','a','c']);
assert.deepEqual(sorted('date',1),['a','d','b','c']);
assert.deepEqual(sorted('event'),['c','b','d','a']);
assert.deepEqual(sorted('partner'),['c','b','d','a']);
assert.deepEqual(sorted('place'),['d','b','a','c']);
assert.deepEqual(sorted('place',-1),['a','b','d','c']);
assert.deepEqual(sorted('made_final',-1),['b','d','a','c']);
assert.deepEqual(sorted('rounds',-1),['b','d','a','c']);
assert.deepEqual(rows.map(r=>r.id),['a','b','c','d'],'Sorting must not mutate the saved history');
assert.deepEqual(Array.from(context.sortScoreRows([{entry:'B',rounds:1},{entry:'A',rounds:3}],{key:'rounds',dir:-1},true),r=>r.entry),['A','B']);
const sort={key:'date',dir:-1};let renders=0;
buttons=[{dataset:{scoreSort:'place'},addEventListener(event,fn){this.click=fn;}}];
context.bindScoreSort(sort,()=>renders++);
buttons[0].click();assert.deepEqual(sort,{key:'place',dir:1});
buttons[0].click();assert.deepEqual(sort,{key:'place',dir:-1});
assert.equal(renders,2);
assert.match(context.scoreHeaders([['place','Place']],sort),/aria-sort="descending"/);
assert.match(context.scoreHeaders([['place','Place']],sort),/button type="button"/);
console.log('Passed: all score columns, numeric and natural text ordering, both directions, missing values last, field rounds, immutable histories, and accessible sort buttons.');
