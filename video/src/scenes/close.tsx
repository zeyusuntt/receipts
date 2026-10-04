import {AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import type {SceneProps} from './types';

export function Close({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const c = copy.close;
  const secondAt = cueFrame(beat, c.second_cue, fps, sequenceFrom, wordTimestamps);
  const urlAt = cueFrame(beat, c.url_cue, fps, sequenceFrom, wordTimestamps);
  return <AbsoluteFill style={{background: palette.paper}}>
    <div style={{position: 'absolute', left: 128, right: 128, top: 310, textAlign: 'center', fontFamily: fonts.serif, fontSize: 108, lineHeight: 1.3}}>{c.first}</div>
    {frame >= secondAt && <div style={{position: 'absolute', left: 128, right: 128, top: 485, textAlign: 'center', fontFamily: fonts.serif, fontSize: 108, lineHeight: 1.3}}>{c.second}</div>}
    {frame >= urlAt && <>
      <div style={{position: 'absolute', left: 128, right: 128, top: 730, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 70}}><div style={{fontFamily: fonts.mono, fontSize: 64, color: palette.accent}}>{c.repo_url}</div><Img src={staticFile('receipts-qr.svg')} alt={c.site_url} style={{width: 320, height: 320}}/></div>
      <div style={{position: 'absolute', left: 128, right: 128, top: 1130, textAlign: 'center', fontSize: 40, color: palette.secondary}}>{c.tagline}</div>
    </>}
  </AbsoluteFill>;
}
