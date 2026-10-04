import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {palette} from '../theme';
import {clamp} from '../components/Motion';
import type {SceneProps} from './types';

export function WhoAndNumbers({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const n = story.numbers;
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const tasksAt = cue(copy.cues.tasks);
  const claimedAt = cue(copy.cues.claimed);
  const falseAt = cue(copy.cues.false);
  const indistinguishableAt = cue(copy.cues.indistinguishable);
  const crossfadeFrames = Math.round(fps * 0.25);
  const lowerThirdOpacity = interpolate(frame, [fps * 3.1, fps * 3.5], [1, 0], clamp);
  const counterOpacity = (start: number, end?: number) => interpolate(frame, [start, start + crossfadeFrames], [0, 1], clamp) * (end === undefined ? 1 : interpolate(frame, [end, end + crossfadeFrames], [1, 0], clamp));
  const interval = copy.numbers.interval
    .replace('{confidence}', String(copy.numbers.confidence))
    .replace('{low}', String(n.ci[0]))
    .replace('{high}', String(n.ci[1]));

  return <AbsoluteFill style={{background: palette.page}}>
    <section data-number-composition style={{position: 'absolute', left: 128, top: 110, bottom: 220, width: 1240, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      <div data-number-heading style={{fontSize: 64, lineHeight: 1.12, fontWeight: 600, whiteSpace: 'nowrap'}}>{copy.numbers.tasks.replace('{tasks}', String(n.tasks)).replace('{repos}', String(n.repos))}</div>
      <div style={{fontSize: 40, lineHeight: 1.3, color: palette.secondary, marginTop: 12}}>{copy.numbers.rule}</div>
      <div data-dot-grid role="img" aria-label={`${n.tasks} tasks, ${frame >= claimedAt ? n.claimed : 0} claimed done, ${frame >= falseAt && frame < indistinguishableAt ? n.false_dones : 0} false dones`} style={{display: 'grid', gridTemplateColumns: 'repeat(10, 70px)', gap: 20, marginTop: 30, width: 880}}>
        {Array.from({length: n.tasks}, (_, i) => {
          const claimed = frame >= claimedAt && i < n.claimed;
          const falseDone = frame >= falseAt && frame < indistinguishableAt && i < n.false_dones;
          const state = falseDone ? 'false-done' : claimed ? 'claimed' : 'unclaimed';
          const color = falseDone ? palette.rejected : claimed ? palette.ink : palette.border;
          return <span key={i} data-state={state} style={{width: 70, height: 70, borderRadius: '50%', background: color}}/>;
        })}
      </div>
    </section>

    {frame < fps * 3.5 && <section data-lower-third-region style={{position: 'absolute', left: 1430, right: 128, top: 820, bottom: 220, display: 'flex', alignItems: 'flex-end'}}>
      <div data-lower-third style={{paddingLeft: 30, borderLeft: `6px solid ${palette.accent}`, opacity: lowerThirdOpacity}}>
        <div style={{fontSize: 64, lineHeight: 1.15, fontWeight: 600}}>{copy.byline.name}</div>
        <div style={{fontSize: 40, lineHeight: 1.25, color: palette.secondary, marginTop: 10}}>{copy.byline.detail}</div>
      </div>
    </section>
    }

    {frame >= tasksAt && frame < claimedAt + crossfadeFrames && <section data-number-counter-state="tasks" style={{position: 'absolute', left: 1430, right: 128, top: 110, bottom: 220, display: 'flex', flexDirection: 'column', justifyContent: 'center', textAlign: 'center', opacity: counterOpacity(tasksAt, claimedAt)}}>
      <div style={{fontSize: 220, letterSpacing: -9, lineHeight: 1, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{n.tasks}</div>
      <div style={{fontSize: 48, lineHeight: 1.3, marginTop: 28}}>{copy.numbers.tasks_short}</div>
    </section>}
    {frame >= claimedAt && frame < falseAt + crossfadeFrames && <section data-number-counter-state="claimed" style={{position: 'absolute', left: 1430, right: 128, top: 110, bottom: 220, display: 'flex', flexDirection: 'column', justifyContent: 'center', textAlign: 'center', opacity: counterOpacity(claimedAt, falseAt)}}>
      <div style={{fontSize: 220, letterSpacing: -9, lineHeight: 1, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{n.claimed}</div>
      <div style={{fontSize: 48, lineHeight: 1.3, marginTop: 28}}>{copy.numbers.claimed_short}</div>
    </section>}
    {frame >= falseAt && <section data-number-counter-state="false" style={{position: 'absolute', left: 1430, right: 128, top: 110, bottom: 220, display: 'flex', flexDirection: 'column', justifyContent: 'center', opacity: counterOpacity(falseAt)}}>
      <div style={{fontSize: 64, lineHeight: 1.1, color: palette.rejected, fontWeight: 600}}>{copy.numbers.false_count.replace('{false_dones}', String(n.false_dones)).replace('{claimed}', String(n.claimed))}</div>
      <div style={{fontSize: 220, letterSpacing: -9, lineHeight: 1, marginTop: 18, color: palette.rejected, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{n.false_done_pct}{copy.numbers.percent}</div>
      <div style={{fontSize: 48, lineHeight: 1.3, marginTop: 28}}>{copy.numbers.rate}</div>
      <div style={{fontSize: 36, lineHeight: 1.35, color: palette.secondary, marginTop: 24}}>{copy.numbers.grader} · {interval}</div>
    </section>}
  </AbsoluteFill>;
}
