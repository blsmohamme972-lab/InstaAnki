const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const now=new Date('2026-11-07T12:00:00Z');
function setup(initial){
  const data=new Map();if(initial!==undefined)data.set('instaanki.state.v1',typeof initial==='string'?initial:JSON.stringify(initial));
  const storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)};
  const ctx={localStorage:storage,Date,CustomEvent:class{},dispatchEvent(){}};
  vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/learning.js','utf8'),ctx);ctx.Learning.load();
  return {L:ctx.Learning,data,storage,ctx};
}
const payload={reason:'bad_sound',comment:'The voice is clipped at the end.',lessonVersion:2,source:{bookId:'shahzad-raja-2015-200-practice-questions',questionNumber:5,sourceRecordSha256:'a'.repeat(64)},assetHashes:{'media/audio/q005.mp3':'b'.repeat(64)}};

test('local reports retain stable identity and content version without grading or exposing notes',()=>{
  const {L}=setup();L.grade('q5',true,'recall','review',now);L.note('q5','Private note should never be exported.');
  const card=JSON.stringify(L.get('q5').card),history=JSON.stringify(L.state.reviews);
  const report=L.reportFeedback('q5',{...payload,note:'secret',reviews:L.state.reviews,source:{...payload.source,rawBookText:'private book'}},now);
  assert.equal(report.lessonId,'q5');assert.equal(report.lessonVersion,2);assert.equal(report.reason,'bad_sound');
  L.load();assert.equal(L.getFeedback('q5')[0].id,report.id);
  assert.equal(JSON.stringify(L.get('q5').card),card);assert.equal(JSON.stringify(L.state.reviews),history);
  const exported=JSON.parse(L.exportFeedback());assert.equal(exported.format,'instaanki-feedback-v1');assert.equal(exported.reports[0].assetHashes['media/audio/q005.mp3'],'b'.repeat(64));
  assert.equal(exported.reports[0].source.rawBookText,undefined);assert.equal(exported.reports[0].note,undefined);
  assert.ok(!L.exportFeedback().includes('Private note'));assert.equal(exported.state,undefined);assert.equal(exported.reviews,undefined);
});

test('hide and dislike are reversible preferences independent of the same FSRS card',()=>{
  const {L}=setup();L.expose('q5',9,now);L.grade('q5',true,'once','review',now);L.like('q5');
  const card=JSON.stringify(L.get('q5').card),history=JSON.stringify(L.state.reviews),later=new Date('2027-11-07T12:00:00Z');
  L.setHidden('q5',true);L.setDisliked('q5',true);
  assert.equal(L.getFeed([{id:'q5'}],later).length,0);assert.equal(L.due([{id:'q5'}],later).length,0);assert.equal(L.stats(later).dueCount,0);
  assert.equal(L.get('q5').liked,true);assert.equal(JSON.stringify(L.get('q5').card),card);
  L.load();assert.equal(L.get('q5').hidden,true);assert.equal(L.get('q5').disliked,true);
  L.setHidden('q5',false);L.setDisliked('q5',false);
  assert.equal(L.due([{id:'q5',version:3}],later).length,1);assert.equal(JSON.stringify(L.get('q5').card),card);assert.equal(JSON.stringify(L.state.reviews),history);
});

test('legacy backup migration and new backup round-trip preserve progress and reports',()=>{
  const {L}=setup();L.grade('q5',false,'old','review',now);L.note('q5','Remember this.');
  const legacy=JSON.parse(JSON.stringify(L.state));delete legacy.feedback;delete legacy.lessons.q5.hidden;delete legacy.lessons.q5.disliked;
  const migrated=setup(legacy).L;assert.equal(migrated.loadError,null);assert.equal(migrated.getFeedback().length,0);assert.equal(migrated.get('q5').hidden,false);
  assert.equal(JSON.stringify(migrated.get('q5').card),JSON.stringify(L.get('q5').card));assert.equal(migrated.get('q5').note,'Remember this.');
  migrated.reportFeedback('q5',payload,now);migrated.setHidden('q5',true);
  const restored=setup().L;restored.restore(JSON.parse(JSON.stringify(migrated.backup())));restored.load();
  assert.equal(JSON.stringify(restored.state),JSON.stringify(migrated.state));
});

test('invalid report backups and failed writes leave committed learning state untouched',()=>{
  const {L,data,storage}=setup();L.grade('q5',true,'keep','review',now);const report=L.reportFeedback('q5',payload,now);
  const before=JSON.stringify(L.state),persisted=data.get(L.storageKey);
  for(const mutate of [r=>r.reason='unknown',r=>r.comment='x'.repeat(4001),r=>r.lessonId='__proto__',r=>r.createdAt='invalid',r=>r.assetHashes.audio='not-a-hash']){
    const backup=L.backup(),raw=JSON.parse(backup.state[L.storageKey]);mutate(raw.feedback[0]);backup.state[L.storageKey]=JSON.stringify(raw);
    assert.throws(()=>L.restore(backup));assert.equal(JSON.stringify(L.state),before);assert.equal(data.get(L.storageKey),persisted);
  }
  const duplicate=L.backup(),raw=JSON.parse(duplicate.state[L.storageKey]);raw.feedback.push(report);duplicate.state[L.storageKey]=JSON.stringify(raw);assert.throws(()=>L.restore(duplicate),/Duplicate/);
  const write=storage.setItem;storage.setItem=()=>{throw new Error('disk full');};
  assert.throws(()=>L.reportFeedback('q5',payload,now),/could not be saved/);assert.throws(()=>L.setHidden('q5',true),/could not be saved/);
  assert.equal(JSON.stringify(L.state),before);assert.equal(data.get(L.storageKey),persisted);storage.setItem=write;
  L.reportFeedback('q5',payload,now);assert.equal(L.getFeedback().length,2);
});

test('content replacement with the same ID keeps old reports attached to the reported version',()=>{
  const {L}=setup();L.grade('q5',true,'before-update','review',now);L.reportFeedback('q5',payload,now);
  const card=JSON.stringify(L.get('q5').card);const replacement={id:'q5',version:3,source:{bookId:payload.source.bookId}};
  const visible=L.getFeed([replacement],now);assert.equal(visible[0].version,3);assert.equal(L.getFeedback('q5')[0].lessonVersion,2);
  assert.equal(JSON.stringify(L.get('q5').card),card);assert.equal(L.state.reviews.length,1);
});

test('reports are never shared on save and require an explicit chooser action',()=>{
  const {L,ctx,storage}=setup();let shared=null;
  assert.equal(L.shareFeedback(),false);
  ctx.AndroidNative={...storage,getAppInfo:()=>JSON.stringify({version:'0.1.2',versionCode:3,packageName:'com.instaanki.app',platform:'Android'}),shareFeedback:text=>{shared=JSON.parse(text);return true;}};
  L.reportFeedback('q5',{...payload,reason:'audio_issue'},now);assert.equal(shared,null);assert.equal(L.getFeedback()[0].reason,'bad_sound');
  assert.equal(L.shareFeedback(),true);assert.equal(shared.reports[0].app.versionCode,3);assert.equal(shared.reports[0].lessonId,'q5');
});

test('mutable input and returned reports cannot alter persisted feedback',()=>{
  const {L}=setup();const input=JSON.parse(JSON.stringify(payload));const result=L.reportFeedback('q5',input,now);
  input.assetHashes['media/audio/q005.mp3']='c'.repeat(64);result.comment='mutated';L.getFeedback()[0].reason='other';
  assert.equal(L.getFeedback()[0].comment,payload.comment);assert.equal(L.getFeedback()[0].assetHashes['media/audio/q005.mp3'],'b'.repeat(64));
  assert.throws(()=>L.setHidden('__proto__',true),/Invalid lesson ID/);
});
