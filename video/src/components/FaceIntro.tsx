import {AbsoluteFill, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy} from '../content';
import {fonts, palette} from '../theme';
import {clamp} from './Motion';

// The narrator on camera for "Hi, I'm Zeyu. I build evaluations for AI agents." The clip is pre-cut and
// speed-matched to the narration (see content/face.json), so it plays from its first frame, muted:
// the voice is the narration's own audio at this point.
export function FaceIntro({path}: {path: string}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const nameIn = interpolate(frame, [Math.round(fps * 0.4), Math.round(fps * 0.75)], [0, 1], clamp);
  return <AbsoluteFill style={{background: palette.black}}>
    <OffthreadVideo src={staticFile(path)} muted style={{width: '100%', height: '100%', objectFit: 'cover'}}/>
    <div data-face-byline style={{position: 'absolute', left: 128, bottom: 260, opacity: nameIn, padding: '22px 34px', borderLeft: `6px solid ${palette.accent}`, background: 'rgba(11,13,16,0.72)', borderRadius: 6, color: palette.paper, fontFamily: fonts.sans}}>
      <div style={{fontSize: 64, lineHeight: 1.15, fontWeight: 600}}>{copy.byline.name}</div>
      <div style={{fontSize: 40, lineHeight: 1.25, marginTop: 10, color: '#D7DCE3'}}>{copy.byline.detail}</div>
    </div>
  </AbsoluteFill>;
}
