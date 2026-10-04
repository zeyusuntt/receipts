import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {Reveal, clamp} from '../components/Motion';
import {CountUp} from '../components/CountUp';
import {LowerThird} from '../components/LowerThird';
import type {SceneProps} from './types';

export function WhoAndNumbers({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const n = story.numbers;
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const tasksAt = cue(copy.cues.tasks);
  const claimedAt = cue(copy.cues.claimed);
  const falseAt = cue(copy.cues.false);
  const rateAt = cue(copy.cues.rate);
  return <AbsoluteFill style={{background: palette.page}}>
    <LowerThird title={copy.byline} top={interpolate(frame, [tasksAt - fps * 0.6, tasksAt], [560, 185], clamp)} centered/>
    {frame >= tasksAt && <Reveal at={tasksAt} style={{position: 'absolute', left: 180, right: 180, top: 315}}>
      <div style={{textAlign: 'center', fontSize: 96, lineHeight: 1.1, fontWeight: 500, letterSpacing: -2}}>{copy.numbers.tasks.replace('{tasks}', String(n.tasks))}</div>
      <div style={{textAlign: 'center', fontSize: 40, lineHeight: 1.2, color: palette.secondary, marginTop: 12}}>{copy.numbers.rule}</div>
      <div style={{display: 'grid', gridTemplateColumns: '840px 1fr', gap: 155, alignItems: 'center', marginTop: 30}}>
        <div><div role="img" aria-label={`${n.tasks} tasks, ${frame >= claimedAt ? n.claimed : 0} claimed done, ${frame >= falseAt ? n.false_dones : 0} false dones`} style={{display: 'grid', gridTemplateColumns: 'repeat(10, 44px)', gap: 14, justifyContent: 'center'}}>
          {Array.from({length: n.tasks}, (_, i) => {
            const state = frame >= falseAt && i < n.false_dones ? 'false-done' : frame >= claimedAt && i < n.claimed ? 'claimed' : 'unclaimed';
            const color = state === 'false-done' ? palette.rejected : state === 'claimed' ? palette.ink : palette.border;
            return <span key={i} data-state={state} style={{width: 44, height: 44, borderRadius: '50%', background: color}}/>;
          })}
        </div><div style={{marginTop: 24, marginLeft: 90, display: 'flex', flexDirection: 'column', gap: 8, fontSize: 32, lineHeight: 1.2, color: palette.secondary}}>
          {copy.numbers.legend.map((label, i) => <div key={label} style={{display: 'flex', alignItems: 'center', gap: 14}}><span style={{width: 20, height: 20, borderRadius: '50%', background: [palette.ink, palette.rejected, palette.border][i], flexShrink: 0}}/>{label}</div>)}
        </div></div>
        <div style={{minWidth: 0}}>
          {frame >= rateAt ? <Reveal at={rateAt}>
            <div style={{fontSize: 270, letterSpacing: -12, lineHeight: 1.05, color: palette.rejected, fontWeight: 500}}><CountUp value={n.false_done_pct} at={rateAt} duration={fps * 0.9} decimals={1} suffix={copy.numbers.percent}/></div>
            <div style={{fontSize: 52, lineHeight: 1.3, marginTop: 28, maxWidth: 950}}>{copy.numbers.rate}</div>
            <div style={{fontSize: 40, color: palette.secondary, marginTop: 20}}>{copy.numbers.grader}</div>
            <div style={{fontSize: 32, color: palette.secondary, fontFamily: fonts.mono, marginTop: 30}}>{copy.numbers.interval.replace('{confidence}', String(copy.numbers.confidence)).replace('{low}', String(n.ci[0])).replace('{high}', String(n.ci[1]))}</div>
          </Reveal> : <>
            {frame >= claimedAt && <Reveal at={claimedAt} style={{fontSize: 76, lineHeight: 1.3}}>{copy.numbers.claimed.replace('{claimed}', String(n.claimed))}</Reveal>}
            {frame >= falseAt && <Reveal at={falseAt} style={{fontSize: 76, lineHeight: 1.3, color: palette.rejected, marginTop: 38}}>{copy.numbers.false.replace('{false_dones}', String(n.false_dones))}</Reveal>}
          </>}
        </div>
      </div>
    </Reveal>}
  </AbsoluteFill>;
}
