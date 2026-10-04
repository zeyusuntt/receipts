import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import capture from '../../public/captures/site/featured_receipt.json';
import {copy, story} from '../content';
import {captureRegion, cueAnyFrame, cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {GateChecks} from '../components/GateChecks';
import {ScreenshotPushIn} from '../components/ScreenshotPushIn';
import type {SceneProps} from './types';

export function ChecksAndOfficial({beat, sequenceFrom, speechDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = copy.proof;
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const officialAt = cueAnyFrame(beat, p.official_cues, fps, sequenceFrom, wordTimestamps);
  const noModelAt = cueAnyFrame(beat, p.no_model_cues, fps, sequenceFrom, wordTimestamps);
  const resolved = story.featured.official[1];
  // The paper receipt alone, at its own aspect, so no clipped page shows beside it.
  const paper = captureRegion(capture, p.receipt_box);
  const receiptWidth = Math.round(850 * paper.width / paper.height);
  const agreement = story.featured.agreement[1];
  return <AbsoluteFill style={{background: palette.page}}>
    {frame < officialAt ? <>
      <div style={{position: 'absolute', left: 128, right: 128, top: 140, fontSize: 96, fontWeight: 500, textAlign: 'center'}}>{p.title}</div>
      <div style={{position: 'absolute', left: 160, right: 160, top: 320}}><GateChecks attempt={story.featured.attempts[1]} at={p.check_cues.map(cue)} evidence/></div>
      {frame >= noModelAt && <div style={{position: 'absolute', left: 128, right: 128, top: 1080, textAlign: 'center', fontSize: 76, fontWeight: 500, color: palette.accent}}>{p.no_model}</div>}
    </> : <>
      <div style={{position: 'absolute', left: 128, top: 180, width: 1040, textAlign: 'center', fontSize: 76, fontWeight: 500}}>{p.receipt_label}</div>
      <div style={{position: 'absolute', left: 128 + (1040 - receiptWidth) / 2, top: 300}}><ScreenshotPushIn page="featured_receipt" capture={capture} contains={p.receipt_box} width={receiptWidth} height={850} duration={speechDuration}/></div>
      <div style={{position: 'absolute', left: 1290, top: 180, width: 1142, textAlign: 'center', fontSize: 48, lineHeight: 1.3, fontWeight: 500}}>{p.official_label}</div>
      <div style={{position: 'absolute', left: 1290, top: 365, width: 1142, height: 785, boxSizing: 'border-box', border: `2px solid ${palette.border}`, background: palette.paper, borderRadius: 24, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center'}}>
        <div style={{fontFamily: fonts.mono, fontSize: 40, color: palette.secondary}}>{story.featured.instance}</div>
        <div style={{position: 'relative', fontSize: 150, fontWeight: 500, color: resolved ? palette.verified : palette.rejected, marginTop: 65, padding: '20px 45px'}}>{resolved ? p.resolved : p.not_resolved}
          <svg width="860" height="265" viewBox="0 0 860 265" style={{position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%, -50%)', overflow: 'visible'}} aria-hidden="true"><path d="M805 131C820 48 645 14 452 22C257 5 43 51 45 143C18 234 242 252 445 245C654 264 831 217 806 120" fill="none" stroke="#B92318" strokeWidth="8" strokeLinecap="round"/><path d="M778 110C814 24 485 2 271 35" fill="none" stroke="#B92318" strokeWidth="3" strokeLinecap="round"/></svg>
        </div>
        <div style={{fontFamily: fonts.mono, fontSize: 32, marginTop: 62, color: palette.secondary}}>{p.agreement[agreement as keyof typeof p.agreement] ?? agreement}</div>
      </div>
    </>}
  </AbsoluteFill>;
}
