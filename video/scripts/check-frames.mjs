import {build} from 'esbuild';
import {mkdirSync} from 'node:fs';

// Server-side rendering exercises scene logic. It does not verify browser layout or fonts.
mkdirSync('out/checks', {recursive: true});
await build({
  stdin: {resolveDir: process.cwd(), loader: 'tsx', contents: `
import assert from 'node:assert/strict';
import {test} from 'node:test';
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
import {scenes as sceneMap} from './src/Video';
import {Captions} from './src/components/Captions';
import {NodeText} from './src/components/NodeText';
import {sequenceWindows, totalFrames, cueFrame} from './src/timing';
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
  for(let frame=from;frame<end;frame++) assert.ok(render(React.createElement(Captions),frame).length>0,'Caption gap at '+frame);
}
console.log('Rejection hold, end hold, and caption coverage passed.');

test('cold open types just the first clause before speech begins',()=>{
  const html=shot(0,windows[0].speechStart-1);
  assert.ok(html.includes('I have successfully implemented the fix for the failing tests.'));
  assert.ok(!html.includes('by adding'));
});
test('numbers keep all tasks visible and change the claimed subset on narration cues',()=>{
  const w=windows[1];
  const at=(phrase)=>cueFrame(w.beat,phrase,timeline.fps,w.from);
  const counts=(frame)=>{
    const html=shot(1,frame);
    return ['unclaimed','claimed','false-done'].map(state=>(html.match(new RegExp('data-state="'+state+'"','g'))??[]).length);
  };
  assert.deepEqual(counts(at('a hundred')),[100,0,0]);
  assert.deepEqual(counts(at('It said "done"')-1),[100,0,0]);
  assert.deepEqual(counts(at('It said "done"')),[33,67,0]);
  assert.deepEqual(counts(at('Twelve')-1),[33,67,0]);
  assert.deepEqual(counts(at('Twelve')),[33,55,12]);
  assert.deepEqual(counts(w.speechDuration-1),[33,55,12]);
  const rateAt=at("by SWE-rebench's own grader");
  assert.ok(!shot(1,rateAt-1).includes('17.9%'));
  assert.ok(shot(1,rateAt+timeline.fps).includes('17.9%'));
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
test('the agent montage exposes readable commands without host plumbing',()=>{
  for(let frame=0;frame<windows[4].speechDuration;frame+=3){
    const html=shot(4,frame);
    for(const prefix of ['/opt/homebrew','/opt/receipts-','/Users/','/private/','executor staging']) assert.ok(!html.includes(prefix),prefix);
  }
});
test('the rejection metadata never shows a full UUID',()=>{
  const html=shot(5,windows[5].speechDuration-1);
  assert.ok(!/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i.test(html));
});
test('the attempt scrolls through the beat and holds its real claim for 1.5 seconds',()=>{
  const w=windows[4];
  const midway=plain(shot(4,Math.round(w.speechDuration/2)));
  assert.ok(!midway.includes('capture patch'));
  assert.ok((shot(4,Math.round(w.speechDuration/2)).match(/data-agent-step=/g)??[]).length>=5);
  for(let frame=w.speechDuration-Math.round(timeline.fps*1.5);frame<w.speechDuration;frame++) {
    assert.ok(plain(shot(4,frame)).includes(story.featured.attempts[0].said));
  }
});
test('the newest step stays inside the scrolling viewport through capture patch',()=>{
  const w=windows[4];
  const last=w.speechDuration-Math.round(timeline.fps*1.5)-1;
  for(const frame of [0,Math.round(last/2),last]) {
    const html=shot(4,frame);
    const offset=Number(html.match(new RegExp('transform:translateY[(]([-0-9.]+)px[)]'))[1]);
    const rows=[...html.matchAll(new RegExp('<div data-agent-step="([0-9]+)" data-newest="([^"]+)" style="height:([0-9.]+)px;','g'))];
    let top=offset,found=false;
    for(const row of rows){
      const height=Number(row[3]);
      if(row[2]==='true'){
        found=true;
        assert.ok(top>=-0.01 && top+height<=660.01,'Newest row outside viewport at frame '+frame+': '+top+' to '+(top+height));
        if(frame===last)assert.equal(Number(row[1]),24);
      }
      top+=height;
    }
    assert.ok(found);
  }
});
test('all six later beats show real evidence and the close holds through the end',()=>{
  const at=(index, phrase)=>cueFrame(windows[index].beat,phrase,timeline.fps,windows[index].from);
  assert.ok(plain(videoShot(6,at(6,'It fixes')-1)).includes(story.featured.appeal_text.split('\\n')[0]));
  for(const path of story.featured.patch_files) assert.ok(plain(videoShot(6,at(6,'It fixes')+timeline.fps)).includes(path));
  assert.ok(plain(videoShot(6,windows[6].speechDuration-1)).includes('VERIFIED'));
  assert.ok(plain(videoShot(7,at(7,"SWE-rebench's grader")+timeline.fps)).includes('resolved'));
  assert.ok(plain(videoShot(7,at(7,"SWE-rebench's grader")-1)).includes('333 baseline-passing tests still pass'));
  for(const path of story.pilot_v1.shipped_files) assert.ok(plain(videoShot(9,at(9,'a copy of the package')+timeline.fps)).includes(path));
  assert.ok(plain(videoShot(10,windows[10].speechDuration-1)).includes('$0.41'));
  const close=videoShot(11,windows[11].durationInFrames-1);
  assert.ok(plain(close).includes('github.com/zeyusuntt/receipts'));
  assert.ok(close.includes('alt="https://zeyusuntt.github.io/receipts/"'));
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
