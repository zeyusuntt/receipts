import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {NodeText} from '../components/NodeText';
import type {SceneProps} from './types';

export function AgentWorks({beat, sequenceFrom, speechDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const steps = story.featured.agent_steps;
  const findStep = (predicate: (step: typeof steps[number]) => boolean, label: string) => {
    const step = steps.find(predicate);
    if (!step) throw new Error(`Missing featured ${label} step`);
    return step;
  };
  const rows = [
    {label: copy.featured.actions.read, at: cue('reads the code'), step: findStep(step => step.kind === 'command' && step.display.includes('grep -n "_parse_ftp_time"'), 'read')},
    {label: copy.featured.actions.edit, at: cue('edits it'), step: findStep(step => step.kind === 'write' && step.display === 'write fs/ftpfs.py', 'edit')},
    {label: copy.featured.actions.test, at: cue('runs the tests'), step: findStep(step => step.display === 'pytest tests/test_ftpfs.py -v --tb=no -q', 'test')},
  ];
  const claimAt = Math.min(cue("says it's done"), speechDuration - Math.round(fps * 1.5));
  const showClaim = frame >= claimAt;

  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, right: 128, top: 105, textAlign: 'center', fontSize: 88, fontWeight: 600}}>{showClaim ? copy.featured.claim_label : copy.featured.agent_title}</div>
    {!showClaim && <>
      <div style={{position: 'absolute', left: 255, right: 255, top: 270, display: 'flex', flexDirection: 'column', gap: 28}}>
        {rows.map(({label, at, step}) => {
          const active = frame >= at;
          return <div key={label} data-agent-action={step.kind} data-active={active} style={{minHeight: 205, boxSizing: 'border-box', display: 'grid', gridTemplateColumns: '370px 1fr 150px', alignItems: 'center', gap: 34, padding: '28px 38px', border: `${active ? 4 : 2}px solid ${active ? palette.accent : palette.border}`, borderRadius: 22, background: active ? '#ECF0FF' : palette.paper}}>
            <div data-action-label style={{fontSize: 48, fontWeight: 600, whiteSpace: 'nowrap', color: active ? palette.accent : palette.noVerdict}}>{label}</div>
            <div style={{fontFamily: fonts.mono, fontSize: 44, lineHeight: 1.35, color: active ? palette.ink : palette.noVerdict}}><NodeText text={step.display}/></div>
            <div style={{fontFamily: fonts.mono, fontSize: 40, textAlign: 'right', color: active ? step.exit_code === 0 ? palette.verified : palette.rejected : palette.noVerdict}}>{step.kind === 'command' ? copy.featured.actions.exit.replace('{code}', String(step.exit_code)) : ''}</div>
          </div>;
        })}
      </div>
      <div style={{position: 'absolute', left: 128, right: 128, top: 1088, textAlign: 'center', fontSize: 40, color: palette.secondary}}>{copy.featured.action_count.replace('{steps}', String(steps.length))}</div>
    </>}
    {showClaim && <div style={{position: 'absolute', left: 250, right: 250, top: 350, textAlign: 'center'}}>
      <div style={{fontSize: 52, lineHeight: 1.45}}>“{story.featured.attempts[0].said}”</div>
      <div style={{fontFamily: fonts.mono, fontSize: 40, lineHeight: 1.4, color: palette.secondary, marginTop: 60}}>{story.featured.model.model}</div>
    </div>}
  </AbsoluteFill>;
}
