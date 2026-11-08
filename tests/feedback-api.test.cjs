'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const handler=require('../api/feedback.js');
const TOKEN='s'.repeat(48);
const GH='github-only-server-secret';
const base=()=>({reportId:'feedback-test-abc1',lessonId:'shahzad2015-q001',lessonVersion:2,
  reason:'bad_images',comment:'Image is hard to understand',createdAt:'2026-11-08T08:00:00Z',
  source:{bookId:'shahzad-raja-2015-200-practice-questions',questionNumber:1},
  assetHashes:{'media/mnemonic/q001.png':'a'.repeat(64)}});
function request(body=base(),authorization='Bearer '+TOKEN) {
  return {method:'POST',headers:{authorization,'content-type':'application/json'},body};
}
function response() {
  return {statusCode:200,headers:{},setHeader(k,v){this.headers[k]=v;return this},
    status(n){this.statusCode=n;return this},json(v){this.body=v;return this}};
}
async function withEnv(fn) {
  const old={...process.env},oldFetch=global.fetch;
  process.env.INSTAANKI_REPORT_TOKEN=TOKEN;
  process.env.GITHUB_ISSUES_TOKEN=GH;
  try{await fn()}finally{process.env=old;global.fetch=oldFetch}
}
test('does not accept reports without the configured pairing secret',async()=>{
  await withEnv(async()=>{
    let calls=0;global.fetch=async()=>{calls++;throw Error('Should not call GitHub')};
    const res=response();await handler(request(base(),'Bearer wrong'),res);
    assert.equal(res.statusCode,401);assert.equal(calls,0);
  });
});
test('creates a GitHub issue using only allowlisted lesson metadata',async()=>{
  await withEnv(async()=>{
    const calls=[];global.fetch=async(url,opts)=>{
      calls.push({url,opts});
      if(url.includes('/search/issues'))return {ok:true,json:async()=>({items:[]})};
      return {ok:true,json:async()=>({number:88,html_url:'https://github.com/blsmohamme972-lab/InstaAnki/issues/88'})};
    };
    const sent={...base(),privateNotes:'never send',reviewHistory:[1,2]};
    const res=response();await handler(request(sent),res);
    assert.equal(res.statusCode,200);assert.equal(res.body.issueNumber,88);
    assert.equal(calls.length,2);
    const body=JSON.parse(calls[1].opts.body);
    assert.match(body.body,/shahzad2015-q001/);
    assert.match(body.body,/bad_images/);
    assert.ok(!body.body.includes('privateNotes'));
    assert.ok(!body.body.includes('reviewHistory'));
    assert.ok(!body.body.includes(GH));
  });
});
test('retries return existing matching issue instead of opening a duplicate',async()=>{
  await withEnv(async()=>{
    let calls=0;global.fetch=async(url)=>{
      calls++;assert.match(url,/search\/issues/);
      return {ok:true,json:async()=>({items:[{number:7,html_url:'https://github.com/blsmohamme972-lab/InstaAnki/issues/7',body:'<!-- instaanki-report-id:feedback-test-abc1 -->'}]})};
    };
    const res=response();await handler(request(),res);
    assert.equal(res.statusCode,200);assert.equal(res.body.issueNumber,7);assert.equal(calls,1);
  });
});
test('invalid source binding and large request fail before GitHub',async()=>{
  await withEnv(async()=>{
    let calls=0;global.fetch=async()=>{calls++;throw Error('Unexpected network')};
    const bad={...base(),source:{bookId:'wrong/unsafe',questionNumber:1}};
    const res=response();await handler(request(bad),res);assert.equal(res.statusCode,400);
    const big=response();const req=request({...base(),comment:'x'.repeat(9000)});
    await handler(req,big);assert.equal(big.statusCode,413);assert.equal(calls,0);
  });
});
test('no GitHub credential returns unavailable and never falsely claims success',async()=>{
  await withEnv(async()=>{
    delete process.env.GITHUB_ISSUES_TOKEN;
    const res=response();await handler(request(),res);assert.equal(res.statusCode,503);
    assert.notEqual(res.body.status,'received');
  });
});
