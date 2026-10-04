import {useCurrentFrame} from 'remotion';
import {copy, story} from '../content';
import {fonts, palette} from '../theme';
import {NodeText} from './NodeText';

export function shortEvidence(text: string) {
  return text.replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, uuid => uuid.slice(0, 8));
}

// A one-line reading of the gate's evidence for the checks table. Falls back to the evidence itself.
export function readableEvidence(id: string, text: string) {
  const targets = text.match(/^target tests passed: (.+)$/);
  if (id.startsWith('R1') && targets) return `${targets[1].split(', ').length} target tests passed`;
  const chains = text.match(/^agent chain .+ unbroken over (\d+) receipt\(s\); witness chain .+ unbroken over (\d+) receipt\(s\); applied digest matches$/);
  if (id.startsWith('R5') && chains) return `hash chain unbroken over ${chains[1]} agent and ${chains[2]} witness steps`;
  return shortEvidence(text).replace(/\b(\d+) (\w+)\(s\)/g, (_, n, word) => `${n} ${word}${n === '1' ? '' : 's'}`);
}

export function GateChecks({attempt, at, evidence = false, minimumFontSize = 34}: {attempt: typeof story.featured.attempts[number]; at: number[]; evidence?: boolean; minimumFontSize?: number}) {
  const frame = useCurrentFrame();
  return <div data-check-min-size={minimumFontSize}>{copy.featured.checks.map((check, i) => {
    const predicate = attempt.predicates.find(p => p.id === check.id);
    if (!predicate) throw new Error(`Missing predicate ${check.id}`);
    const active = frame >= at[i];
    const color = active ? predicate.passed ? palette.verified : palette.rejected : palette.noVerdict;
    return <div key={check.id} data-check={check.id} data-passed={active && predicate.passed} style={{display: 'grid', gridTemplateColumns: evidence ? '760px 1fr 130px' : '65px 1fr 130px', alignItems: 'center', gap: evidence ? 40 : 22, minHeight: evidence ? 120 : 70, padding: evidence ? '12px 0' : '0', borderBottom: `1px solid ${palette.border}`, boxSizing: 'border-box'}}>
      {evidence ? <div style={{fontSize: 48, lineHeight: 1.2}}>{check.label}</div> : <span style={{fontFamily: fonts.mono, fontSize: Math.max(34, minimumFontSize), color: palette.secondary}}>{check.id.split('_')[0]}</span>}
      <div style={{fontFamily: evidence ? fonts.mono : fonts.sans, fontSize: evidence ? 44 : 48, lineHeight: 1.4, color: evidence ? palette.secondary : palette.ink}}>{evidence ? <NodeText text={readableEvidence(check.id, predicate.evidence)}/> : check.label}</div>
      <span style={{fontFamily: fonts.mono, fontSize: Math.max(40, minimumFontSize), color, textAlign: 'right'}}>{active ? predicate.passed ? copy.featured.pass : copy.featured.fail : '·'}</span>
    </div>;
  })}</div>;
}
