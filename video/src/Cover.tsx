import {AbsoluteFill, useVideoConfig} from 'remotion';
import {PaperReceipt} from './components/PaperReceipt';
import {copy, story} from './content';
import {fonts, palette} from './theme';

// The Devpost and YouTube cover: the name and the claim on the left, the real receipt on the right.
// Every number comes from story.json; the receipt is the video's own component in its final state.
export function Cover() {
  const {width, height} = useVideoConfig();
  const n = story.numbers;
  const receiptScale = Math.min(1, (height - 200) / 1080);
  return <AbsoluteFill style={{background: palette.page, color: palette.ink, fontFamily: fonts.sans}}>
    <div style={{position: 'absolute', left: 150, top: 0, bottom: 0, width: width - 1180 * receiptScale - 360, display: 'flex', flexDirection: 'column', justifyContent: 'center'}}>
      <div style={{fontSize: 230, lineHeight: 0.95, fontWeight: 600, letterSpacing: -8}}>{copy.title}</div>
      <div style={{fontSize: 64, lineHeight: 1.2, marginTop: 44, fontWeight: 500}}>The coding agent that isn't allowed to grade its own homework.</div>
      <div style={{display: 'flex', gap: 64, marginTop: 72, alignItems: 'flex-end'}}>
        <div>
          <div style={{fontSize: 40, color: palette.secondary}}>Agent on its own</div>
          <div style={{fontSize: 120, fontWeight: 600, color: palette.rejected, lineHeight: 1.05}}>{n.false_dones} of {n.claimed}</div>
          <div style={{fontSize: 40, color: palette.secondary}}>"done" were false</div>
        </div>
        <div>
          <div style={{fontSize: 40, color: palette.secondary}}>With Receipts</div>
          <div style={{fontSize: 120, fontWeight: 600, color: palette.verified, lineHeight: 1.05}}>0 of {n.verified}</div>
          <div style={{fontSize: 40, color: palette.secondary}}>shipped fixes false</div>
        </div>
      </div>
      <div style={{fontSize: 40, marginTop: 64, color: palette.accent, fontWeight: 500}}>NVIDIA Nemotron 3 Super on Nebius Token Factory</div>
      <div style={{fontFamily: fonts.mono, fontSize: 34, marginTop: 16, color: palette.secondary}}>{n.tasks} real SWE-rebench bugs · pre-registered</div>
    </div>
    <div style={{position: 'absolute', right: 150, top: (height - 1080 * receiptScale) / 2, width: 1180, height: 1080, transform: `scale(${receiptScale}) rotate(-2deg)`, transformOrigin: 'top right'}}>
      <PaperReceipt checkAt={[0, 0, 0, 0, 0]} metaAt={0} stampAt={0}/>
    </div>
  </AbsoluteFill>;
}
