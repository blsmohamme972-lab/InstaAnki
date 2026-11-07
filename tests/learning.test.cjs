const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
function setup(initial){const data=new Map();if(initial!==undefined)data.set('instaanki.state.v1',typeof initial==='string'?initial:JSON.stringify(initial));const ctx={localStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)},Date,CustomEvent:class{constructor(type,detail){this.type=type;this.detail=detail;}},dispatchEvent(){}};vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/learning.js','utf8'),ctx);ctx.Learning.load();return {L:ctx.Learning,data,storage:ctx.localStorage};}
const now=new Date('2026-11-07T12:00:00Z');
test('watching enrolls without successful recall; likes and notes never grade',()=>{const {L}=setup();L.expose('q1',9,now);L.like('q1');L.note('q1','Recall the posterior territory.');assert.equal(L.get('q1').card.reps,0);assert.equal(L.state.reviews.length,0);assert.equal(L.stats(now).reviewCount,0);assert.equal(L.due([{id:'q1'}],now).length,1);});
test('Good and Again use FSRS; duplicate attempts cannot double-grade',()=>{const {L}=setup();const good=L.grade('q1',true,'attempt1','review',now);const again=L.grade('q2',false,'attempt2','review',now);assert.equal(good.rating,'Good');assert.equal(again.rating,'Again');assert.ok(Date.parse(good.due)>Date.parse(again.due));assert.equal(L.grade('q1',false,'attempt1','review',now).duplicate,true);assert.equal(L.get('q1').card.reps,1);assert.equal(L.stats(now).reviewCount,2);assert.equal(L.stats(now).accuracy,50);});
test('early practice preserves the scheduled due date',()=>{const {L}=setup();L.grade('q1',true,'first','review',now);const before=JSON.stringify(L.get('q1').card);const result=L.grade('q1',false,'practice','practice',new Date(now.getTime()+1000));assert.equal(result.scheduled,false);assert.equal(JSON.stringify(L.get('q1').card),before);assert.equal(L.stats(now).reviewCount,1);});
test('backup round-trip retains dates, notes and recall history',()=>{const a=setup(),b=setup();a.L.grade('q1',true,'first','review',now);a.L.note('q1','Local only');a.L.setSetting('retention',.95);b.L.restore(JSON.parse(JSON.stringify(a.L.backup())));assert.equal(b.L.get('q1').note,'Local only');assert.equal(b.L.state.settings.retention,.95);assert.equal(b.L.get('q1').card.due,a.L.get('q1').card.due);b.L.grade('q1',true,'second','review',new Date(now.getTime()+600001));assert.equal(b.L.get('q1').card.reps,2);});
test('invalid restore never overwrites existing progress',()=>{const {L,data}=setup();L.grade('q1',true,'first','review',now);const before=data.get(L.storageKey);const bad=L.backup();const raw=JSON.parse(bad.state[L.storageKey]);raw.lessons.q1.card.due='broken';bad.state[L.storageKey]=JSON.stringify(raw);assert.throws(()=>L.restore(bad));assert.equal(data.get(L.storageKey),before);});
test('daily new limit and due-first feed are based on real enrollment',()=>{const {L}=setup();L.setSetting('newPerDay',1);L.expose('q2',9,now);const feed=L.getFeed([{id:'q1'},{id:'q2'},{id:'q3'}],now);assert.equal(feed.length,1);assert.equal(feed[0].id,'q2');L.grade('q2',true,'answer','review',now);assert.equal(L.getFeed([{id:'q1'},{id:'q2'}],now)[0].id,'q2');});
test('a changed retention updates future scheduling without deleting history',()=>{const {L}=setup();L.grade('q1',true,'first','review',now);L.setSetting('retention',.97);assert.equal(L.get('q1').card.reps,1);assert.equal(L.state.reviews.length,1);assert.throws(()=>L.setSetting('retention',1));});

test('failed disk writes roll back grades and allow the same attempt to retry',()=>{const {L,data,storage}=setup();L.expose('q1',9,now);const before=JSON.stringify(L.state),persisted=data.get(L.storageKey),write=storage.setItem;storage.setItem=()=>{throw new Error('Disk full');};assert.throws(()=>L.grade('q1',true,'retry-me','review',now),/could not be saved/);assert.equal(JSON.stringify(L.state),before);assert.equal(data.get(L.storageKey),persisted);assert.throws(()=>L.note('q1','Unsaved'),/could not be saved/);assert.equal(L.get('q1').note,'');assert.throws(()=>L.setSetting('speed',2),/could not be saved/);assert.equal(L.state.settings.speed,1);storage.setItem=write;const retried=L.grade('q1',true,'retry-me','review',now);assert.equal(retried.duplicate,false);assert.equal(L.get('q1').card.reps,1);assert.equal(L.state.reviews.length,1);L.load();assert.equal(L.get('q1').card.reps,1);});

test('older saved progress and backups default to all daily topics without losing learning history',()=>{
  const original=setup();
  original.L.grade('q1',true,'before-topics','review',now);
  original.L.note('q1','Keep the existing record.');
  const legacy=JSON.parse(original.data.get(original.L.storageKey));
  delete legacy.settings.dailyTopicIds;
  const loaded=setup(legacy);
  assert.equal(loaded.L.loadError,null);
  assert.deepEqual(Array.from(loaded.L.state.settings.dailyTopicIds),[]);
  assert.equal(JSON.stringify(loaded.L.state.lessons),JSON.stringify(legacy.lessons));
  assert.equal(JSON.stringify(loaded.L.state.reviews),JSON.stringify(legacy.reviews));
  const restored=setup();
  restored.L.restore({format:'instaanki-backup-v1',state:{[restored.L.storageKey]:JSON.stringify(legacy)}});
  assert.deepEqual(Array.from(restored.L.state.settings.dailyTopicIds),[]);
  assert.equal(restored.L.get('q1').card.due,original.L.get('q1').card.due);
  assert.equal(restored.L.get('q1').note,'Keep the existing record.');
});

test('daily topic preferences persist canonical IDs once and own their input array',()=>{
  const {L}=setup();
  const selected=['specialty.thoracic','concept.coronary_dominance','specialty.thoracic'];
  L.setSetting('dailyTopicIds',selected);
  selected.push('specialty.vascular');
  assert.deepEqual(Array.from(L.state.settings.dailyTopicIds),['specialty.thoracic','concept.coronary_dominance']);
  L.load();
  assert.deepEqual(Array.from(L.state.settings.dailyTopicIds),['specialty.thoracic','concept.coronary_dominance']);
  assert.deepEqual(Array.from(setup().L.state.settings.dailyTopicIds),[]);
});

test('backup round-trip and All reset preserve daily topics and scheduled recall separately',()=>{
  const original=setup(),restored=setup();
  original.L.grade('q1',true,'topic-backup','review',now);
  original.L.setSetting('dailyTopicIds',['specialty.cardiac','specialty.thoracic']);
  const backup=JSON.parse(JSON.stringify(original.L.backup()));
  restored.L.restore(backup);
  restored.L.load();
  assert.deepEqual(Array.from(restored.L.state.settings.dailyTopicIds),['specialty.cardiac','specialty.thoracic']);
  const before=JSON.stringify(restored.L.state.lessons);
  restored.L.setSetting('dailyTopicIds',[]);
  restored.L.load();
  assert.deepEqual(Array.from(restored.L.state.settings.dailyTopicIds),[]);
  assert.equal(JSON.stringify(restored.L.state.lessons),before);
  assert.equal(restored.L.state.reviews.length,1);
  assert.equal(restored.L.get('q1').card.due,original.L.get('q1').card.due);
  restored.L.restore(backup);
  assert.deepEqual(Array.from(restored.L.state.settings.dailyTopicIds),['specialty.cardiac','specialty.thoracic']);
});

test('invalid daily topics never overwrite preferences or progress through settings or restore',()=>{
  const {L,data}=setup();
  L.grade('q1',true,'valid-progress','review',now);
  L.setSetting('dailyTopicIds',['specialty.thoracic']);
  const before=JSON.stringify(L.state),persisted=data.get(L.storageKey);
  const invalid=['specialty.thoracic',null,['not a canonical id'],['__proto__'],[7],Array(257).fill('specialty.cardiac')];
  for(const value of invalid){
    assert.throws(()=>L.setSetting('dailyTopicIds',value));
    assert.equal(JSON.stringify(L.state),before);
    assert.equal(data.get(L.storageKey),persisted);
    const backup=L.backup();
    const raw=JSON.parse(backup.state[L.storageKey]);
    raw.settings.dailyTopicIds=value;
    backup.state[L.storageKey]=JSON.stringify(raw);
    assert.throws(()=>L.restore(backup));
    assert.equal(JSON.stringify(L.state),before);
    assert.equal(data.get(L.storageKey),persisted);
  }
});

test('failed preference writes retain the previous topic selection and allow a safe retry',()=>{
  const {L,data,storage}=setup();
  L.setSetting('dailyTopicIds',['specialty.thoracic']);
  const before=JSON.stringify(L.state),persisted=data.get(L.storageKey),write=storage.setItem;
  storage.setItem=()=>{throw new Error('Disk full');};
  assert.throws(()=>L.setSetting('dailyTopicIds',['specialty.cardiac']),/could not be saved/);
  assert.equal(JSON.stringify(L.state),before);
  assert.equal(data.get(L.storageKey),persisted);
  storage.setItem=write;
  L.setSetting('dailyTopicIds',['specialty.cardiac']);
  L.load();
  assert.deepEqual(Array.from(L.state.settings.dailyTopicIds),['specialty.cardiac']);
});
