import { createEmptyCard, fsrs, Rating, TypeConvert } from 'ts-fsrs';

// Exposure and recall are deliberately separate. Only an answered assessment
// changes an FSRS card. Stable source IDs survive new artwork/content versions.
const KEY = 'instaanki.state.v1';
const defaults = {speed:1, retention:0.9, newPerDay:10, dailyTopicIds:[], autoPlay:true, autoCheckUpdates:true, reduceMotion:false};
const rates = [0.75,1,1.25,1.5,1.75,2];
const feedbackReasons = ['bad_sound','bad_images','bad_timing','bad_mcq','wrong_source','other'];
const feedbackAliases = {audio_issue:'bad_sound',image_issue:'bad_images',sync_issue:'bad_timing',factual_error:'bad_mcq',unclear_explanation:'other'};
const maxFeedback = 5000;
const safeId = id => typeof id === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$/.test(id) && !['__proto__','constructor','prototype'].includes(id);
const fresh = () => ({schemaVersion:1, settings:{...defaults,dailyTopicIds:[]}, lessons:{}, reviews:[],feedback:[]});
const dateKey = value => {const d=new Date(value);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
const validDate = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
let state=fresh(), loadError=null, committed=JSON.stringify(state);

function storage(){
  if (globalThis.AndroidNative) return globalThis.AndroidNative;
  return globalThis.localStorage;
}
function notify(kind,id){
  if(typeof globalThis.dispatchEvent==='function')globalThis.dispatchEvent(new CustomEvent('learning:changed',{detail:{kind,id}}));
}
function save(kind='state',id){
  if(loadError){state=JSON.parse(committed);throw new Error('Saved progress could not be read. Restore a valid backup before making changes.');}
  const pending=JSON.stringify(state);
  try{storage().setItem(KEY,pending);}
  catch(error){
    // A failed disk write must not leave a grade or attempt ID in memory.
    // Otherwise retrying the answer could look like an already-saved result.
    state=JSON.parse(committed);
    throw new Error('Your change could not be saved. Free some storage and try again.');
  }
  committed=pending;
  notify(kind,id);
}
function assertState(value){
  if(!value||value.schemaVersion!==1||typeof value.lessons!=='object'||value.lessons===null||Array.isArray(value.lessons)||!Array.isArray(value.reviews))throw new Error('Unsupported progress backup.');
  if(Object.keys(value.lessons).length>20000||value.reviews.length>200000)throw new Error('Progress backup is too large.');
  const result=fresh();
  const s=value.settings||{};
  for(const key of Object.keys(defaults))if(s[key]!==undefined)result.settings[key]=checkedSetting(key,s[key]);
  for(const [id,record] of Object.entries(value.lessons)){
    if(!safeId(id)||!record||typeof record!=='object'||Array.isArray(record))throw new Error('Invalid lesson progress.');
    if(record.note!==undefined&&(typeof record.note!=='string'||record.note.length>16000))throw new Error('Invalid lesson note.');
    if(record.enrolledAt!==null&&record.enrolledAt!==undefined&&!validDate(record.enrolledAt))throw new Error('Invalid enrollment date.');
    if(record.card){
      if(!validDate(record.card.due)||record.card.last_review&&!validDate(record.card.last_review))throw new Error('Invalid review date.');
      for(const k of ['stability','difficulty','scheduled_days','reps','lapses','learning_steps','state'])if(!Number.isFinite(record.card[k])||record.card[k]<0)throw new Error('Invalid review card.');
      if(record.card.state>3||record.card.difficulty>10)throw new Error('Invalid review card state.');
      TypeConvert.card(record.card);
    }
    if(!Number.isFinite(record.watchedSeconds??0)||(record.watchedSeconds??0)<0)throw new Error('Invalid watch time.');
    for(const key of ['hidden','disliked'])if(record[key]!==undefined&&typeof record[key]!=='boolean')throw new Error('Invalid lesson preference.');
    result.lessons[id]={liked:record.liked===true,hidden:record.hidden===true,disliked:record.disliked===true,note:record.note||'',watchedSeconds:record.watchedSeconds||0,enrolledAt:record.enrolledAt||null,card:record.card||null};
  }
  for(const review of value.reviews){
    if(!review||!safeId(review.lessonId)||typeof review.attemptId!=='string'||review.attemptId.length>180||!validDate(review.at)||typeof review.correct!=='boolean'||!['Good','Again'].includes(review.rating))throw new Error('Invalid review history.');
    result.reviews.push(review);
  }
  if(value.feedback!==undefined){
    if(!Array.isArray(value.feedback)||value.feedback.length>maxFeedback)throw new Error('Invalid feedback reports.');
    const ids=new Set();
    for(const report of value.feedback){
      const checked=checkedFeedback(report);
      if(ids.has(checked.id))throw new Error('Duplicate feedback report ID.');
      ids.add(checked.id);result.feedback.push(checked);
    }
  }
  return result;
}
function checkedFeedback(value){
  if(!value||typeof value!=='object'||Array.isArray(value)||!safeId(value.id)||!safeId(value.lessonId)||!validDate(value.createdAt))throw new Error('Invalid feedback report.');
  const reason=feedbackAliases[value.reason]||value.reason;
  if(!feedbackReasons.includes(reason))throw new Error('Choose a valid feedback reason.');
  if(typeof value.comment!=='string'||value.comment.length>4000)throw new Error('Keep feedback comments under 4,000 characters.');
  const version=value.lessonVersion??null;
  if(version!==null&&!(Number.isInteger(version)&&version>=0&&version<=1e9)&&!(typeof version==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/.test(version)))throw new Error('Invalid feedback lesson version.');
  const source={};
  if(value.source!==undefined){
    if(!value.source||typeof value.source!=='object'||Array.isArray(value.source))throw new Error('Invalid feedback source.');
    if(value.source.bookId!==undefined){if(!safeId(value.source.bookId))throw new Error('Invalid feedback book ID.');source.bookId=value.source.bookId;}
    if(value.source.questionNumber!==undefined){if(!Number.isInteger(value.source.questionNumber)||value.source.questionNumber<1||value.source.questionNumber>1e7)throw new Error('Invalid feedback source question.');source.questionNumber=value.source.questionNumber;}
    for(const key of ['sourceRecordSha256','extractionSha256'])if(value.source[key]!==undefined){if(typeof value.source[key]!=='string'||!/^[a-f0-9]{64}$/i.test(value.source[key]))throw new Error('Invalid feedback source checksum.');source[key]=value.source[key].toLowerCase();}
  }
  const assetHashes={};
  if(value.assetHashes!==undefined){
    if(!value.assetHashes||typeof value.assetHashes!=='object'||Array.isArray(value.assetHashes)||Object.keys(value.assetHashes).length>200)throw new Error('Invalid feedback asset checksums.');
    for(const [path,hash] of Object.entries(value.assetHashes)){
      if(!/^[A-Za-z0-9][A-Za-z0-9._/-]{0,319}$/.test(path)||path.split('/').some(x=>!x||x==='.'||x==='..'||['__proto__','constructor','prototype'].includes(x))||typeof hash!=='string'||!/^[a-f0-9]{64}$/i.test(hash))throw new Error('Invalid feedback asset checksum.');
      assetHashes[path]=hash.toLowerCase();
    }
  }
  const app={};
  if(value.app!==undefined){
    if(!value.app||typeof value.app!=='object'||Array.isArray(value.app))throw new Error('Invalid feedback app version.');
    for(const key of ['version','packageName','platform'])if(value.app[key]!==undefined){if(typeof value.app[key]!=='string'||value.app[key].length>120)throw new Error('Invalid feedback app version.');app[key]=value.app[key];}
    if(value.app.versionCode!==undefined){if(!Number.isInteger(value.app.versionCode)||value.app.versionCode<0)throw new Error('Invalid feedback app version.');app.versionCode=value.app.versionCode;}
  }
  // Deliberate allowlist: notes, grades, profile fields and arbitrary payload keys
  // never enter the shareable report, even if a caller supplies them accidentally.
  return {id:value.id,lessonId:value.lessonId,lessonVersion:version,reason,comment:value.comment,createdAt:value.createdAt,source,assetHashes,app};
}
function reportFeedback(id,details={},now=new Date()){
  if(!safeId(id))throw new Error('Invalid lesson ID.');
  if(!details||typeof details!=='object'||Array.isArray(details))throw new Error('Invalid feedback report.');
  if(state.feedback.length>=maxFeedback)throw new Error('The local feedback limit has been reached. Export your reports before adding more.');
  let app={};
  try{if(typeof globalThis.AndroidNative?.getAppInfo==='function')app=JSON.parse(globalThis.AndroidNative.getAppInfo());}catch(_){/* Version can remain unknown. */}
  const suffix=typeof globalThis.crypto?.randomUUID==='function'?globalThis.crypto.randomUUID():`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${state.feedback.length}`;
  const report=checkedFeedback({id:`feedback-${suffix}`,lessonId:id,lessonVersion:details.lessonVersion??null,reason:details.reason,comment:details.comment??'',createdAt:new Date(now).toISOString(),source:details.source,assetHashes:details.assetHashes,app});
  state.feedback.push(report);save('feedback',id);
  return JSON.parse(JSON.stringify(report));
}
function getFeedback(id){
  if(id!==undefined&&!safeId(id))throw new Error('Invalid lesson ID.');
  return JSON.parse(JSON.stringify(state.feedback.filter(report=>id===undefined||report.lessonId===id)));
}
function exportFeedback(){
  return JSON.stringify({format:'instaanki-feedback-v1',schemaVersion:1,createdAt:new Date().toISOString(),reports:getFeedback()},null,2);
}
function shareFeedback(){
  if(typeof globalThis.AndroidNative?.shareFeedback!=='function')return false;
  return globalThis.AndroidNative.shareFeedback(exportFeedback())===true;
}
function checkedSetting(key,value){
  if(key==='speed'&&rates.includes(Number(value)))return Number(value);
  if(key==='retention'&&Number.isFinite(Number(value))&&Number(value)>=0.75&&Number(value)<=0.97)return Number(value);
  if(key==='newPerDay'&&Number.isInteger(Number(value))&&Number(value)>=1&&Number(value)<=100)return Number(value);
  if(key==='dailyTopicIds'&&Array.isArray(value)&&value.length<=256&&value.every(safeId))return [...new Set(value)];
  if(['autoPlay','autoCheckUpdates','reduceMotion'].includes(key)&&typeof value==='boolean')return value;
  throw new Error('Invalid setting.');
}
function get(id){
  if(!safeId(id))throw new Error('Invalid lesson ID.');
  return state.lessons[id]||{liked:false,hidden:false,disliked:false,note:'',watchedSeconds:0,enrolledAt:null,card:null};
}
function edit(id){const record=get(id);return state.lessons[id]||(state.lessons[id]={...record});}
function enrolledToday(now=new Date()){
  const today=dateKey(now);return Object.values(state.lessons).filter(x=>x.enrolledAt&&dateKey(x.enrolledAt)===today).length;
}
function enroll(record,now){
  if(!record.card){record.enrolledAt=new Date(now).toISOString();record.card=JSON.parse(JSON.stringify(createEmptyCard(new Date(now))));}
}
function load(){
  try{const raw=storage().getItem(KEY);state=raw?assertState(JSON.parse(raw)):fresh();loadError=null;}
  catch(error){loadError=String(error.message||error);state=fresh();}
  committed=JSON.stringify(state);
  return state;
}
function expose(id,seconds,now=new Date()){
  const dt=Number(seconds);
  if(!Number.isFinite(dt)||dt<=0||dt>30)return get(id);
  const record=edit(id);record.watchedSeconds+=dt;
  if(record.watchedSeconds>=8&&!record.card&&enrolledToday(now)<state.settings.newPerDay)enroll(record,now);
  save('exposure',id);return record;
}
function grade(id,correct,attemptId,mode='review',now=new Date()){
  if(typeof correct!=='boolean'||typeof attemptId!=='string'||attemptId.length<1||attemptId.length>180)throw new Error('Invalid assessment result.');
  const previous=state.reviews.find(x=>x.attemptId===attemptId);
  if(previous)return {...previous,duplicate:true,scheduled:!previous.practice};
  const record=edit(id),practice=mode==='practice';
  const rating=correct?'Good':'Again';
  let log=null;
  if(!practice){
    enroll(record,now);
    const scheduler=fsrs({request_retention:state.settings.retention,enable_fuzz:false});
    const answer=scheduler.next(TypeConvert.card(record.card),new Date(now),correct?Rating.Good:Rating.Again);
    record.card=JSON.parse(JSON.stringify(answer.card));log=answer.log;
  }
  const review={lessonId:id,attemptId,at:new Date(now).toISOString(),correct,rating,practice,due:record.card?.due||null,log};
  state.reviews.push(review);save('review',id);
  return {...review,scheduled:!practice,duplicate:false};
}
function due(lessons,now=new Date()){
  return lessons.filter(l=>{const r=get(l.id);return !r.hidden&&r.card&&new Date(r.card.due).getTime()<=new Date(now).getTime();}).sort((a,b)=>new Date(get(a.id).card.due)-new Date(get(b.id).card.due));
}
function getFeed(lessons,now=new Date()){
  lessons=lessons.filter(l=>!get(l.id).hidden);
  const dueLessons=due(lessons,now),dueIds=new Set(dueLessons.map(x=>x.id));
  const available=Math.max(0,state.settings.newPerDay-enrolledToday(now));
  const newLessons=lessons.filter(l=>!get(l.id).card).slice(0,available);
  const existing=lessons.filter(l=>get(l.id).card&&!dueIds.has(l.id));
  return [...dueLessons,...newLessons,...existing];
}
function stats(now=new Date()){
  const reviews=state.reviews.filter(x=>!x.practice),correct=reviews.filter(x=>x.correct).length;
  const records=Object.values(state.lessons),days=new Set(reviews.map(x=>dateKey(x.at)));
  const cursor=new Date(now);let streak=0;
  if(!days.has(dateKey(cursor)))cursor.setDate(cursor.getDate()-1);
  while(days.has(dateKey(cursor))){streak++;cursor.setDate(cursor.getDate()-1);}
  return {reviewCount:reviews.length,correctCount:correct,accuracy:reviews.length?Math.round(100*correct/reviews.length):0,learnedCount:records.filter(x=>x.card?.reps>0).length,enrolledCount:records.filter(x=>x.card).length,dueCount:records.filter(x=>!x.hidden&&x.card&&new Date(x.card.due)<=new Date(now)).length,watchedSeconds:Math.round(records.reduce((a,x)=>a+x.watchedSeconds,0)),streak};
}
function backup(){return {format:'instaanki-backup-v1',createdAt:new Date().toISOString(),state:{[KEY]:JSON.stringify(state)}};}
function restore(document){
  if(document?.format!=='instaanki-backup-v1'||typeof document.state?.[KEY]!=='string')throw new Error('This is not an InstaAnki progress backup.');
  const restored=assertState(JSON.parse(document.state[KEY]));
  // Write the validated snapshot before replacing the in-memory state.
  const snapshot=JSON.stringify(restored);
  storage().setItem(KEY,snapshot);state=restored;committed=snapshot;loadError=null;notify('restore');return state;
}
export const Learning={
  load,get,expose,grade,due,getFeed,stats,backup,restore,reportFeedback,getFeedback,exportFeedback,shareFeedback,
  get state(){return state;},get loadError(){return loadError;},
  like(id){const r=edit(id);r.liked=!r.liked;save('like',id);return r.liked;},
  setHidden(id,value){if(typeof value!=='boolean')throw new Error('Invalid hidden preference.');const r=edit(id);r.hidden=value;save('hidden',id);return value;},
  setDisliked(id,value){if(typeof value!=='boolean')throw new Error('Invalid dislike preference.');const r=edit(id);r.disliked=value;save('disliked',id);return value;},
  note(id,text){if(typeof text!=='string'||text.length>16000)throw new Error('Keep notes under 16,000 characters.');edit(id).note=text;save('note',id);},
  setSetting(key,value){state.settings[key]=checkedSetting(key,value);save('settings');return state.settings[key];},
  feedbackReasons:[...feedbackReasons],algorithm:'FSRS 6',version:'ts-fsrs 6.0.0',storageKey:KEY
};
globalThis.Learning=Learning;
