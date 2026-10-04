import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {ArchitectureMap, mapPositions} from '../components/ArchitectureMap';
import {GateChecks} from '../components/GateChecks';
import {NodeText} from '../components/NodeText';
import {Stamp} from '../components/Stamp';
import {clamp} from '../components/Motion';
import type {SceneProps} from './types';

export function AppealPasses({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const a = copy.appeal;
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const backAt = cue(a.cues.return);
  const patchAt = cue(a.cues.patch);
  const forkAt = cue(a.cues.fork);
  const checksAt = cue(a.cues.checks);
  const verifiedAt = cue(a.cues.verified);
  const attempt = story.featured.attempts[1];
  const evidence = story.featured.appeal_text.split('\n');
  const lines = [...evidence.slice(0, 2), evidence.filter(Boolean).at(-1)!];
  const progress = interpolate(frame, [backAt, Math.max(backAt + 1, patchAt - fps)], [0, 1], clamp);
  const center = (node: 'agent' | 'gate') => 128 + (mapPositions[node][0] + mapPositions[node][2] / 2) * 2304 / 2256;
  const left = interpolate(progress, [0, 1], [Math.min(1312, center('gate') - 560), center('agent') - 560], clamp);
  const title = frame >= verifiedAt ? a.verified_title : frame >= checksAt ? a.checks_title : frame >= forkAt ? a.witness_title : frame >= patchAt ? a.files_title : a.title;
  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, right: 128, top: 140, fontSize: 96, textAlign: 'center', fontWeight: 500}}>{title}</div>
    {frame < verifiedAt && <div style={{position: 'absolute', left: 128, top: 285}}><ArchitectureMap visibleNodes={frame >= forkAt ? ['test', 'agent', 'witness', 'gate', 'receipt'] : ['test', 'agent', 'gate', 'receipt']} litNodes={frame >= checksAt ? ['witness', 'gate'] : frame >= forkAt ? ['witness'] : frame >= patchAt ? ['agent'] : ['gate', 'agent']} showCheckpoint={frame >= forkAt} nodeFrames={{witness: forkAt}} witnessBranch={attempt.witness_branch}/></div>}
    {frame < patchAt && <div data-appeal-card style={{position: 'absolute', left, top: 445, width: 1120, boxSizing: 'border-box', background: palette.paper, border: `3px solid ${palette.accent}`, borderRadius: 24, padding: '28px 32px', boxShadow: '0 20px 55px rgba(18,22,28,0.14)'}}>
      {lines.map((line, i) => <div key={i} style={{fontFamily: fonts.mono, fontSize: 32, lineHeight: 1.45, marginTop: i ? 20 : 0, color: i === 0 ? palette.rejected : palette.ink}}><NodeText text={line}/></div>)}
    </div>}
    {frame >= patchAt && frame < forkAt && <div style={{position: 'absolute', left: 128, right: 128, top: 835, textAlign: 'center'}}>{story.featured.patch_files.map(file => <div key={file} style={{fontFamily: fonts.mono, fontSize: 64, lineHeight: 1.4, color: palette.accent}}>{file}</div>)}</div>}
    {frame >= forkAt && frame < checksAt && <div style={{position: 'absolute', left: 128, right: 128, top: 875, textAlign: 'center', fontFamily: fonts.mono, fontSize: 52, color: palette.accent}}>{copy.featured.witness_label.replace('{branch}', attempt.witness_branch)}<div style={{fontSize: 32, marginTop: 28}}>{copy.architecture.checkpoint} · {story.featured.checkpoint_id.slice(0, 8)}</div></div>}
    {frame >= checksAt && <div style={{position: 'absolute', left: 520, right: 520, top: frame >= verifiedAt ? 620 : 800}}><GateChecks attempt={attempt} at={copy.featured.checks.map((_, i) => checksAt + Math.min(fps * 0.12 * i, Math.max(0, verifiedAt - checksAt - 1)))}/></div>}
    {frame >= verifiedAt && <div style={{position: 'absolute', left: 128, right: 128, top: 355, textAlign: 'center'}}><Stamp verdict="VERIFIED" at={verifiedAt} size={1.6}/></div>}
  </AbsoluteFill>;
}
