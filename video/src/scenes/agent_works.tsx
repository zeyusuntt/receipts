import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {fonts, palette} from '../theme';
import {ArchitectureMap} from '../components/ArchitectureMap';
import {LowerThird} from '../components/LowerThird';
import {NodeText} from '../components/NodeText';
import type {SceneProps} from './types';

export function AgentWorks({speechStart, speechDuration}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const speed = copy.featured.replay_speed;
  const claimAt = Math.max(speechStart, speechStart + speechDuration - Math.round(fps * 1.5));
  const showClaim = frame >= claimAt;
  const steps = story.featured.agent_steps;
  const progress = Math.max(0, Math.min(1, (frame - speechStart) / Math.max(1, claimAt - speechStart - 1)));
  const position = progress * (steps.length - 1);
  const active = Math.floor(position);
  const display = steps.map(step => step.display.replace(/\s+/g, ' '));
  // Plex Mono is 0.6em wide. Reserve 72 columns and enough room for every
  // real line, with six single-line rows or five rows around a long command.
  const heights = display.map(text => {
    let lines = 1, used = 0;
    for (const token of text.split(/(?<=::|\/)|(\s+)/).filter(Boolean)) {
      if (used + token.length > 72) {lines++; used = 0;}
      used += token.length;
    }
    return Math.max(110, lines * 60 + 16);
  });
  const tops = heights.map((_, i) => heights.slice(0, i).reduce((sum, h) => sum + h, 0));
  const previous = Math.max(0, tops[active] + heights[active] - 660);
  const following = Math.min(active + 1, steps.length - 1);
  const next = Math.max(0, tops[following] + heights[following] - 660);
  const scroll = previous + (next - previous) * (position - active);
  const first = Math.max(0, tops.findIndex((top, i) => top + heights[i] > scroll));
  const visible = steps.slice(first, first + 7);
  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, right: 128, top: 140, textAlign: 'center', fontSize: 96, fontWeight: 500}}>{showClaim ? copy.featured.claim_label : copy.featured.agent_title}</div>
    {!showClaim && <div style={{position: 'absolute', left: 128, right: 128, top: 275, height: 820, boxSizing: 'border-box', borderRadius: 24, background: palette.black, color: palette.paper, padding: '24px 32px', overflow: 'hidden'}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 32, color: '#ADB6C4'}}>
        <span style={{fontFamily: fonts.mono}}>{story.featured.attempts[0].number} · {story.featured.run_id}</span>
        <span>{copy.featured.replay_label} <span style={{fontFamily: fonts.mono, color: palette.paper, background: palette.accent, marginLeft: 20, padding: '6px 14px', borderRadius: 6}}>{speed}{copy.featured.speed_suffix}</span></span>
      </div>
      <div style={{marginTop: 20, height: 660, overflow: 'hidden'}}><div style={{transform: `translateY(${tops[first] - scroll}px)`}}>{visible.map((step, i) => {
        const newest = first + i === active;
        const pending = first + i > active;
        return <div key={step.seq} data-agent-step={step.seq} data-newest={newest} style={{height: heights[first + i], boxSizing: 'border-box', display: 'flex', alignItems: 'center', gap: 20, padding: '8px 16px', borderLeft: `4px solid ${newest ? '#A9BAFF' : 'transparent'}`, background: newest ? '#2346C8' : 'transparent', color: pending ? '#6D7889' : newest ? palette.white : '#BFC8D5'}}>
          <span style={{fontFamily: fonts.mono, fontSize: 32, minWidth: 52}}>{String(step.seq).padStart(2, '0')}</span>
          <div style={{fontFamily: fonts.mono, fontSize: 48, lineHeight: 1.25}}><NodeText text={display[first + i]}/></div>
        </div>;
      })}</div></div>
    </div>}
    {showClaim && <>
      <div style={{position: 'absolute', left: 128, top: 285}}><ArchitectureMap litNodes={['agent']} visibleNodes={['test', 'agent', 'witness', 'gate', 'receipt']}/></div>
      <div style={{position: 'absolute', left: 180, right: 180, top: 835, textAlign: 'center', fontFamily: fonts.sans, fontSize: 64, lineHeight: 1.4}}>“{story.featured.attempts[0].said}”</div>
    </>}
    <LowerThird title={story.featured.model.model} detail={copy.featured.model_suffix} top={1110} centered size={48}/>
  </AbsoluteFill>;
}
