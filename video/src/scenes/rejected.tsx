import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {ArchitectureMap} from '../components/ArchitectureMap';
import {Reveal, clamp} from '../components/Motion';
import {Stamp} from '../components/Stamp';
import {NodeText} from '../components/NodeText';
import type {SceneProps} from './types';

export function Rejected({beat, sequenceFrom, speechDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const attempt = story.featured.attempts[0];
  const forkAt = cue(copy.cues.fork);
  const patchAt = cue(copy.cues.patch);
  const checksAt = cue(copy.cues.tests);
  const stampAt = cue(copy.cues.rejected);
  const failedAt = stampAt - fps * 0.45;
  // The verdict first (R1 turns red, the stamp lands on "Rejected"), then the reason when the narration
  // gives it ("the spec still fails"): the heading and the failing test arrive together, not with the stamp.
  const whyAt = Math.max(stampAt + Math.round(fps * 0.5), cue(copy.cues.why));
  const forked = frame >= forkAt;
  const operation = story.featured.witness_receipts[0];
  const patchProgress = interpolate(frame, [patchAt, patchAt + fps * 0.8], [0, 1], clamp);
  const shortIds = (text: string) => text.replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, (uuid) => uuid.slice(0, 8));
  return <AbsoluteFill style={{background: palette.page}}>
    {frame >= whyAt && <div style={{position: 'absolute', left: 128, right: 128, top: 140, textAlign: 'center', fontSize: 88, fontWeight: 600, letterSpacing: -1}}>{copy.featured.rejected_title}</div>}
    {frame < failedAt && <div style={{position: 'absolute', left: 128, top: 155}}><ArchitectureMap visibleNodes={forked ? ['test', 'agent', 'witness', 'gate', 'receipt'] : ['test', 'agent', 'gate', 'receipt']} nodeFrames={{witness: forkAt}} litNodes={['agent', ...(forked ? ['witness'] as const : [])]} showCheckpoint={forked} edge={frame >= patchAt && frame < patchAt + fps ? 'agent-witness' : undefined} edgeProgress={patchProgress}/></div>}
    {frame >= patchAt && frame < patchAt + fps && <div style={{position: 'absolute', left: 1000 + patchProgress * 160, top: 630, padding: '12px 20px', fontFamily: fonts.mono, fontSize: 34, background: palette.accent, borderRadius: 7, color: palette.paper}}>{copy.architecture.patch}</div>}
    {forked && <div style={{position: 'absolute', left: 128, right: 128, top: frame >= failedAt ? 1110 : 765, textAlign: 'center', fontFamily: fonts.mono, fontSize: 34, color: palette.secondary, display: 'flex', flexDirection: 'column', gap: 8}}>
      <div>{shortIds(copy.featured.witness_label.replace('{branch}', attempt.witness_branch))} · {shortIds(operation.receipt_id)} · {shortIds(operation.image_after)}</div>
      <div>{shortIds(story.featured.image)}</div>
    </div>}
    <div style={{position: 'absolute', left: 128, right: 128, top: frame >= failedAt ? 740 : 885, display: 'flex', gap: 52}}>
      <div style={{width: 940}}>{copy.featured.checks.map((check, i) => {
        const predicate = attempt.predicates.find((p) => p.id === check.id);
        if (!predicate) throw new Error(`Missing predicate ${check.id}`);
        const at = checksAt + (failedAt - checksAt - fps * 0.5) * i / 4;
        if (frame < at) return null;
        const pending = !predicate.passed && frame < failedAt;
        const color = pending ? palette.noVerdict : predicate.passed ? palette.verified : palette.rejected;
        return <Reveal key={check.id} at={at} style={{height: 68, borderBottom: `1px solid ${palette.border}`, display: 'flex', alignItems: 'center', gap: 24}}>
          <span style={{fontFamily: fonts.mono, fontSize: 34, minWidth: 55, color: palette.secondary}}>{check.id.split('_')[0]}</span>
          <span style={{fontSize: 48, flex: 1}}>{check.label}</span>
          <span style={{fontFamily: fonts.mono, fontSize: 40, color, minWidth: 110, textAlign: 'right'}}>{pending ? '·' : predicate.passed ? copy.featured.pass : copy.featured.fail}</span>
        </Reveal>;
      })}</div>
      {frame >= whyAt && <div style={{flex: 1, height: 340, boxSizing: 'border-box', position: 'relative', padding: '30px 36px', border: `3px solid ${palette.rejected}`, borderRadius: 24, background: '#FFF1E9'}}>
        <div style={{fontFamily: fonts.mono, fontSize: 34, color: palette.rejected, marginBottom: 22}}>{attempt.predicates[0].id.split('_')[0]} · {copy.featured.checks.find((check) => check.id === attempt.predicates[0].id)?.label}</div>
        <div style={{fontFamily: fonts.mono, fontSize: 44, lineHeight: 1.55}}><NodeText text={shortIds(attempt.predicates[0].evidence)}/></div>
      </div>}
    </div>
    <div data-stamp-area="rejection" style={{position: 'absolute', left: 128, right: 128, top: 430, textAlign: 'center'}}><Stamp verdict="REJECTED" at={stampAt} size={1.6}/></div>
  </AbsoluteFill>;
}
