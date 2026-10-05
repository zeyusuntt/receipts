import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import consoleBoxes from '../../public/captures/console/boxes.json';
import {copy, story} from '../content';
import {cueFrame, replayPlan} from '../timing';
import {fonts, palette} from '../theme';
import {ConsoleCapture} from '../components/ConsoleCapture';
import {PaperReceipt} from '../components/PaperReceipt';
import {TerminalReplay} from '../components/TerminalReplay';
import type {SceneProps} from './types';

const fill = (template: string, values: Record<string, string | number>) => Object.entries(values).reduce((text, [key, value]) => text.replaceAll(`{${key}}`, String(value)), template);
const number = (value: number) => value.toLocaleString('en-US');
const PR_CARD_TOP = 174;
const PR_CARD_HEIGHT = 910;
const PR_LINE_BUDGET = 48;

function wrapPrLine(line: string) {
  if (line.length <= PR_LINE_BUDGET) return [line];
  const lines: string[] = [];
  for (const word of line.split(' ')) {
    if (word.length > PR_LINE_BUDGET) throw new Error(`PR description token exceeds ${PR_LINE_BUDGET} characters: ${word}`);
    const candidate = lines.length === 0 || lines.at(-1) === '' ? word : `${lines.at(-1)} ${word}`;
    if (candidate.length <= PR_LINE_BUDGET - 1) {
      if (lines.length === 0) lines.push(candidate);
      else lines[lines.length - 1] = candidate;
    } else {
      lines.push(word);
    }
  }
  return lines;
}

export function Results({beat, sequenceFrom, speechDuration, sceneDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const n = story.numbers;
  const c = copy.results;
  const builtAt = cueFrame(beat, c.cues.built, fps, sequenceFrom, wordTimestamps);
  const tokensAt = cueFrame(beat, c.cues.tokens, fps, sequenceFrom, wordTimestamps);
  const sandboxesAt = cueFrame(beat, c.cues.sandboxes, fps, sequenceFrom, wordTimestamps);
  const receiptAt = cueFrame(beat, c.cues.reverify, fps, sequenceFrom, wordTimestamps);
  const fixAt = cueFrame(beat, c.cues.fix, fps, sequenceFrom, wordTimestamps);
  const fixMedia = {...story.media.fix, command_start_s: story.media.fix.command_end_s - story.media.fix.typing_excerpt_s};
  const fixPlan = replayPlan(fixMedia, ((sceneDuration ?? speechDuration) - fixAt) / fps, fps);
  const description = story.featured.pr_description.split('\n');
  const prTitle = description[0];
  if (!prTitle || description[1] !== '') throw new Error('PR description must start with a title and blank line');
  const prBody = description.slice(2);

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

    {frame >= receiptAt && frame < fixAt && <>
      <div style={{position: 'absolute', left: 128, top: 110}}><PaperReceipt compact checkAt={[receiptAt, receiptAt, receiptAt, receiptAt, receiptAt]} metaAt={receiptAt} stampAt={receiptAt}/></div>
      <div style={{position: 'absolute', left: 1348, right: 128, top: 110}}>
        <div style={{fontSize: 36, color: palette.secondary}}>{c.pr_description_label}</div>
      </div>
      <div data-pr-description-card data-card-top={PR_CARD_TOP} data-card-height={PR_CARD_HEIGHT} style={{position: 'absolute', left: 1348, right: 128, top: PR_CARD_TOP, height: PR_CARD_HEIGHT, boxSizing: 'border-box', padding: '38px 40px', border: `2px solid ${palette.border}`, borderRadius: 16, background: palette.paper, boxShadow: '0 22px 44px rgba(18,22,28,0.13)', overflow: 'hidden'}}>
        <div style={{fontSize: 44, lineHeight: 1.15, fontWeight: 600}}>{prTitle}</div>
        <div style={{fontFamily: fonts.mono, fontSize: 34, lineHeight: 1.28, marginTop: 28}}>
          {prBody.map((sourceLine, sourceIndex) => {
            if (!sourceLine) return <div key={`gap-${sourceIndex}`} style={{height: 18}}/>;
            const lines = wrapPrLine(sourceLine);
            const content = lines.map((line, lineIndex) => <div key={`${sourceIndex}-${lineIndex}`} data-pr-body-line>{line}{lineIndex < lines.length - 1 ? ' ' : ''}</div>);
            if (sourceLine.includes('re-verify:')) return <div key={`source-${sourceIndex}`} data-pr-reverify style={{margin: '10px -14px', padding: '9px 12px', border: `6px solid ${palette.rejected}`, borderRadius: 18, transform: 'rotate(-0.5deg)'}}>{content}</div>;
            return <div key={`source-${sourceIndex}`}>{content}</div>;
          })}
        </div>
      </div>
    </>}

    {frame >= fixAt && <TerminalReplay media={fixMedia} plan={fixPlan} startAt={fixAt} header={c.fix_header} recordingNote={fill(c.fix_recording_note, {seconds: story.media.fix.typing_excerpt_s})} waitLabel={copy.reverify.wait_label} speedSuffix={copy.reverify.speed_suffix} holdLabel={copy.reverify.hold_label} headerTop={60} controlsTop={130} panelTop={200} panelHeight={1010} videoStyle={{position: 'absolute', width: 2022, height: 1138, left: 141, top: -35}} focus={{x: -268, y: -930, scale: 1.675, at: fixPlan.segments[2].from + Math.round(fps * 0.5)}}/>}
  </AbsoluteFill>;
}
