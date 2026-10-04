import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import type {SceneProps} from './types';

export function PilotStory({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = story.pilot_v1;
  const c = copy.pilot;
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const treeAt = cue(c.cues.tree);
  const publishedAt = cue(c.cues.published);
  const fixedAt = cue(c.cues.fixed);
  const rerunAt = cue(c.cues.rerun);
  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, right: 128, top: 125, textAlign: 'center', fontSize: 88, fontWeight: 600}}>{c.title}</div>
    {frame < treeAt && <div style={{position: 'absolute', left: 128, right: 128, top: 395, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 100}}>
      {[{label: c.gate_label, value: p.gate, color: palette.verified}, {label: c.official_label, value: p.official_resolved ? copy.proof.resolved : copy.proof.not_resolved, color: p.official_resolved ? palette.verified : palette.rejected}].map((pane, i) => <div key={pane.label} style={{background: palette.paper, border: `2px solid ${palette.border}`, borderRadius: 24, padding: '65px 40px', textAlign: 'center', minHeight: 330}}>
        <div style={{fontSize: 48, color: palette.secondary}}>{pane.label}</div>
        <div style={{fontSize: i ? 108 : 140, color: pane.color, marginTop: 60, fontWeight: 600}}>{i === 0 ? <span style={{display: 'inline-block', border: `9px solid ${pane.color}`, padding: '8px 30px', borderRadius: 8, transform: 'rotate(-3deg)'}}>{pane.value}</span> : pane.value}</div>
      </div>)}
    </div>}
    {frame >= treeAt && frame < publishedAt && <>
      <div data-pilot-tree style={{position: 'absolute', left: 250, right: 250, top: 220, bottom: 220, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
        <div style={{textAlign: 'center', fontSize: 64}}>{c.tree_title}</div>
        <div style={{fontFamily: fonts.mono, fontSize: 48, lineHeight: 1.5, marginTop: 54}}>
          <div style={{fontSize: 44, color: palette.secondary, marginBottom: 24}}>{p.instance}</div>
          <div style={{display: 'flex', alignItems: 'center', gap: 44, padding: '28px 30px', background: palette.paper, borderRadius: 16}}><span style={{color: palette.accent}}>{p.real_build_package}…</span><span style={{fontFamily: fonts.sans, fontSize: 40, color: palette.secondary}}>{c.real_label}</span></div>
          <div style={{marginTop: 35, borderLeft: `5px solid ${palette.rejected}`, padding: '22px 30px', background: '#FFF1E9', borderRadius: 16}}>
            <div style={{fontFamily: fonts.sans, fontSize: 48, color: palette.rejected, marginBottom: 22}}>{c.copy_label}</div>
            {p.shipped_files.map((file, i) => <div key={file} data-shipped-file={file} style={{color: palette.rejected, paddingLeft: 20, fontSize: 48}}><span style={{marginRight: 25, color: palette.secondary}}>{i === p.shipped_files.length - 1 ? '└─' : '├─'}</span>{file}</div>)}
          </div>
        </div>
      </div>
    </>}
    {frame >= publishedAt && <div data-pilot-checklist style={{position: 'absolute', left: 230, right: 230, top: 220, bottom: 220, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      {[{text: c.published, at: publishedAt}, {text: c.fixed.replace('{commit}', p.fix_commit), at: fixedAt}, {text: c.rerun, at: rerunAt}].map(item => <div key={item.text} style={{display: 'flex', alignItems: 'center', gap: 36, fontSize: 52, lineHeight: 1.35, padding: '42px 0', borderBottom: `2px solid ${palette.border}`}}><span style={{fontSize: 64, color: frame >= item.at ? palette.verified : palette.border}}>✓</span><span>{item.text}</span></div>)}
    </div>}
  </AbsoluteFill>;
}
