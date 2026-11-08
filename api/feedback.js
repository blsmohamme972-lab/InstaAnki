'use strict';
// Opt-in, single-owner report receiver for InstaAnki. Deploy on a trusted HTTPS
// server; never add either token to an APK, browser asset, or public repository.
const crypto = require('node:crypto');
const REPO = 'blsmohamme972-lab/InstaAnki';
const REASONS = new Set(['bad_sound','bad_images','bad_timing','bad_mcq','wrong_source','other']);
const ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/;
const HASH = /^[0-9a-f]{64}$/i;
const MAX_BYTES = 8192;
function equalSecret(header, configured) {
  if (!configured || typeof configured !== 'string' || configured.length < 32) return false;
  const value = typeof header === 'string' && header.startsWith('Bearer ') ? header.slice(7) : '';
  const a = crypto.createHash('sha256').update(value).digest();
  const b = crypto.createHash('sha256').update(configured).digest();
  return value.length >= 32 && crypto.timingSafeEqual(a,b);
}
function parseReport(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw Error('Invalid report');
  const { reportId, lessonId, lessonVersion, reason, comment, createdAt, source, assetHashes } = raw;
  if (!ID.test(reportId || '') || !ID.test(lessonId || '')) throw Error('Invalid report ID or lesson ID');
  if (!REASONS.has(reason)) throw Error('Invalid reason');
  if (!Number.isInteger(lessonVersion) || lessonVersion < 1 || lessonVersion > 1000000) throw Error('Invalid lesson revision');
  if (typeof comment !== 'string' || comment.length > 1000) throw Error('Invalid comment');
  if (typeof createdAt !== 'string' || !Number.isFinite(Date.parse(createdAt))) throw Error('Invalid timestamp');
  if (!source || typeof source !== 'object' || Array.isArray(source) ||
      !ID.test(source.bookId || '') || !Number.isInteger(source.questionNumber) ||
      source.questionNumber < 1 || source.questionNumber > 1000000) throw Error('Invalid source binding');
  const pairs = Object.entries(assetHashes || {});
  if (pairs.length > 10 || pairs.some(([p,h]) => !/^[A-Za-z0-9][A-Za-z0-9._/-]{0,159}$/.test(p) ||
     p.split('/').some(x=>!x||x==='.'||x==='..') || typeof h !== 'string' || !HASH.test(h))) throw Error('Invalid asset fingerprints');
  return { reportId, lessonId, lessonVersion, reason, comment,
    createdAt: new Date(createdAt).toISOString(),
    source: { bookId:source.bookId,questionNumber:source.questionNumber },
    assetHashes:Object.fromEntries(pairs) };
}
function description(r) {
  const marker = '<!-- instaanki-report-id:' + r.reportId + ' -->';
  const imageHashes = Object.entries(r.assetHashes).map(([p,h])=>'\`'+p+'\` — \`'+h+'\`').join('\n') || 'Not supplied';
  return [marker,'## In-app lesson report','',
    '| Field | Value |','| --- | --- |',
    '| Report ID | \`'+r.reportId+'\` |',
    '| Lesson ID | \`'+r.lessonId+'\` |',
    '| Revision | '+r.lessonVersion+' |',
    '| Reason | \`'+r.reason+'\` |',
    '| Book/question | \`'+r.source.bookId+'\` / '+r.source.questionNumber+' |',
    '| Reported at | '+r.createdAt+' |','',
    '### Comment',
    r.comment ? r.comment.replace(/[<>]/g,'') : '(No comment)',
    '','### Asset SHA-256 references',imageHashes,'',
    'This report does not authorize automatic image generation or replacement. Verify source binding, medical facts and revision before publishing.'].join('\n');
}
async function githubRequest(token, path, opts={}) {
  const response = await fetch('https://api.github.com'+path, {
    ...opts, headers:{'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,
       'X-GitHub-Api-Version':'2022-11-28','User-Agent':'InstaAnki-Report-Receiver',
       ...(opts.body?{'Content-Type':'application/json'}:{})}});
  if (!response.ok) throw Error('GitHub request failed');
  return response.json();
}
async function findIssue(token,reportId) {
  const marker='instaanki-report-id:'+reportId;
  const q=encodeURIComponent('repo:'+REPO+' is:issue in:body "'+marker+'"');
  const data=await githubRequest(token,'/search/issues?q='+q+'&per_page=5');
  return (data.items||[]).find(i=>typeof i.body==='string'&&i.body.includes('<!-- '+marker+' -->'))||null;
}
module.exports = async function handler(req,res) {
  res.setHeader('Cache-Control','no-store');
  if (req.method !== 'POST') {res.setHeader('Allow','POST');return res.status(405).json({error:'Method not allowed'});}
  if (!equalSecret(req.headers.authorization,process.env.INSTAANKI_REPORT_TOKEN))
    return res.status(401).json({error:'Unauthorized'});
  const token=process.env.GITHUB_ISSUES_TOKEN;
  if (!token) return res.status(503).json({error:'Reporting is not configured'});
  const type=String(req.headers['content-type']||'');
  if (!type.startsWith('application/json')) return res.status(415).json({error:'Expected JSON'});
  if (Number(req.headers['content-length']||0)>MAX_BYTES) return res.status(413).json({error:'Report too large'});
  try {
    const raw=typeof req.body==='string'?JSON.parse(req.body):req.body;
    if (Buffer.byteLength(JSON.stringify(raw||{}),'utf8')>MAX_BYTES) return res.status(413).json({error:'Report too large'});
    const r=parseReport(raw);
    let issue=await findIssue(token,r.reportId);
    if (!issue) issue=await githubRequest(token,'/repos/'+REPO+'/issues',{method:'POST',
      body:JSON.stringify({title:'[In-app] '+r.lessonId+' — '+r.reason,body:description(r)})});
    return res.status(200).json({status:'received',id:r.reportId,issueNumber:issue.number,issueUrl:issue.html_url});
  } catch(error) {
    if (/^Invalid |^Unexpected token/.test(String(error.message))) return res.status(400).json({error:'Invalid report'});
    return res.status(502).json({error:'Unable to deliver report; retry later'});
  }
};
