import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {fonts, palette} from '../theme';
import {Stamp} from './Stamp';

const fill = (template: string, values: Record<string, string | number>) => Object.entries(values).reduce((text, [key, value]) => text.replaceAll(`{${key}}`, String(value)), template);
const formatNumber = (value: number) => value.toLocaleString('en-US');
const modelName = (modelId: string) => modelId.split('/').at(-1)!.replace(/-\d+b-.+$/i, '').split('-').map(part => /^\d/.test(part) ? part : part[0].toUpperCase() + part.slice(1)).join(' ');

export function PaperReceipt({checkAt, metaAt, stampAt, compact = false}: {checkAt: number[]; metaAt: number; stampAt: number; compact?: boolean}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const data = story.featured.receipt;
  const text = copy.proof.receipt;
  if (data.removed_or_skipped !== 0 || data.test_files_changed !== 0) throw new Error('Printed receipt copy requires zero removed, skipped, or test files changed');
  const checks = [
    fill(text.spec, {passed: data.target_tests, total: data.target_tests}),
    fill(text.kept, {kept: data.kept_tests}),
    fill(text.removed, {collected: data.collected_tests}),
    fill(text.scope, {files: data.files_changed}),
    fill(text.steps, {agent: data.agent_steps, witness: data.witness_steps}),
  ];
  const meta = [
    fill(text.attempts, {
      first_number: data.attempts[0].number,
      first_verdict: data.attempts[0].verdict,
      second_number: data.attempts[1].number,
      second_verdict: data.attempts[1].verdict,
    }),
    fill(text.model, {model: modelName(story.featured.model.model)}),
    fill(text.cost, {tokens: formatNumber(story.featured.cost.tokens), dollars: story.featured.cost.model_dollars.toFixed(2)}),
    fill(text.witness, {checkpoint: story.featured.checkpoint_id.slice(0, 8)}),
  ];
  const visibleChecks = compact ? checks.slice(0, 2) : checks;
  const width = compact ? 1100 : 1180;
  const finalHeight = compact ? 960 : 1080;
  const initialHeight = 360;
  const growFrames = Math.round(fps * 0.25);
  const printEvents = [...checkAt, ...meta.map((_, index) => metaAt + index * 2), stampAt];
  const lineGrowth = (finalHeight - initialHeight) / printEvents.length;
  const height = compact ? finalHeight : initialHeight + printEvents.reduce((total, at) => total + lineGrowth * interpolate(frame, [at - growFrames, at], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}), 0);
  const printComplete = compact || frame >= stampAt;
  const lineStyle = {minHeight: compact ? 48 : 50, whiteSpace: 'nowrap' as const};
  return <div data-paper-receipt data-final-height={finalHeight} data-print-complete={printComplete} style={{position: 'relative', width, height, boxSizing: 'border-box', padding: compact ? '42px 54px 96px' : '34px 54px 94px', background: palette.paper, color: palette.ink, fontFamily: fonts.mono, fontSize: 38, lineHeight: 1.18, clipPath: 'polygon(0 0,100% 0,100% 97%,97% 100%,94% 97%,91% 100%,88% 97%,85% 100%,82% 97%,79% 100%,76% 97%,73% 100%,70% 97%,67% 100%,64% 97%,61% 100%,58% 97%,55% 100%,52% 97%,49% 100%,46% 97%,43% 100%,40% 97%,37% 100%,34% 97%,31% 100%,28% 97%,25% 100%,22% 97%,19% 100%,16% 97%,13% 100%,10% 97%,7% 100%,4% 97%,0 100%)', filter: 'drop-shadow(0 28px 35px rgba(18,22,28,0.16))'}}>
    <div data-receipt-line style={{...lineStyle, fontWeight: 500}}>{text.header}</div>
    <div data-receipt-line style={lineStyle}>{story.featured.instance}</div>
    <div data-receipt-line style={{...lineStyle, paddingBottom: 14, borderBottom: `2px dashed ${palette.border}`}}>{fill(text.repo, {repo: story.featured.repo, revision: story.featured.revision})}</div>
    <div style={{marginTop: 18}}>
      {visibleChecks.map((line, index) => <div key={line} data-receipt-line style={{...lineStyle, opacity: frame >= checkAt[index] ? 1 : 0}}>{line}</div>)}
    </div>
    {!compact && <div style={{marginTop: 12, paddingTop: 14, borderTop: `2px dashed ${palette.border}`}}>
      {meta.map((line, index) => <div key={line} data-receipt-line style={{...lineStyle, opacity: frame >= metaAt + index * 2 ? 1 : 0}}>{line}</div>)}
    </div>}
    <div style={{position: 'absolute', right: 54, bottom: compact ? 88 : 70}}><Stamp verdict="VERIFIED" at={stampAt} size={compact ? 0.7 : 0.8}/></div>
  </div>;
}
