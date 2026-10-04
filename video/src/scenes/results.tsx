import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {palette} from '../theme';
import type {SceneProps} from './types';

export function Results({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const n = story.numbers;
  const c = copy.results;
  const cards = [
    {value: String(n.verified), label: c.verified, color: palette.verified, cue: c.cues.verified},
    {value: String(n.shipped_false_dones), label: c.false, color: palette.ink, cue: c.cues.false},
    {value: `$${n.model_dollars_per_fix.toFixed(2)}`, label: c.cost, color: palette.accent, cue: c.cues.cost},
  ];
  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, right: 128, top: 160, textAlign: 'center', fontSize: 96, fontWeight: 500}}>{c.title.replace('{tasks}', String(n.tasks))}</div>
    <div style={{position: 'absolute', left: 128, right: 128, top: 400, display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 40}}>
      {cards.map(card => {
        const active = frame >= cueFrame(beat, card.cue, fps, sequenceFrom, wordTimestamps);
        return <div key={card.label} style={{boxSizing: 'border-box', minHeight: 535, border: `${active ? 3 : 2}px solid ${active ? card.color : palette.border}`, borderRadius: 24, background: palette.paper, padding: '70px 38px 55px', textAlign: 'center'}}>
          <div style={{fontSize: 190, letterSpacing: -6, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums', fontWeight: 500, color: active ? card.color : palette.noVerdict}}>{card.value}</div>
          <div style={{fontSize: 52, lineHeight: 1.25, marginTop: 44}}>{card.label}</div>
        </div>;
      })}
    </div>
    <div style={{position: 'absolute', left: 128, right: 128, top: 1050, textAlign: 'center', fontSize: 40, color: palette.secondary}}>{c.agreement.replace('{resolved}', String(n.gate_pass_officially_resolved[0])).replace('{passes}', String(n.gate_pass_officially_resolved[1]))}</div>
  </AbsoluteFill>;
}
