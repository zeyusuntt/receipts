import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueAnyFrame, cueFrame} from '../timing';
import {fonts, palette} from '../theme';
import {PaperReceipt} from '../components/PaperReceipt';
import type {SceneProps} from './types';

export function ChecksAndOfficial({beat, sequenceFrom, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const p = copy.proof;
  const cue = (phrase: string) => cueFrame(beat, phrase, fps, sequenceFrom, wordTimestamps);
  const checkAt = p.check_cues.map(cue);
  const noModelAt = cueAnyFrame(beat, p.no_model_cues, fps, sequenceFrom, wordTimestamps);
  const officialAt = cueAnyFrame(beat, p.official_cues, fps, sequenceFrom, wordTimestamps);
  const metaAt = checkAt.at(-1)! + 2;
  const stampAt = Math.min(officialAt - 2, metaAt + 10);
  const resolved = story.featured.official[1];
  const agreement = story.featured.agreement[1];

  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, top: 110}}><PaperReceipt checkAt={checkAt} metaAt={metaAt} stampAt={stampAt}/></div>
    <div style={{position: 'absolute', left: 1370, right: 128, top: 150, bottom: 220, display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center'}}>
      {frame >= noModelAt && frame < officialAt && <div style={{fontSize: 64, lineHeight: 1.25, fontWeight: 600, color: palette.accent}}>{p.no_model}</div>}
      {frame >= officialAt && <>
        <div style={{fontSize: 48, lineHeight: 1.3, fontWeight: 600}}>{p.official_label}</div>
        <div style={{fontFamily: fonts.mono, fontSize: 40, color: palette.secondary, marginTop: 55}}>{story.featured.instance}</div>
        <div style={{position: 'relative', fontSize: 150, fontWeight: 600, color: resolved ? palette.verified : palette.rejected, marginTop: 55, padding: '20px 45px'}}>{resolved ? p.resolved : p.not_resolved}
          <svg width="860" height="265" viewBox="0 0 860 265" style={{position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%, -50%) rotate(-0.7deg)', overflow: 'visible'}} aria-hidden="true"><path d="M805 131C820 48 645 14 452 22C257 5 43 51 45 143C18 234 242 252 445 245C654 264 831 217 806 120" fill="none" stroke={resolved ? palette.verified : palette.rejected} strokeWidth="6" strokeLinecap="round"/><path d="M778 110C814 24 485 2 271 35" fill="none" stroke={resolved ? palette.verified : palette.rejected} strokeWidth="3" strokeLinecap="round"/></svg>
        </div>
        <div style={{fontSize: 40, marginTop: 55, color: palette.secondary}}>{p.agreement[agreement as keyof typeof p.agreement] ?? agreement}</div>
      </>}
    </div>
  </AbsoluteFill>;
}
