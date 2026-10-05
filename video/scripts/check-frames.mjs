import {build} from 'esbuild';
import {mkdirSync} from 'node:fs';

// Server-side rendering exercises scene logic. It does not verify browser layout or fonts.
mkdirSync('out/checks', {recursive: true});
await build({
  stdin: {resolveDir: process.cwd(), loader: 'tsx', contents: `
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readdirSync, readFileSync} from 'node:fs';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {Internals} from 'remotion';
import {ColdOpen} from './src/scenes/cold_open';
import {WhoAndNumbers} from './src/scenes/who_and_numbers';
import {Receipts} from './src/scenes/receipts';
import {FeaturedSetup} from './src/scenes/featured_setup';
import {AgentWorks} from './src/scenes/agent_works';
import {Rejected} from './src/scenes/rejected';
import {Placeholder} from './src/scenes/Placeholder';
import {Video, scenes as sceneMap} from './src/Video';
import {Captions} from './src/components/Captions';
import {NodeText} from './src/components/NodeText';
import {sequenceWindows, totalFrames, cueFrame, replayPlan} from './src/timing';
import {timeline, story, copy} from './src/content';

const scenes=timeline.beats.map(beat=>sceneMap[beat.id]);
const windows=sequenceWindows(timeline);
const config={id:'Receipts',fps:timeline.fps,width:2560,height:1440,durationInFrames:totalFrames(timeline.total_s,timeline.fps),defaultProps:{}};
// OffthreadVideo's render path reads these browser flags even during SSR.
// React server rendering runs no effects, so this never fetches a video frame.
globalThis.window={remotion_audioEnabled:false,remotion_videoEnabled:false,remotion_proxyPort:0,location:{origin:'http://localhost',href:'http://localhost/'}};
globalThis.document={baseURI:'http://localhost/'};
function render(element,frame) {
  return renderToStaticMarkup(React.createElement(Internals.RemotionEnvironmentContext.Provider,{value:{isRendering:true,isStudio:false,isPlayer:false,isReadOnlyStudio:false,isClientSideRendering:false}},React.createElement(Internals.CompositionManager.Provider,{value:{compositions:[config],canvasContent:{type:'composition',compositionId:'Receipts'},currentCompositionMetadata:config}},React.createElement(Internals.TimelineContext.Provider,{value:{frame:{Receipts:frame},isInsideFreeze:false}},React.createElement(Internals.CanUseRemotionHooksProvider,{},element)))));
}
function shot(index,frame) {
  const w=windows[index];
  return render(React.createElement(scenes[index]??Placeholder,{beat:w.beat,sequenceFrom:w.from,speechStart:w.speechStart,speechDuration:w.speechDuration,sceneDuration:w.durationInFrames}),frame);
}
function videoShot(index, localFrame) {
  const w=windows[index];
  return render(React.createElement(sceneMap[w.beat.id]??Placeholder,{beat:w.beat,sequenceFrom:w.from,speechStart:w.speechStart,speechDuration:w.speechDuration,sceneDuration:w.durationInFrames}),localFrame);
}
function plain(html) {return html.replace(/<[^>]+>/g,'').replaceAll('&#x27;', "'").replaceAll('&quot;', '"').replaceAll('&gt;', '>').replaceAll('&lt;', '<').replaceAll('&amp;', '&').replaceAll('\u200B','');}
function fontSizes(source) {return [...source.matchAll(/fontSize\\s*:\\s*([0-9]+(?:\\.[0-9]+)?)/g)].map(match=>Number(match[1]));}
function assertFontFloor(path,source) {
  for(const size of fontSizes(source)) assert.ok(size>=34,path+' has fontSize '+size);
}
test('source keeps the 34 pixel type floor and removes the permanent corner strip',()=>{
  const files=readdirSync('src',{recursive:true}).filter(path=>path.endsWith('.tsx'));
  for(const path of files) assertFontFloor(path,readFileSync('src/'+path,'utf8'));
  assert.ok(!readFileSync('src/Video.tsx','utf8').includes('CornerStrip'));
});
test('font floor scanner finds declarations and rejects a sub-floor fixture',()=>{
  const fixture='const safe={fontSize: 34}; const unsafe={fontSize: 20};';
  assert.deepEqual(fontSizes(fixture),[34,20]);
  assert.throws(()=>assertFontFloor('fixture.tsx',fixture),/fixture\\.tsx has fontSize 20/);
});
test('scratch draft mark occupies the cleared top-right corner, and only on a scratch timeline',()=>{
  const html=render(React.createElement(Video,{}),0);
  const marker=html.indexOf('data-draft');
  if(!timeline.source.startsWith('scratch')) { assert.equal(marker,-1,'a recorded narration renders no draft mark'); return; }
  assert.ok(marker>=0,'scratch timeline renders a draft mark');
  const tag=html.slice(marker,marker+320);
  assert.ok(tag.includes('right:64px'));
  assert.ok(tag.includes('top:48px'));
  assert.ok(!tag.includes('left:64px'));
});
for(const [index,w] of windows.entries()) {
  const midpoint=Math.round((w.beat.start_s+w.beat.end_s)/2*timeline.fps)-w.from;
  for(const frame of [0,midpoint,w.speechStart+w.speechDuration-1]) assert.ok(shot(index,frame).length>100);
  console.log(w.beat.id+': start, midpoint, speech end rendered as HTML');
}
const rejected=windows[5];
const stampAt=cueFrame(rejected.beat,copy.cues.rejected,timeline.fps,rejected.from);
assert.ok(shot(5,stampAt-1).replace(/<[^>]+>/g,'').replaceAll('\u200B','').includes(story.featured.attempts[0].predicates[0].evidence));
assert.ok(!shot(5,stampAt-1).includes('rotate(-3deg)'));
assert.ok(shot(5,stampAt+20).includes('REJECTED'));
// Remotion's spring reaches its exact resting value one frame after its duration.
const firstHeld=stampAt+Math.round(timeline.fps*0.65)+1;
assert.ok(shot(5,firstHeld)===shot(5,firstHeld+timeline.fps*2),'The rejection must hold without new scene motion for two seconds');
assert.ok(firstHeld+timeline.fps*2<=windows[6].from-rejected.from,'The next scene must leave two seconds after stamp settling');
const last=windows[11];
assert.equal(shot(11,last.durationInFrames-1),shot(11,last.speechStart+last.speechDuration-1),'End hold preserves the close card');
for(const w of windows) {
  const from=Math.round(w.beat.start_s*timeline.fps);
  const end=Math.round(w.beat.end_s*timeline.fps);
  // Every spoken word has its caption on screen; only a pause longer than the caption hold may clear it.
  const spoken=w.beat.words?.length ? w.beat.words.map(word=>[Math.round(word.start_s*timeline.fps),Math.round(word.end_s*timeline.fps)]) : [[from,end]];
  for(const [a,b] of spoken) for(let frame=a;frame<b;frame++) assert.ok(render(React.createElement(Captions),frame).length>0,'Caption gap at '+frame);
}
console.log('Rejection hold, end hold, and caption coverage passed.');

test('cold open types just the first clause before speech begins',()=>{
  const html=shot(0,windows[0].speechStart-1);
  assert.ok(html.includes('I have successfully implemented the fix for the failing tests.'));
  assert.ok(!html.includes('by adding'));
});
test('numbers open on the full grid, reveal the false dones, then make all claimed dones indistinguishable',()=>{
  const w=windows[1];
  const at=(phrase)=>cueFrame(w.beat,phrase,timeline.fps,w.from);
  const counts=(frame)=>{
    const html=shot(1,frame);
    return ['unclaimed','claimed','false-done'].map(state=>(html.match(new RegExp('data-state="'+state+'"','g'))??[]).length);
  };
  assert.deepEqual(counts(0),[100,0,0]);
  assert.deepEqual(counts(at('sixty-seven')-1),[100,0,0]);
  assert.deepEqual(counts(at('sixty-seven')),[33,67,0]);
  assert.deepEqual(counts(at('Twelve')-1),[33,67,0]);
  assert.deepEqual(counts(at('Twelve')),[33,55,12]);
  assert.deepEqual(counts(at('which twelve')),[33,67,0]);
  assert.ok(!plain(shot(1,at('Twelve')-1)).includes('17.9%'));
  assert.ok(plain(shot(1,at('Twelve'))).includes('17.9%'));
});
test('numbers lower third is present at one second and gone at five seconds',()=>{
  const first=shot(1,timeline.fps);
  assert.ok(plain(first).includes('Zeyu Sun'));
  assert.ok(plain(first).includes('100 real bugs, 100 open-source projects'));
  assert.ok(first.includes('data-number-heading=\"true\"'));
  assert.ok(first.includes('white-space:nowrap'));
  assert.ok(first.includes('data-number-composition=\"true\"'));
  assert.match(first,/data-number-composition=\"true\" style=\"[^\"]*top:110px;bottom:220px/);
  assert.match(first,/data-dot-grid=\"true\"[^>]*style=\"[^\"]*grid-template-columns:repeat\\(10, 70px\\);gap:20px/);
  assert.match(first,/data-lower-third-region=\"true\" style=\"[^\"]*left:1430px;right:128px/);
  assert.ok(!plain(shot(1,timeline.fps*5)).includes('Zeyu Sun'));
});
test('numbers right-half counter replaces 100 with 67 and then the false-done rate',()=>{
  const w=windows[1];
  const at=(phrase)=>cueFrame(w.beat,phrase,timeline.fps,w.from)+Math.ceil(timeline.fps*0.3);
  const counter=(frame)=>{
    const html=shot(1,frame);
    const states=[...html.matchAll(/data-number-counter-state=\"([^\"]+)\"/g)].map(match=>match[1]);
    return {html,text:plain(html),states};
  };
  const tasks=counter(at(copy.cues.tasks));
  assert.deepEqual(tasks.states,['tasks']);
  assert.ok(tasks.text.includes('100real bugs'));
  assert.ok(!tasks.text.includes('67said ‘done’'));

  const claimed=counter(at(copy.cues.claimed));
  assert.deepEqual(claimed.states,['claimed']);
  assert.ok(claimed.text.includes('67said ‘done’'));
  assert.ok(!claimed.text.includes('17.9%'));

  const falseDone=counter(at(copy.cues.false));
  assert.deepEqual(falseDone.states,['false']);
  assert.ok(falseDone.text.includes('12 of 67'));
  assert.ok(falseDone.text.includes('17.9%'));
  assert.ok(!falseDone.text.includes('67said ‘done’'));
});
test('secondary layouts stay balanced and keep their key labels readable',()=>{
  const receipts=windows[2];
  const witnessAt=cueFrame(receipts.beat,copy.cues.witness,timeline.fps,receipts.from);
  const preConsole=videoShot(2,witnessAt-timeline.fps);
  assert.ok(preConsole.includes('data-map-node=\"agent\"'));
  assert.ok(plain(preConsole).includes(copy.tagline),'tagline stays under the map until the console appears');
  const consoleFrame=videoShot(2,witnessAt);
  assert.ok(consoleFrame.includes('captures/console/sandboxes-about.png'));
  assert.ok(!plain(consoleFrame).includes(copy.tagline));

  const appeal=windows[6];
  // The checks list follows the console proof; it is on screen by the VERIFIED cue.
  const checksAt=cueFrame(appeal.beat,copy.appeal.cues.verified,timeline.fps,appeal.from);
  const appealChecks=videoShot(6,checksAt);
  assert.ok(appealChecks.includes('data-appeal-checks=\"true\"'));
  assert.ok(appealChecks.includes('data-check-min-size=\"44\"'));
  assert.match(appealChecks,/data-appeal-checks=\"true\" style=\"[^\"]*left:420px;right:420px/);

  const pilot=windows[9];
  const treeAt=cueFrame(pilot.beat,copy.pilot.cues.tree,timeline.fps,pilot.from);
  const publishedAt=cueFrame(pilot.beat,copy.pilot.cues.published,timeline.fps,pilot.from);
  assert.match(videoShot(9,treeAt+timeline.fps),/data-pilot-tree=\"true\" style=\"[^\"]*top:220px;bottom:220px/);
  assert.match(videoShot(9,publishedAt+timeline.fps),/data-pilot-checklist=\"true\" style=\"[^\"]*top:220px;bottom:220px/);

  const agent=windows[4];
  const readAt=cueFrame(agent.beat,'reads the code',timeline.fps,agent.from);
  const actions=videoShot(4,readAt);
  assert.ok(actions.includes('grid-template-columns:370px 1fr 150px'));
  assert.ok(actions.includes('data-action-label=\"true\"'));
  assert.ok(actions.includes('white-space:nowrap'));
});
test('appeal ties the witness receipt record to the Token Factory console operation',()=>{
  const w=windows[6];
  const forkAt=cueFrame(w.beat,copy.appeal.cues.fork,timeline.fps,w.from);
  const html=videoShot(6,forkAt+Math.ceil(timeline.fps*0.3));
  const text=plain(html);
  const operation=story.featured.witness_operations.w2;
  assert.ok(html.includes('captures/console/witness-operation.png'));
  assert.ok(html.includes('aria-label="Operation UUID"'));
  assert.ok(html.includes('aria-label="Success"'));
  assert.ok(text.includes('This witness run in the Nebius Token Factory console'));
  assert.ok(text.includes('receipt record · witness w2 · operation '+operation));
  assert.ok(html.includes('data-witness-operation="'+operation+'"'));
});
test('spec names retain class identity and permit only separator breaks',()=>{
  const html=shot(3,windows[3].speechDuration-1);
  const plain=html.replace(/<[^>]+>/g,'').replaceAll('\u200B','');
  assert.ok(plain.includes('TestFTPFS::test_getinfo_modified'));
  assert.ok(plain.includes('TestFTPFSNoMLSD::test_getinfo_modified'));
  assert.ok(plain.includes('TestMemoryFS::test_copy_preserve_time'));
  assert.ok(!html.includes('overflow-wrap:anywhere'));
  assert.ok(html.replace(/<[^>]+>/g,'').includes('::\u200B'));
});
test('the agent beat uses three real action rows and the recorded-step count',()=>{
  const w=windows[4];
  const html=plain(shot(4,cueFrame(w.beat,'runs the tests',timeline.fps,w.from)));
  assert.ok(html.includes('grep -n "_parse_ftp_time" fs/ftpfs.py'));
  assert.ok(html.includes('write fs/ftpfs.py'));
  assert.ok(html.includes('pytest tests/test_ftpfs.py -v --tb=no -q'));
  assert.ok(html.includes('exit 1'));
  assert.ok(html.includes('24 recorded steps'));
  for(const prefix of ['/opt/homebrew','/opt/receipts-','/Users/','/private/','executor staging']) assert.ok(!html.includes(prefix),prefix);
});
test('the rejection metadata never shows a full UUID',()=>{
  const html=shot(5,windows[5].speechDuration-1);
  assert.ok(!/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.test(html));
});
test('the attempt holds its real claim for 1.5 seconds',()=>{
  const w=windows[4];
  for(let frame=w.speechDuration-Math.round(timeline.fps*1.5);frame<w.speechDuration;frame++) {
    assert.ok(plain(shot(4,frame)).includes(story.featured.attempts[0].said));
  }
});
test('all six later beats show real evidence and the close holds through the end',()=>{
  const at=(index, phrase)=>cueFrame(windows[index].beat,phrase,timeline.fps,windows[index].from);
  assert.ok(plain(videoShot(6,at(6,'It finds the real bug')-1)).includes(story.featured.appeal_text.split('\\n')[0]));
  for(const path of story.featured.patch_files) assert.ok(plain(videoShot(6,at(6,'It finds the real bug')+timeline.fps)).includes(path));
  assert.ok(plain(videoShot(6,windows[6].speechDuration-1)).includes('VERIFIED'));
  assert.ok(plain(videoShot(7,at(7,"SWE-rebench's grader")+timeline.fps)).includes('resolved'));
  for(const path of story.pilot_v1.shipped_files) assert.ok(plain(videoShot(9,at(9,'a copy of the package')+timeline.fps)).includes(path));
  assert.ok(plain(videoShot(10,at(10,'It all ran on Nebius Token Factory')-1)).includes('$0.41'));
  const close=videoShot(11,windows[11].durationInFrames-1);
  assert.ok(plain(close).includes('github.com/zeyusuntt/receipts'));
  assert.ok(close.includes('alt="https://zeyusuntt.github.io/receipts/"'));
});
test('printed receipt is complete by narration end and official agreement follows its cue',()=>{
  const w=windows[7];
  const receipt=plain(videoShot(7,w.speechDuration-1));
  for(const line of [
    'RECEIPT',
    'pyfilesystem__pyfilesystem2-462',
    'PyFilesystem/pyfilesystem2 @ ac8a91a',
    'spec: 3 of 3 target tests pass',
    'kept: 333 of 333 passing tests',
    'removed or skipped: none',
    'scope: 2 files, no tests',
    'steps: 36 agent + 2 witness, chained',
    'attempt 1 rejected, attempt 2 verified',
    'Nemotron 3 Super · Nebius Token Factory',
    '904,972 tokens · $0.28',
    'witness: fresh fork of bc230a98',
    'VERIFIED',
  ]) assert.ok(receipt.includes(line),line);
  const grader=cueFrame(w.beat,"SWE-rebench's grader",timeline.fps,w.from);
  assert.ok(!plain(videoShot(7,grader-1)).includes('agrees with the gate'));
  assert.ok(plain(videoShot(7,grader)).includes('agrees with the gate'));
});
test('printed receipts stay inside the safe area and keep every line unbroken',()=>{
  const full=videoShot(7,windows[7].speechDuration-1);
  const marker=full.indexOf('data-paper-receipt');
  assert.ok(marker>=0,'full receipt is rendered');
  const geometry=full.slice(Math.max(0,marker-200),marker+500).match(/top:([0-9]+)px\"><div data-paper-receipt=\"true\"[^>]*style=\"[^\"]*height:([0-9]+)px/);
  assert.ok(geometry,'full receipt exposes its rendered top and height');
  const top=Number(geometry[1]);
  const bottom=top+Number(geometry[2]);
  assert.ok(top>=110,'receipt top '+top+' is above the safe area');
  assert.ok(bottom<=1220,'receipt bottom '+bottom+' enters the caption band');
  const expected=[
    'RECEIPT',
    'pyfilesystem__pyfilesystem2-462',
    'PyFilesystem/pyfilesystem2 @ ac8a91a',
    'spec: 3 of 3 target tests pass',
    'kept: 333 of 333 passing tests',
    'removed or skipped: none',
    'scope: 2 files, no tests',
    'steps: 36 agent + 2 witness, chained',
    'attempt 1 rejected, attempt 2 verified',
    'Nemotron 3 Super · Nebius Token Factory',
    '904,972 tokens · $0.28',
    'witness: fresh fork of bc230a98',
  ];
  const lines=[...full.matchAll(/data-receipt-line=\"true\"[^>]*>([^<]*)/g)].map(match=>plain(match[1]));
  assert.deepEqual(lines,expected);
  assert.ok(lines.every(line=>[...line].length<=46),'receipt line exceeds 46 characters: '+lines.find(line=>[...line].length>46));

  const w=windows[10];
  const compact=videoShot(10,cueFrame(w.beat,'a receipt I can re-run',timeline.fps,w.from)+timeline.fps);
  assert.ok(!compact.includes('data-command-break=\"after-reverify\"'),'separate reverify command box remains');
  const compactLines=[...compact.matchAll(/data-receipt-line=\"true\"[^>]*>([^<]*)/g)].map(match=>plain(match[1]));
  assert.ok(compactLines.length>0);
  assert.ok(compactLines.every(line=>[...line].length<=46),'compact receipt line exceeds 46 characters');
});
test('printed receipt lines become visible on their cues and remain visible at completion',()=>{
  const w=windows[7];
  const checks=[
    'spec: 3 of 3 target tests pass',
    'kept: 333 of 333 passing tests',
    'removed or skipped: none',
    'scope: 2 files, no tests',
    'steps: 36 agent + 2 witness, chained',
  ];
  const meta=[
    'attempt 1 rejected, attempt 2 verified',
    'Nemotron 3 Super · Nebius Token Factory',
    '904,972 tokens · $0.28',
    'witness: fresh fork of bc230a98',
  ];
  const opacity=(html,text)=>{
    const line=[...html.matchAll(/data-receipt-line=\"true\" style=\"([^\"]*)\">([^<]*)/g)].find(match=>plain(match[2])===text);
    assert.ok(line,'missing receipt line '+text);
    const value=line[1].match(/opacity:([01])/);
    assert.ok(value,'missing receipt opacity for '+text);
    return Number(value[1]);
  };
  for(const [index,phrase] of copy.proof.check_cues.entries()) {
    const at=cueFrame(w.beat,phrase,timeline.fps,w.from);
    assert.equal(opacity(videoShot(7,at-1),checks[index]),0,checks[index]+' appears before its cue');
    assert.equal(opacity(videoShot(7,at),checks[index]),1,checks[index]+' is hidden on its cue');
  }
  const complete=videoShot(7,w.speechDuration-1);
  for(const line of [...checks,...meta]) assert.equal(opacity(complete,line),1,line+' is hidden during the completed receipt hold');
  assert.ok(plain(complete).includes('VERIFIED'));
});
test('printed receipt grows with its lines and reaches full height with the stamp',()=>{
  const w=windows[7];
  const firstAt=cueFrame(w.beat,copy.proof.check_cues[0],timeline.fps,w.from);
  const thirdAt=cueFrame(w.beat,copy.proof.check_cues[2],timeline.fps,w.from);
  const geometry=(html)=>{
    const marker=html.indexOf('data-paper-receipt');
    const receipt=html.slice(marker,marker+1800).match(/data-paper-receipt=\"true\" data-final-height=\"([0-9.]+)\" data-print-complete=\"(true|false)\" style=\"([^\"]*)\"/);
    const parent=html.slice(Math.max(0,marker-200),marker).match(/top:([0-9.]+)px\"><div $/);
    assert.ok(receipt,'receipt exposes animation geometry: '+html.slice(marker,marker+260));
    assert.ok(parent,'receipt exposes fixed top geometry: '+html.slice(Math.max(0,marker-120),marker));
    const height=Number(receipt[3].match(/height:([0-9.]+)px/)?.[1]);
    return {top:Number(parent[1]), finalHeight:Number(receipt[1]), complete:receipt[2]==='true', height};
  };
  const earlyFrame=Math.min(firstAt+Math.ceil(timeline.fps*0.3),thirdAt-1);
  const early=geometry(videoShot(7,earlyFrame));
  const complete=geometry(videoShot(7,w.speechDuration-1));
  assert.equal(early.top,complete.top,'receipt top edge moves while printing');
  assert.ok(early.height<complete.finalHeight*0.6,'early receipt is already '+Math.round(early.height/complete.finalHeight*100)+'% of final height');
  assert.equal(complete.height,complete.finalHeight,'completed receipt has not reached final height');
  assert.equal(complete.complete,true);
  assert.ok(complete.top+complete.height<=1190,'completed receipt bottom exceeds 1190');

  const results=windows[10];
  const compact=geometry(videoShot(10,cueFrame(results.beat,copy.results.cues.reverify,timeline.fps,results.from)+1));
  assert.equal(compact.height,compact.finalHeight,'compact receipt must render at final height');
  assert.equal(compact.complete,true,'compact receipt must render complete');
});
test('pilot outcome cards are filled on their first frame',()=>{
  const first=plain(videoShot(9,0));
  assert.ok(first.includes('The gate'));
  assert.ok(first.includes('PASS'));
  assert.ok(first.includes('not resolved'));
});
test('results proof moves from overview to readable usage and operations push-ins',()=>{
  const w=windows[10];
  const builtAt=cueFrame(w.beat,'It all ran on Nebius Token Factory',timeline.fps,w.from);
  const tokensAt=cueFrame(w.beat,'eighty-seven million',timeline.fps,w.from);
  const sandboxesAt=cueFrame(w.beat,'five hundred sandboxes',timeline.fps,w.from);
  assert.ok(tokensAt-builtAt>=Math.round(timeline.fps*1.5),'console overview must hold for 1.5 seconds');
  const overview=videoShot(10,builtAt+timeline.fps);
  assert.ok(overview.includes('captures/console/usage.png'),overview);
  assert.ok(overview.includes('captures/console/operations.png'),overview);
  assert.ok(plain(overview).includes('Built on Nebius Token Factory'));

  const usage=videoShot(10,tokensAt+timeline.fps);
  assert.ok(usage.includes('captures/console/usage.png'));
  assert.ok(!usage.includes('captures/console/operations.png'));
  assert.ok(usage.includes('data-highlight-width=\"2200\"'));
  assert.ok(plain(usage).includes('87,379,659'));
  assert.ok(plain(usage).includes('Nemotron tokens'));
  assert.ok(plain(usage).includes('over the 100 tasks'));
  assert.ok(plain(usage).includes('Token Factory usage, Sep 4 to Oct 4 (all of development)'));

  const operations=videoShot(10,sandboxesAt+timeline.fps);
  assert.ok(!operations.includes('captures/console/usage.png'));
  assert.ok(operations.includes('captures/console/operations.png'));
  assert.ok(operations.includes('data-highlight-width=\"2200\"'));
  assert.ok(operations.includes('data-console-height=\"680\"'),'rotated operations annotation needs vertical clearance');
  assert.ok(plain(operations).includes('482sandboxes'));
  assert.ok(plain(operations).includes('4,253hash-chained steps'));
  assert.ok(plain(operations).includes('over the 100 tasks'));
  assert.ok(plain(operations).includes('Token Factory Sandboxes, real operations'));

  for(const html of [usage,operations]) {
    const heading=html.match(/data-proof-heading=\"true\" style=\"([^\"]*)\"/);
    const panel=html.match(/data-proof-panel=\"true\" style=\"([^\"]*)\"/);
    assert.ok(heading && panel,'push-in exposes heading and panel geometry');
    const number=(style,name)=>Number(style.match(new RegExp(name+':([0-9.]+)(?:px)?'))?.[1]);
    const headingTop=number(heading[1],'top');
    const headingSize=number(heading[1],'font-size');
    const headingLineHeight=number(heading[1],'line-height');
    const panelTop=number(panel[1],'top');
    assert.ok(panelTop>=200,'push-in panel starts at '+panelTop+'px');
    assert.ok(panelTop>=headingTop+headingSize*headingLineHeight,'push-in panel overlaps the heading');
    const labels=[...html.matchAll(/data-proof-label=\"true\" style=\"([^\"]*)\">([^<]*)/g)];
    assert.ok(labels.length>=2,'push-in exposes its metric labels');
    for(const [,style,label] of labels) {
      assert.ok(style.includes('white-space:nowrap'),'metric label wraps: '+plain(label));
      assert.ok([...plain(label)].length<=20,'metric label is too long: '+plain(label));
    }
  }
});
test('results open on a vertically centred impact comparison with 12 and 0 dominant',()=>{
  const html=videoShot(10,0);
  const text=plain(html);
  for(const phrase of ['Nemotron on its own','67','said done','12','were false','With Receipts','66','shipped','0','false',"by SWE-rebench's official grader, on these 100 bugs",'$0.41 of Nemotron tokens per verified fix']) assert.ok(text.includes(phrase),phrase);
  assert.ok(html.includes('data-impact-grid=\"true\"'));
  assert.match(html,/data-impact-grid=\"true\" style=\"[^\"]*top:110px;bottom:220px[^\"]*justify-content:center/);
  assert.match(html,/data-impact-column-left=\"true\" style=\"[^\"]*border-right:2px solid/);
  assert.match(html,/data-impact-number=\"67\" style=\"[^\"]*font-size:160px/);
  assert.match(html,/data-impact-number=\"66\" style=\"[^\"]*font-size:160px/);
  assert.match(html,/data-impact-number=\"12\" style=\"[^\"]*font-size:260px/);
  assert.match(html,/data-impact-number=\"0\" style=\"[^\"]*font-size:260px/);
  const sizes=(marker)=>[...html.matchAll(new RegExp('data-'+marker+'=\"true\" style=\"[^\"]*font-size:([0-9]+)px','g'))].map(match=>Number(match[1]));
  assert.deepEqual(sizes('impact-header'),[56,56]);
  assert.deepEqual(sizes('impact-label'),[56,56,56,56]);
  assert.deepEqual(sizes('impact-grader'),[40]);
  assert.deepEqual(sizes('impact-cost'),[56]);
});
test('results close on the reusable receipt and Receipts-written pull request description',()=>{
  const w=windows[10];
  const rendered=videoShot(10,cueFrame(w.beat,'a receipt I can re-run',timeline.fps,w.from)+timeline.fps);
  const html=plain(rendered);
  assert.ok(html.includes('RECEIPTpyfilesystem__pyfilesystem2-462'));
  assert.ok(html.includes('Pull request description, written by Receipts'));
  assert.ok(html.includes('Fixes pyfilesystem__pyfilesystem2-462: FTPFS should use MDTM.'));
  assert.ok(html.includes('re-verify: uv run receipts reverify receipts/pyfilesystem__pyfilesystem2-462.json'));
  assert.ok(!rendered.includes('data-command-break="after-reverify"'),'the separate reverify command box remains');

  const card=rendered.match(/data-pr-description-card="true" data-card-top="([0-9.]+)" data-card-height="([0-9.]+)"/);
  assert.ok(card,'PR card exposes its safe-area geometry');
  assert.ok(Number(card[1])+Number(card[2])<=1220,'PR card enters the caption band');
  const lines=[...rendered.matchAll(/data-pr-body-line="true"[^>]*>([^<]*)/g)].map(match=>plain(match[1]));
  assert.ok(lines.length>0,'PR description has no body lines');
  assert.ok(lines.every(line=>[...line].length<=48),'PR body line exceeds the mono 34 character budget: '+lines.find(line=>[...line].length>48));
});
test('results part D replays the real fix recording and holds its final frame',()=>{
  const w=windows[10];
  const fixAt=cueFrame(w.beat,'On another repo',timeline.fps,w.from);
  const before=videoShot(10,fixAt-1);
  const replay=videoShot(10,fixAt);
  assert.ok(!before.includes('captures/fix-tf.mp4'));
  assert.ok(replay.includes('data-replay-media="captures/fix-tf.mp4"'));
  assert.ok(replay.includes('data-replay-state="typing"'));
  assert.ok(replay.includes('data-replay-rate="1"'));
  assert.ok(replay.includes('data-replay-source-seconds="15.000"'));
  assert.ok(plain(replay).includes('Another repo, one command: PyFlakes issue 335 on Nebius Token Factory Sandboxes'));
  assert.ok(plain(replay).includes('real recording · the waits are sped up · final 2s of typing shown'));

  const excerpt={...story.media.fix,command_start_s:story.media.fix.command_end_s-2};
  const plan=replayPlan(excerpt,(w.durationInFrames-fixAt)/timeline.fps,timeline.fps);
  assert.equal(plan.segments[0].rate,1,'fix typing must play at 1x');
  assert.ok(plan.segments[1].rate>1,'fix wait must be accelerated');
  assert.equal(plan.segments[2].rate,1,'fix result must play at 1x');
  const oneSecond=videoShot(10,fixAt+timeline.fps);
  assert.ok(oneSecond.includes('data-replay-state="typing"'));
  assert.ok(oneSecond.includes('data-replay-source-seconds="16.000"'));
  const result=videoShot(10,fixAt+plan.segments[2].from);
  assert.ok(result.includes('data-replay-state="result"'));
  assert.ok(result.includes('data-replay-rate="1"'));

  const beforeClose=windows[11].from-w.from-1;
  const held=videoShot(10,beforeClose);
  assert.ok(held.includes('data-replay-media="captures/fix-tf.mp4"'));
  assert.ok(held.includes('data-replay-state="hold"'));
  // The recording itself is the result: it fills the frame instead of a typed summary under it.
  assert.ok(!held.includes('data-fix-result-summary'));
  assert.match(held,/top:200px;height:1010px/);
});
test('captions consume aligned beat words without an external prop',()=>{
  const beat={id:'x',start_s:10,end_s:14,text:'One two. Three.',words:[
    {w:'One',start_s:10.2,end_s:10.5},{w:'two.',start_s:10.7,end_s:11},
    {w:'Three.',start_s:12.5,end_s:13.5},
  ]};
  assert.ok(render(React.createElement(Captions,{beats:[beat]}),Math.round(10.8*timeline.fps)).includes('One two.'));
  assert.equal(render(React.createElement(Captions,{beats:[beat]}),Math.round(11.5*timeline.fps)),'');
  assert.ok(render(React.createElement(Captions,{beats:[beat]}),Math.round(12.8*timeline.fps)).includes('Three.'));
});
test('appeal prose and provenance can wrap within their evidence cards',()=>{
  for(const [text,width] of [
    [story.featured.appeal_text.split('\\n').filter(Boolean).at(-1),1050],
    [story.featured.appeal_text.split('\\n')[1],1050],
    [story.featured.attempts[1].predicates[4].evidence,1410],
  ]) {
    const html=render(React.createElement(NodeText,{text}),0);
    const groups=[...html.matchAll(new RegExp('<span style="white-space:nowrap">([^<]+)</span>','g'))].map(match=>plain(match[1]));
    assert.ok(groups.every(group=>group.length*32*0.6<=width),'Unbreakable evidence exceeds its mono text column: '+text);
    assert.equal(plain(html),text);
  }
});
`},
  bundle: true, platform: 'node', format: 'esm', packages: 'external', outfile: 'out/checks/frames.mjs',
  plugins: [{name: 'omit-font-css-from-ssr', setup(b) {
    b.onResolve({filter: /\.css$/}, (args) => ({path: args.path, namespace: 'font-css'}));
    b.onLoad({filter: /.*/, namespace: 'font-css'}, () => ({contents: '', loader: 'js'}));
  }}],
});
await import('../out/checks/frames.mjs');
