import {AbsoluteFill} from 'remotion';
import {fonts, palette} from '../theme';
import type {SceneProps} from './types';
export function Placeholder({beat}: SceneProps) {
  return <AbsoluteFill style={{background: palette.page, justifyContent: 'center', padding: '128px 180px 260px', boxSizing: 'border-box'}}>
    <div style={{fontFamily: fonts.mono, color: palette.accent, fontSize: 42, marginBottom: 50}}>{beat.id}</div>
    <div style={{fontSize: 65, lineHeight: 1.5, maxWidth: 2200}}>{beat.text}</div>
  </AbsoluteFill>;
}
