const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {loadRajaStarterFixture,routeRajaStarterFixture}=require('./helpers/raja-starter-fixture.cjs');
const root=path.resolve(__dirname,'..'),web=path.join(root,'web');
const fixture=loadRajaStarterFixture(web),lessons=fixture.lessons;
const mime={'.html':'text/html','.js':'application/javascript','.json':'application/json','.css':'text/css','.mp3':'audio/mpeg','.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.ogg':'audio/ogg'};
const csp="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; media-src 'self' blob:; connect-src 'self' https:; font-src 'self' data:; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'";
const server=http.createServer((req,res)=>{
 let rel=decodeURIComponent(new URL(req.url,'http://local').pathname).replace(/^\//,'')||'index.html';
 if(rel.startsWith('content/test-pack/'))rel=rel.slice('content/test-pack/'.length);
 let file=rel.startsWith('private-content/')?path.join(root,'private-content/app-assets',rel.slice(16)):path.join(web,rel);
 if(rel==='private-content/book-cover.jpeg'&&!fs.existsSync(file))file=path.join(root,'private-content/book-cover.jpeg');
 if(!file.startsWith(root+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end('Not found');return;}
 const data=fs.readFileSync(file);res.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');res.setHeader('Content-Security-Policy',csp);res.setHeader('Accept-Ranges','bytes');
 if(req.headers.range){const match=/bytes=(\d+)-(\d*)/.exec(req.headers.range);if(match){const start=Number(match[1]),end=Math.min(data.length-1,match[2]?Number(match[2]):data.length-1);res.writeHead(206,{'Content-Range':`bytes ${start}-${end}/${data.length}`,'Content-Length':end-start+1});res.end(data.subarray(start,end+1));return;}}
 res.setHeader('Content-Length',data.length);res.end(data);
});
const results=[];
async function check(name,fn){await fn();const scoped=fixture.label+': '+name;results.push(scoped);console.log('PASS '+scoped);}
async function until(page,predicate,arg,options={}){const end=Date.now()+(options.timeout||10000);while(Date.now()<end){if(await page.evaluate(predicate,arg))return;await page.waitForTimeout(100);}throw new Error('Browser condition timed out');}
async function main(){
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 const browser=await chromium.launch({headless:true});
 const ctx=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,hasTouch:true,isMobile:true});
 await routeRajaStarterFixture(ctx,fixture);
 const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://raw.githubusercontent.com/blsmohamme972-lab/InstaAnki/main/content/catalog-v2.json',r=>r.fulfill({json:{schemaVersion:1,packs:[],latestApp:{version:'0.1.0',versionCode:1,url:'https://github.com/blsmohamme972-lab/InstaAnki/releases'}}}));
 await page.addInitScript(()=>{if(!localStorage.getItem('instaanki.state.v1'))localStorage.setItem('instaanki.state.v1',JSON.stringify({schemaVersion:1,settings:{autoPlay:false,autoCheckUpdates:false},lessons:{},reviews:[]}));});
 await page.goto(origin);await page.waitForSelector('#lesson-card:not([hidden])');
 await check('all three lessons load; real MP3 metadata decodes',async()=>{assert.equal(await page.locator('#lesson-position').textContent(),'01 / 03');await until(page,()=>document.querySelector('audio').readyState>=1);const d=await page.locator('audio').evaluate(a=>a.duration);assert.ok(Math.abs(d-lessons[0].durationSeconds)<.2);});
 await check('actual playback automatically enrolls without grading',async()=>{await page.locator('#play-button').click();await until(page,()=>Learning.get('shahzad2015-q054').enrolledAt!==null,{},{timeout:16000});await page.locator('#play-button').click();const r=await page.evaluate(()=>({card:Learning.get('shahzad2015-q054').card,reviews:Learning.stats().reviewCount}));assert.equal(r.card.reps,0);assert.equal(r.reviews,0);});
 await check('seek shows an uncropped clinical figure and its license',async()=>{await page.locator('audio').evaluate((a,t)=>{a.currentTime=t;},lessons[0].scenes[1].start+.5);await until(page,()=>document.querySelector('#visual-stage').classList.contains('is-real'));assert.equal(await page.locator('#lesson-image').evaluate(e=>getComputedStyle(e).objectFit),'contain');assert.match(await page.locator('#real-image-badge').textContent(),/CC BY 4/);});
 await check('speed change persists and scene state follows seeking',async()=>{await page.locator('#speed-button').click();await page.locator('[data-speed="1.5"]').click();assert.equal(await page.locator('audio').evaluate(a=>a.playbackRate),1.5);await page.locator('audio').evaluate((a,t)=>a.currentTime=t,lessons[0].scenes[2].start+1);await until(page,t=>document.querySelector('#lesson-caption').textContent===t,lessons[0].scenes[2].caption);});
 await check('narrated clinical ending precedes MCQ, correct answer schedules Good once',async()=>{
  const presentation=lessons[0].presentation;
  await page.locator('audio').evaluate((audio,time)=>{audio.pause();audio.currentTime=time;},(presentation?.clinicalGallery.startSeconds??lessons[0].realImageOutro.start)+1);
  if(presentation){await until(page,()=>!document.querySelector('#lesson-ending').hidden);assert.equal(await page.locator('.clinical-tile').count(),presentation.clinicalGallery.images.length);}
  else await until(page,()=>document.querySelector('#visual-stage').classList.contains('is-real'));
  await page.locator('audio').evaluate((audio,end)=>{audio.pause();audio.currentTime=(end||audio.duration)-.12;},presentation?.effectiveEndSeconds);
  await page.locator('#play-button').click();await page.waitForSelector('.quiz-option');await page.locator('[data-answer="1"]').click();await page.locator('[data-action="submit-answer"]').click();await page.waitForSelector('.quiz-result');
  const r=await page.evaluate(()=>({card:Learning.get('shahzad2015-q054').card,review:Learning.state.reviews[0]}));assert.equal(r.card.reps,1);assert.equal(r.review.rating,'Good');assert.ok(Date.parse(r.card.due)>Date.now());assert.equal(await page.locator('.quiz-option:not(:disabled)').count(),0);await page.locator('[data-action="close-modal"]').click();
 });
 await check('like and private note persist without changing recall',async()=>{await page.locator('#like-button').click();await page.locator('[data-action="note"]').click();await page.locator('#note-input').fill('The curved key supplies the back.');await page.locator('[data-action="save-note"]').click();const r=await page.evaluate(()=>({r:Learning.get('shahzad2015-q054'),count:Learning.stats().reviewCount}));assert.equal(r.r.liked,true);assert.equal(r.r.note,'The curved key supplies the back.');assert.equal(r.count,1);await page.reload();await page.waitForSelector('#lesson-card:not([hidden])');assert.equal(await page.evaluate(()=>Learning.get('shahzad2015-q054').note),'The curved key supplies the back.');});
 await check('publications show the original book, available cover or offline fallback, and 200 source questions',async()=>{
  await page.locator('[data-tab="publications"]').click();
  const privateCover=fs.existsSync(path.join(root,'private-content/book-cover.jpeg'))||fs.existsSync(path.join(root,'private-content/app-assets/book-cover.jpeg'));
  if(privateCover)await until(page,()=>document.querySelector('[data-cover]')?.naturalWidth>0);
  else await until(page,()=>document.querySelector('[data-cover]')?.hidden===true);
  assert.equal(await page.locator('[data-book]').count(),1);await page.locator('[data-book]').click();assert.equal(await page.locator('.question-cell').count(),200);await page.locator('[data-action="close-modal"]').click();
 });
 await check('due entry gates playback with question; unknown answer gives Again',async()=>{await page.evaluate(()=>{const b=Learning.backup();const s=JSON.parse(b.state[Learning.storageKey]);s.lessons['shahzad2015-q054'].card.due=new Date(Date.now()-5000).toISOString();b.state[Learning.storageKey]=JSON.stringify(s);Learning.restore(b);});await page.locator('[data-tab="feed"]').click();if(!await page.locator('#modal-backdrop:not([hidden])').count())await page.locator('[data-feed="due"]').click();await page.waitForSelector('.quiz-option');assert.equal(await page.locator('audio').evaluate(a=>a.paused),true);await page.getByRole('button',{name:'I don’t know yet'}).click();await page.waitForSelector('.quiz-result');const last=await page.evaluate(()=>Learning.state.reviews.at(-1));assert.equal(last.rating,'Again');assert.equal(last.correct,false);await page.locator('[data-action="close-modal"]').click();});
 await check('early practice never moves the due date',async()=>{const before=await page.evaluate(()=>Learning.get('shahzad2015-q054').card.due);await page.locator('[data-tab="review"]').click();await page.locator('[data-practice-lesson="shahzad2015-q054"]').click();await page.locator('[data-answer="1"]').click();await page.locator('[data-action="submit-answer"]').click();assert.equal(await page.evaluate(()=>Learning.get('shahzad2015-q054').card.due),before);await page.locator('[data-action="close-modal"]').click();});
 await check('failed answer save stays editable; retry records exactly once',async()=>{
  await page.locator('[data-tab="review"]').click();await page.locator('[data-practice-lesson="shahzad2015-q054"]').click();await page.locator('[data-answer="1"]').click();
  const before=await page.evaluate(()=>JSON.stringify(Learning.state));
  await page.evaluate(()=>{window.savedStorageWriter=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw new Error('Simulated full disk');};});
  await page.locator('[data-action="submit-answer"]').click();
  assert.equal(await page.locator('.quiz-result').count(),0);assert.equal(await page.locator('[data-action="submit-answer"]').isEnabled(),true);
  assert.equal(await page.evaluate(()=>JSON.stringify(Learning.state)),before);assert.match(await page.locator('#toast').textContent(),/could not be saved/);
  await page.evaluate(()=>{Storage.prototype.setItem=window.savedStorageWriter;delete window.savedStorageWriter;});
  await page.locator('[data-action="submit-answer"]').click();await page.waitForSelector('.quiz-result');
  assert.equal(await page.evaluate(()=>Learning.state.reviews.length),JSON.parse(before).reviews.length+1);await page.locator('[data-action="close-modal"]').click();
 });
 await check('backup round-trip and invalid backup preserve local data',async()=>{await page.evaluate(()=>{const b=Learning.backup();Learning.note('shahzad2015-q054','Temporary');Learning.restore(b);const before=JSON.stringify(Learning.state);try{Learning.restore({format:'bad',state:{}})}catch(_){}if(JSON.stringify(Learning.state)!==before)throw Error('Invalid restore mutated state');});assert.equal(await page.evaluate(()=>Learning.get('shahzad2015-q054').note),'The curved key supplies the back.');});
 await check('settings check catalog and retention changes without reset',async()=>{await page.locator('[data-tab="settings"]').click();await page.locator('[data-action="retention"]').click();await page.locator('#retention-input').fill('95');await page.locator('[data-action="save-retention"]').click();assert.equal(await page.evaluate(()=>Learning.state.settings.retention),.95);await page.locator('[data-action="check-updates"]').click();await until(page,()=>/No newer app release|Available lesson packages/.test(document.querySelector('#modal-body').textContent));await page.locator('[data-action="close-modal"]').click();});
 const screenshotDir=path.join(root,'test-results');fs.mkdirSync(screenshotDir,{recursive:true});
 await check('all three lessons play local audio and show timed mnemonic and real-image scenes without external network',async()=>{
  const localContext=await browser.newContext({viewport:{width:390,height:844},deviceScaleFactor:1,hasTouch:true,isMobile:true});
  await localContext.route('https://**/*',r=>r.abort());
  await routeRajaStarterFixture(localContext,fixture);
  await localContext.addInitScript(()=>localStorage.setItem('instaanki.state.v1',JSON.stringify({schemaVersion:1,settings:{autoPlay:false,autoCheckUpdates:false},lessons:{},reviews:[]})));
  const localPage=await localContext.newPage();localPage.on('pageerror',e=>errors.push(e.message));await localPage.goto(origin);await localPage.waitForSelector('#lesson-card:not([hidden])');
  for(let index=0;index<lessons.length;index++){
   const lesson=lessons[index];assert.equal(await localPage.locator('#lesson-title').textContent(),lesson.title);await until(localPage,()=>document.querySelector('audio').readyState>=1);
   assert.ok(Math.abs((await localPage.locator('audio').evaluate(a=>a.duration))-lesson.durationSeconds)<.2);
   await localPage.locator('audio').evaluate(a=>{a.currentTime=3;});await localPage.locator('#play-button').click();await until(localPage,()=>document.querySelector('audio').currentTime>3.15);
   assert.equal(await localPage.locator('#lesson-caption').textContent(),lesson.scenes[0].caption);await until(localPage,()=>document.querySelector('#lesson-image').naturalWidth>0);
   await localPage.screenshot({path:path.join(screenshotDir,lesson.id+'-mnemonic.png')});
   await localPage.locator('audio').evaluate((audio,time)=>{audio.pause();audio.currentTime=time;},(lesson.presentation?.clinicalGallery.startSeconds??lesson.realImageOutro.start)+.5);
   if(lesson.presentation){
    await until(localPage,()=>!document.querySelector('#lesson-ending').hidden&&[...document.querySelectorAll('.clinical-tile img')].every(image=>image.complete&&image.naturalWidth>0));
    assert.equal(await localPage.locator('.clinical-tile img').evaluateAll(images=>images.every(image=>getComputedStyle(image).objectFit==='contain')),true);
   }else{
    await until(localPage,()=>document.querySelector('#visual-stage').classList.contains('is-real')&&document.querySelector('#lesson-image').complete&&document.querySelector('#lesson-image').naturalWidth>0);
    assert.equal(await localPage.locator('#lesson-image').evaluate(e=>getComputedStyle(e).objectFit),'contain');assert.ok((await localPage.locator('#real-image-badge').textContent()).includes(lesson.realImages[0].license));
   }
   await localPage.screenshot({path:path.join(screenshotDir,lesson.id+'-real.png')});
   if(index<lessons.length-1)await localPage.locator('[data-action="next"]').click();
  }
  await localContext.close();
 });
 await page.locator('[data-tab="insights"]').click();await page.screenshot({path:path.join(screenshotDir,'insights.png')});
 await page.locator('[data-tab="feed"]').click();if(await page.locator('#modal-backdrop:not([hidden])').count())await page.locator('[data-action="close-modal"]').click();await page.locator('[data-feed="all"]').click();if(await page.locator('#modal-backdrop:not([hidden])').count())await page.locator('[data-action="close-modal"]').click();await page.screenshot({path:path.join(screenshotDir,'feed.png')});
 await check('mobile layouts have no horizontal overflow at360/390/430',async()=>{for(const width of [360,390,430]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}});
 await check('no uncaught JavaScript errors under native-equivalent CSP',async()=>assert.deepEqual(errors,[]));
 await browser.close();server.close();fs.writeFileSync(path.join(screenshotDir,'browser-report.json'),JSON.stringify({passed:results.length,tests:results,physicalAndroidTested:false},null,2));
}
main().catch(e=>{console.error(e);server.close();process.exit(1)});
