import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {clamp} from '../components/Motion';
import {NodeText} from '../components/NodeText';
import type {SceneProps} from './types';

export function ColdOpen({beat, sequenceFrom, speechStart, speechDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const clause = story.cold_open.said.split(' by ')[0].trim();
  const said = /[.!?]$/u.test(clause) ? clause : `${clause}.`;
  const typed = Math.floor(interpolate(frame, [0, Math.max(1, speechStart * 0.9)], [0, said.length], clamp));
  const failAt = cueFrame(beat, copy.cold_open.cue, fps, sequenceFrom, wordTimestamps);
  const questionAt = Math.min(speechStart + speechDuration * 0.43, failAt - fps * 1.6);
  const failed = frame >= failAt;
  const run = story.cold_open.run_id.slice(-copy.cold_open.run_short_chars);
  return <AbsoluteFill style={{background: palette.black, color: palette.paper}}>
    {!failed && <>
      <div style={{position: 'absolute', left: 240, right: 240, top: 345, textAlign: 'center', color: '#9EA8B8', fontFamily: fonts.mono, fontSize: 34}}>{copy.cold_open.agent_label}</div>
      <div style={{position: 'absolute', left: 240, right: 240, top: 455, minHeight: 260, textAlign: 'center', fontFamily: fonts.mono, fontSize: 76, lineHeight: 1.5}}>{said.slice(0, typed)}<span style={{opacity: typed === said.length ? 0 : 1, color: '#7388DE'}}>▌</span></div>
      {frame >= questionAt && <div style={{position: 'absolute', left: 240, right: 240, top: 825, textAlign: 'center', fontFamily: fonts.serif, fontStyle: 'italic', fontSize: 130}}>{copy.cold_open.question}</div>}
    </>}
    {failed && <>
      <div style={{position: 'absolute', left: 160, right: 160, top: 390, textAlign: 'center', fontFamily: fonts.mono, fontWeight: 500, fontSize: 180, color: palette.rejected}}>{copy.cold_open.failed}</div>
      <div style={{position: 'absolute', left: 160, right: 160, top: 630, textAlign: 'center', fontFamily: fonts.mono, fontSize: 52, lineHeight: 1.55, color: palette.paper}}><NodeText text={story.cold_open.witness_failed[0].evidence}/></div>
      <div style={{position: 'absolute', left: 160, right: 160, top: 975, textAlign: 'center', fontFamily: fonts.mono, fontSize: 36, color: '#9EA8B8'}}>{copy.cold_open.witness_label.replace('{run}', run)}</div>
    </>}
  </AbsoluteFill>;
}
