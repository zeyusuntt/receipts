import {interpolate, useCurrentFrame} from 'remotion';
import {clamp} from './Motion';
export function CountUp({value, at, duration, decimals = 0, suffix = ''}: {value: number; at: number; duration: number; decimals?: number; suffix?: string}) {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [at, at + Math.max(1, duration)], [0, 1], clamp);
  const eased = 1 - (1 - progress) ** 3;
  return <span style={{fontVariantNumeric: 'tabular-nums'}}>{(value * eased).toFixed(decimals)}{suffix}</span>;
}
