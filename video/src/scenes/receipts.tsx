import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy} from '../content';
import {cueFrame} from '../timing';
import {palette} from '../theme';
import {ArchitectureMap, type MapNode} from '../components/ArchitectureMap';
import {Reveal} from '../components/Motion';
import type {SceneProps} from './types';

export function Receipts({beat, sequenceFrom, speechDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const mapAt = cue(copy.cues.agent) - fps * 0.8;
  const at: Record<MapNode, number> = {test: mapAt, agent: cue(copy.cues.agent), witness: cue(copy.cues.witness), gate: Math.min(cue(copy.cues.gate) - fps * 0.4, speechDuration - fps * 2), receipt: speechDuration - fps * 1.6, official: speechDuration - fps * 1.6};
  const visible = (Object.keys(at) as MapNode[]).filter((key) => frame >= at[key]);
  return <AbsoluteFill style={{background: palette.page}}>
    {frame < mapAt && <Reveal style={{position: 'absolute', inset: '170px 128px 240px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center'}}>
      <div style={{fontSize: 280, fontWeight: 500, letterSpacing: -8}}>{copy.title}</div>
      <div style={{fontSize: 72, maxWidth: 1940, lineHeight: 1.35, color: palette.secondary, marginTop: 38}}>{copy.tagline}</div>
    </Reveal>}
    {frame >= mapAt && <>
      <Reveal at={mapAt} style={{position: 'absolute', left: 128, right: 128, top: 180, textAlign: 'center', fontSize: 108, fontWeight: 500, letterSpacing: -2}}>{copy.title}</Reveal>
      <div style={{position: 'absolute', left: 128, top: 365}}><ArchitectureMap visibleNodes={visible} nodeFrames={at} litNodes={visible.filter((n) => n === 'agent' || n === 'witness' || n === 'gate')}/></div>
      {frame >= at.gate && <Reveal at={at.gate} style={{position: 'absolute', left: 128, right: 128, top: 1070, textAlign: 'center', fontSize: 60, color: palette.accent}}>{copy.architecture.title}</Reveal>}
    </>}
  </AbsoluteFill>;
}
