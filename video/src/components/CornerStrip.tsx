import {copy} from '../content';
import {fonts, palette} from '../theme';
export function CornerStrip() {
  return <div style={{position: 'absolute', top: 56, right: 128, display: 'flex', alignItems: 'center', gap: 18, fontFamily: fonts.sans, fontSize: 34, fontWeight: 500, color: palette.secondary, zIndex: 40}}>
    <span style={{width: 9, height: 9, background: palette.accent, borderRadius: 9}} />{copy.corner}
  </div>;
}
