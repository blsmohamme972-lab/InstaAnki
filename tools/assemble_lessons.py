#!/usr/bin/env python3
"""Bind verified source-derived scripts to actual audio, licensed art and stable IDs.

Requires the private extraction locally. It never copies the original question
wording or complete source book into public lesson data.
"""
from pathlib import Path
import json, shutil
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'private-content'
BOOK='shahzad-raja-2015-200-practice-questions'
TITLE='200 Practice Questions in Cardiothoracic Surgery'
def read(p):return json.loads(p.read_text())
def write(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
def main():
    draft=read(PRIVATE/'starter-lessons-draft.json')
    registry=read(ROOT/'taxonomy/registry.latest.json')
    tags={x['id']:x['label'] for x in registry['tags']}
    real={x['sourceQuestionNumber']:x for x in read(ROOT/'web/media/real/attributions.json')['assets']}
    posters={54:'coronary-palace',5:'sequestration-palace',182:'resistance-palace'}
    # Each original symbol has one explicit meaning, reused at a fixed locus.
    symbols={
      54:[{'symbol':'Curved key','meaning':'Circumflex artery','x':.41,'y':.61},{'symbol':'Side wall','meaning':'Lateral left ventricular wall','x':.62,'y':.55},{'symbol':'Rear bridge','meaning':'Posterior septal territory through the PDA','x':.91,'y':.55}],
      5:[{'symbol':'Separate coat','meaning':'Its own visceral pleural covering','x':.48,'y':.73},{'symbol':'Separate glass dome','meaning':'Extralobar tissue outside the main lung covering','x':.82,'y':.47},{'symbol':'External red pipe','meaning':'Systemic arterial supply','x':.65,'y':.36}],
      182:[{'symbol':'Four locks','meaning':'Radius to the fourth power','x':.5,'y':.22},{'symbol':'Wide doorway','meaning':'Larger vessel radius','x':.67,'y':.58},{'symbol':'Relieved gatekeeper','meaning':'Lower resistance','x':.65,'y':.62}]
    }
    # Restrained image-space motion; real clinical pictures remain uncropped.
    anchors={54:[(.41,.61),(.74,.5),(.91,.55),(.62,.55),(.73,.55),(.41,.61)],5:[(.48,.73),(.65,.36),(.25,.25),(.28,.4),(.82,.47),(.48,.73)],182:[(.5,.2),(.27,.59),(.66,.58),(.66,.58),(.5,.55),(.5,.2)]}
    lessons=[]
    for original in draft['lessons']:
        q=original['source_question_number'];asset=real[q]
        timing=read(ROOT/f"web/media/audio/{original['id']}.timing.json")
        poster=f"media/mnemonic/{posters[q]}.png"
        tag_ids=[original['primary_specialty_id'],original['primary_domain_id'],original['primary_focus_id'],*original.get('concept_ids',[]),*original.get('condition_ids',[]),*original.get('anatomy_ids',[])]
        scenes=[]
        for i,(s,t) in enumerate(zip(original['scenes'],timing['scenes'])):
            assert s['voice_text']==t['text'], 'Audio and source script differ'
            clinical=(q==54 and i==1) or (q==5 and i==2)
            x,y=anchors[q][i]
            scenes.append({'id':s['id'],'start':t['start'],'end':t['end'],'image':f"media/real/{asset['file']}" if clinical else poster,'kind':'clinical' if clinical else 'mnemonic','caption':s['headline'],'transcript':s['voice_text'],'camera':{'from':{'x':.5 if clinical else x,'y':.5 if clinical else y,'scale':1 if clinical else 1.015},'to':{'x':.5 if clinical else x,'y':.5 if clinical else y,'scale':1 if clinical else 1.075}},'spotlight':{'x':x,'y':y,'r':.26 if clinical else .28}})
        mcq=original['mcq'];opts=mcq['options'];correct=next(i for i,x in enumerate(opts) if x['label']==mcq['correct_answer_letter'])
        lesson={'id':f'shahzad2015-q{q:03d}','version':1,'title':original['title'],'specialty':tags[original['primary_specialty_id']],'primarySpecialtyId':original['primary_specialty_id'],'taxonomyVersion':registry['version'],'tags':[{'id':x,'label':tags[x]} for x in dict.fromkeys(tag_ids)],'durationSeconds':timing['duration'],'audioUrl':timing['audioPath'].lstrip('/'),'poster':poster,'locus':original['locus'],'mnemonicSymbols':symbols[q],'scenes':scenes,'realImageOutro':{'start':timing['realImageOutro']['start'],'end':timing['realImageOutro']['end']},'realImages':[{'url':f"media/real/{asset['file']}",'title':asset['title'],'caption':asset['caption'],'displayNotes':asset['displayNotes'],'sourceUrl':asset['sourceUrl'],'author':asset['author'],'license':asset['license']['id'].replace('-',' '),'licenseUrl':asset['license']['url'],'attribution':asset['attribution'],'focusRegion':asset['focusRegion']}],'quiz':{'prompt':mcq['stem'],'options':[x['text'] for x in opts],'correctIndex':correct,'explanation':mcq['explanation']},'source':{'bookId':BOOK,'questionNumber':q,'page':original['source_question_pages'][0]['printed_page'],'answerPages':[p['printed_page'] for p in original['source_answer_pages']],'bookTitle':TITLE,'verificationNote':'Source-aligned original teaching content. Core anatomy or physiology checked against the cited references; historical treatment claims are excluded.','corroboratingSources':original.get('corroborating_sources',[])}}
        assert 60<=lesson['durationSeconds']<=90
        lessons.append(lesson)
    write(ROOT/'web/data/lessons.json',lessons)
    source_questions=read(PRIVATE/'questions.json')
    manifest_path=ROOT/f'production/books/{BOOK}.json'
    if manifest_path.exists():manifest=read(manifest_path)
    else:
        manifest={'schemaVersion':1,'bookId':BOOK,'title':TITLE,'author':'Shahzad G. Raja','year':2015,'totalQuestions':200,'completedVideos':0,'completedQuestionNumbers':[],'updatedAt':datetime.now(timezone.utc).isoformat(),'source':{'extracted':True,'originalPdfRetained':False,'privateArchiveLocation':'User private source archive; do not publish the raw book'},'questions':[{'number':q['source_question_number'],'id':q['id'],'status':'needs_review' if q.get('explanation_format')=='image_only' or q.get('extraction_flags') else 'ready','batchId':None,'lessonId':None} for q in source_questions]}
        write(manifest_path,manifest)
    completed=[x['number'] for x in manifest['questions'] if x['status']=='produced']
    books=[{'id':BOOK,'title':TITLE,'author':'Shahzad G. Raja','year':2015,'coverUrl':'private-content/book-cover.jpeg','totalQuestions':200,'extractedQuestions':200,'completedVideos':len(completed),'progress':round(len(completed)/200*100,1),'completedQuestionNumbers':completed,'nextQuestionNumber':next((q for q in range(1,201) if q not in completed),None),'questions':[{k:q[k] for k in ['number','status','lessonId']} for q in manifest['questions']],'sourceStatus':'Source text extracted; each lesson checked before production','needsNewBook':len(completed)==200}]
    write(ROOT/'web/data/books.json',books)
    write(ROOT/'web/data/taxonomy.json',registry)
    (PRIVATE/'app-assets').mkdir(exist_ok=True)
    shutil.copy2(PRIVATE/'book-cover.jpeg',PRIVATE/'app-assets/book-cover.jpeg')
    print(f'Assembled {len(lessons)} narrated lessons; production ledger: {len(completed)}/200 verified.')
if __name__=='__main__':main()
