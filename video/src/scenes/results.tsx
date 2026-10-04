import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import consoleBoxes from '../../public/captures/console/boxes.json';
import {copy, story} from '../content';
import {cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {ConsoleCapture} from '../components/ConsoleCapture';
import {PaperReceipt} from '../components/PaperReceipt';
import type {SceneProps} from './types';

const fill = (template: string, values: Record<string, string | number>) => Object.entries(values).reduce((text, [key, value]) => text.replaceAll(`{${key}}`, String(value)), template);
const number = (value: number) => value.toLocaleString('en-US');

export function Results({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const n = story.numbers;
  const c = copy.results;
  const builtAt = cueFrame(beat, c.cues.built, fps, sequenceFrom, wordTimestamps);
  const tokensAt = cueFrame(beat, c.cues.tokens, fps, sequenceFrom, wordTimestamps);
  const sandboxesAt = cueFrame(beat, c.cues.sandboxes, fps, sequenceFrom, wordTimestamps);
  const receiptAt = cueFrame(beat, c.cues.reverify, fps, sequenceFrom, wordTimestamps);
  const command = fill(c.receipt_command, {instance: story.featured.instance});
  const commandWords = command.split(' ');
  const commandLead = commandWords.slice(0, 2).join(' ');
  const commandPath = commandWords.slice(2).join(' ');

  return <AbsoluteFill style={{background: palette.page}}>
    {frame < builtAt && <>
      <div data-impact-grid style={{position: 'absolute', left: 128, right: 128, top: 110, bottom: 220, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center'}}>
        <div style={{width: '100%', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 96, textAlign: 'center'}}>
          <div data-impact-column-left style={{borderRight: `2px solid ${palette.border}`, padding: '0 72px'}}>
            <div data-impact-header style={{fontSize: 56, fontWeight: 600}}>{c.before.title}</div>
            <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 30, marginTop: 44}}><div data-impact-number={n.claimed} style={{fontSize: 160, lineHeight: 1, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{n.claimed}</div><div data-impact-label style={{fontSize: 56}}>{c.before.claimed}</div></div>
            <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 30, marginTop: 18}}><div data-impact-number={n.false_dones} style={{fontSize: 260, lineHeight: 1, fontWeight: 600, color: palette.rejected, fontVariantNumeric: 'tabular-nums'}}>{n.false_dones}</div><div data-impact-label style={{fontSize: 56}}>{c.before.false}</div></div>
          </div>
          <div style={{padding: '0 72px'}}>
            <div data-impact-header style={{fontSize: 56, fontWeight: 600}}>{c.with_receipts.title}</div>
            <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 30, marginTop: 44}}><div data-impact-number={n.verified} style={{fontSize: 160, lineHeight: 1, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{n.verified}</div><div data-impact-label style={{fontSize: 56}}>{c.with_receipts.shipped}</div></div>
            <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: 30, marginTop: 18}}><div data-impact-number={n.shipped_false_dones} style={{fontSize: 260, lineHeight: 1, fontWeight: 600, color: palette.verified, fontVariantNumeric: 'tabular-nums'}}>{n.shipped_false_dones}</div><div data-impact-label style={{fontSize: 56}}>{c.with_receipts.false}</div></div>
          </div>
        </div>
        <div data-impact-grader style={{fontSize: 40, color: palette.secondary, marginTop: 46}}>{fill(c.official, {tasks: n.tasks})}</div>
        <div data-impact-cost style={{fontSize: 56, color: palette.accent, marginTop: 30}}>${n.model_dollars_per_fix.toFixed(2)} {copy.results.cost}</div>
      </div>
    </>}

    {frame >= builtAt && frame < tokensAt && <>
      <div style={{position: 'absolute', left: 128, right: 128, top: 72, textAlign: 'center', fontSize: 88, fontWeight: 600}}>{c.built.title}</div>
      <div style={{position: 'absolute', left: 128, top: 220}}><ConsoleCapture image="usage" meta={consoleBoxes.usage} label={fill(c.built.usage, {period: consoleBoxes.usage.period})} width={1040} height={610}/></div>
      <div style={{position: 'absolute', right: 128, top: 220}}><ConsoleCapture image="operations" meta={consoleBoxes.operations} label={c.built.operations} width={1040} height={610}/></div>
    </>}

    {frame >= tokensAt && frame < sandboxesAt && <>
      <div data-proof-heading style={{position: 'absolute', left: 128, right: 128, top: 72, textAlign: 'center', fontSize: 88, lineHeight: 1.1, fontWeight: 600}}>{c.built.title}</div>
      <div data-proof-panel style={{position: 'absolute', left: 128, top: 200}}><ConsoleCapture image="usage" meta={consoleBoxes.usage} focus={consoleBoxes.usage.highlight} targetWidth={2200} label={c.built.usage} width={2304} height={610}/></div>
      <div style={{position: 'absolute', left: 128, right: 128, top: 900, textAlign: 'center'}}>
        <div style={{fontSize: 120, lineHeight: 1, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{number(n.scale.tokens)}</div>
        <div data-proof-label style={{fontSize: 48, marginTop: 18, whiteSpace: 'nowrap'}}>{c.built.tokens}</div>
        <div data-proof-label style={{fontSize: 40, marginTop: 12, whiteSpace: 'nowrap'}}>{fill(c.built.over, {tasks: n.tasks})}</div>
      </div>
    </>}

    {frame >= sandboxesAt && frame < receiptAt && <>
      <div data-proof-heading style={{position: 'absolute', left: 128, right: 128, top: 72, textAlign: 'center', fontSize: 88, lineHeight: 1.1, fontWeight: 600}}>{c.built.title}</div>
      <div data-proof-panel style={{position: 'absolute', left: 128, top: 200}}><ConsoleCapture image="operations" meta={consoleBoxes.operations} focus={consoleBoxes.operations.push_in} targetWidth={2200} label={c.built.operations} width={2304} height={680}/></div>
      <div style={{position: 'absolute', left: 390, right: 390, top: 950, textAlign: 'center'}}>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 120}}>
          <div><div style={{fontSize: 120, lineHeight: 1, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{number(n.scale.sandboxes)}</div><div data-proof-label style={{fontSize: 48, marginTop: 12, whiteSpace: 'nowrap'}}>{c.built.sandboxes}</div></div>
          <div><div style={{fontSize: 120, lineHeight: 1, fontWeight: 600, fontVariantNumeric: 'tabular-nums'}}>{number(n.scale.steps)}</div><div data-proof-label style={{fontSize: 48, marginTop: 12, whiteSpace: 'nowrap'}}>{c.built.steps}</div></div>
        </div>
        <div data-proof-label style={{fontSize: 40, marginTop: 12, whiteSpace: 'nowrap'}}>{fill(c.built.over, {tasks: n.tasks})}</div>
      </div>
    </>}

    {frame >= receiptAt && <>
      <div style={{position: 'absolute', left: 128, top: 110}}><PaperReceipt compact checkAt={[receiptAt, receiptAt, receiptAt, receiptAt, receiptAt]} metaAt={receiptAt} stampAt={receiptAt}/></div>
      <div data-command-break="after-reverify" style={{position: 'absolute', left: 1320, right: 128, top: 455, padding: '38px 40px', borderRadius: 20, background: palette.black, color: palette.paper, fontFamily: fonts.mono, fontSize: 36, lineHeight: 1.45}}>
        <div style={{whiteSpace: 'nowrap'}}>{commandLead}</div>{' '}
        <div style={{whiteSpace: 'nowrap'}}>{commandPath}</div>
      </div>
    </>}
  </AbsoluteFill>;
}
