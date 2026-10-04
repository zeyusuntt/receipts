import type {CSSProperties, ReactNode} from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';

export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
export function Reveal({at = 0, children, style}: {at?: number; children: ReactNode; style?: CSSProperties}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const elapsed = frame - at;
  const progress = spring({frame: elapsed, fps, config: {damping: 22, stiffness: 125, mass: 0.9}, durationInFrames: Math.round(fps * 0.65)});
  return <div style={{opacity: interpolate(elapsed, [0, fps * 0.18], [0, 1], clamp), transform: `translateY(${(1 - progress) * 32}px)`, ...style}}>{children}</div>;
}
