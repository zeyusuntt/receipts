import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy} from '../content';
import {fonts, palette} from '../theme';
export function Stamp({verdict, at, size = 1}: {verdict: 'VERIFIED' | 'REJECTED'; at: number; size?: number}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (frame < at) return null;
  const scale = spring({frame: frame - at, fps, config: {stiffness: 210, damping: 14, mass: 0.75}, durationInFrames: Math.round(fps * 0.65)});
  const color = verdict === 'VERIFIED' ? palette.verified : palette.rejected;
  return <div style={{display: 'inline-block', color, border: `${7 * size}px solid ${color}`, borderRadius: 8, padding: `${12 * size}px ${34 * size}px ${16 * size}px`, fontFamily: fonts.sans, fontSize: 68 * size, fontWeight: 600, letterSpacing: 5 * size, transform: `rotate(-3deg) scale(${scale})`, background: palette.paper}}>{copy.verdicts[verdict]}</div>;
}
