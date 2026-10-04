import {fonts, palette} from '../theme';
import {Reveal} from './Motion';
export function LowerThird({title, detail, at = 0, top = 1090, centered = false, size = 64}: {title: string; detail?: string; at?: number; top?: number; centered?: boolean; size?: number}) {
  return <Reveal at={at} style={{position: 'absolute', left: 128, right: 128, top, textAlign: centered ? 'center' : 'left', paddingLeft: centered ? 0 : 32, borderLeft: centered ? undefined : `5px solid ${palette.accent}`}}>
    <div style={{fontFamily: fonts.sans, fontSize: size, lineHeight: 1.3, fontWeight: 500}}>{title}</div>
    {detail && <div style={{fontFamily: fonts.mono, color: palette.secondary, fontSize: 32, marginTop: 10}}>{detail}</div>}
  </Reveal>;
}
