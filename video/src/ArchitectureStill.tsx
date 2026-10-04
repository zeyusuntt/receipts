import {AbsoluteFill} from 'remotion';
import {ArchitectureMap} from './components/ArchitectureMap';
import {copy} from './content';
import {palette, fonts} from './theme';
export function ArchitectureStill() {
  return <AbsoluteFill style={{background: palette.page, color: palette.ink, fontFamily: fonts.sans}}>
    <div style={{position: 'absolute', left: 128, top: 220, fontSize: 145, letterSpacing: -5, fontWeight: 500}}>{copy.title}</div>
    <div style={{position: 'absolute', left: 128, top: 465, fontSize: 52, color: palette.secondary}}>{copy.architecture.title}</div>
    <div style={{position: 'absolute', left: 128, top: 660}}><ArchitectureMap litNodes={['agent', 'witness', 'gate']} showCheckpoint/></div>
  </AbsoluteFill>;
}
