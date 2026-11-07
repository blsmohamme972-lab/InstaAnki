import { createEmptyCard, fsrs, Rating, TypeConvert } from 'ts-fsrs';

// Exposure and recall are deliberately separate. Only an answered assessment
// changes an FSRS card. Stable source IDs survive new artwork/content versions.
const KEY = 'instaanki.state.v1';
const defaults = {speed:1, retention:0.9, newPerDay:10, dailyTopicIds:[], autoPlay:true, autoCheckUpdates:true, reduceMotion:false};
const rates = [0.75,1,1.25,1.5,1.75,2];
const safeId = id => typeof id === 'string' && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,119}$/.test(id) && !['__proto__','constructor','prototype'].includes(id);
const fresh = () => ({schemaVersion:1, settings:{...defaults,dailyTopicIds:[]}, lessons:{}, reviews:[]});
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
    result.lessons[id]={liked:record.liked===true,note:record.note||'',watchedSeconds:record.watchedSeconds||0,enrolledAt:record.enrolledAt||null,card:record.card||null};
  }
  for(const review of value.reviews){
    if(!review||!safeId(review.lessonId)||typeof review.attemptId!=='string'||review.attemptId.length>180||!validDate(review.at)||typeof review.correct!=='boolean'||!['Good','Again'].includes(review.rating))throw new Error('Invalid review history.');
    result.reviews.push(review);
  }
  return result;
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
  return state.lessons[id]||{liked:false,note:'',watchedSeconds:0,enrolledAt:null,card:null};
}
function edit(id){return state.lessons[id]||(state.lessons[id]={...get(id)});}
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
  return lessons.filter(l=>{const c=get(l.id).card;return c&&new Date(c.due).getTime()<=new Date(now).getTime();}).sort((a,b)=>new Date(get(a.id).card.due)-new Date(get(b.id).card.due));
}
function getFeed(lessons,now=new Date()){
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
  return {reviewCount:reviews.length,correctCount:correct,accuracy:reviews.length?Math.round(100*correct/reviews.length):0,learnedCount:records.filter(x=>x.card?.reps>0).length,enrolledCount:records.filter(x=>x.card).length,dueCount:records.filter(x=>x.card&&new Date(x.card.due)<=new Date(now)).length,watchedSeconds:Math.round(records.reduce((a,x)=>a+x.watchedSeconds,0)),streak};
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
  load,get,expose,grade,due,getFeed,stats,backup,restore,
  get state(){return state;},get loadError(){return loadError;},
  like(id){const r=edit(id);r.liked=!r.liked;save('like',id);return r.liked;},
  note(id,text){if(typeof text!=='string'||text.length>16000)throw new Error('Keep notes under 16,000 characters.');edit(id).note=text;save('note',id);},
  setSetting(key,value){state.settings[key]=checkedSetting(key,value);save('settings');return state.settings[key];},
  algorithm:'FSRS 6',version:'ts-fsrs 6.0.0',storageKey:KEY
};
globalThis.Learning=Learning;
