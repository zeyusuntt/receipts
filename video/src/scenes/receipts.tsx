import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import consoleBoxes from '../../public/captures/console/boxes.json';
import {copy} from '../content';
import {cueFrame} from '../timing';
import {palette} from '../theme';
import {ArchitectureMap, type MapNode} from '../components/ArchitectureMap';
import {ConsoleCapture} from '../components/ConsoleCapture';
import {Reveal} from '../components/Motion';
import type {SceneProps} from './types';

export function Receipts({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const mapAt = Math.round(fps * 3);
  const agentAt = cue(copy.cues.agent);
  const witnessAt = cue(copy.cues.witness);
  const gateAt = cue(copy.cues.gate);
  const litNodes: MapNode[] = frame >= gateAt ? ['gate'] : frame >= witnessAt ? ['witness'] : frame >= agentAt ? ['agent'] : [];

  return <AbsoluteFill style={{background: palette.page}}>
    {frame < mapAt && <Reveal style={{position: 'absolute', inset: '170px 128px 240px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center'}}>
      <div style={{fontSize: 220, fontWeight: 600, letterSpacing: -7}}>{copy.title}</div>
      <div style={{fontSize: 64, maxWidth: 1940, lineHeight: 1.35, color: palette.secondary, marginTop: 38}}>{copy.tagline}</div>
    </Reveal>}
    {frame >= mapAt && <>
      <div style={{position: 'absolute', left: 128, top: 120}}><ArchitectureMap litNodes={litNodes}/></div>
      {frame < witnessAt && <div style={{position: 'absolute', left: 128, right: 128, top: 800, textAlign: 'center', fontSize: 56, lineHeight: 1.3, color: palette.secondary}}>{copy.tagline}</div>}
      {frame >= witnessAt && frame < gateAt && <Reveal at={witnessAt} style={{position: 'absolute', left: 740, top: 680}}>
        <ConsoleCapture image="sandboxes-about" meta={consoleBoxes['sandboxes-about']} label={copy.architecture.console_label} width={1053} height={477}/>
      </Reveal>}
    </>}
  </AbsoluteFill>;
}
