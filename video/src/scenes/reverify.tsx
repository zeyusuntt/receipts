import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame, replayPlan} from '../timing';
import {palette} from '../theme';
import {TerminalReplay} from '../components/TerminalReplay';
import type {SceneProps} from './types';

export function Reverify({beat, sequenceFrom, speechDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const media = story.media.reverify;
  const r = copy.reverify;
  const plan = replayPlan(media, speechDuration / fps, fps);
  const dockerAt = cueFrame(beat, r.docker_cue, fps, sequenceFrom, wordTimestamps);
  // Enlarge the terminal 1.1x, the most at which its widest line (x 74 to 2074 of 2560) still fits
  // the panel, and crop the empty space below its last line (y 695 of 1440).
  const videoStyle = {position: 'absolute' as const, width: 2816, height: 1584, left: -30, top: -47};
  return <AbsoluteFill style={{background: palette.page}}>
    <TerminalReplay media={media} plan={plan} header={r.label} recordingNote={r.recording_note} waitLabel={r.wait_label} speedSuffix={r.speed_suffix} holdLabel={r.hold_label} headerTop={160} controlsTop={270} panelTop={350} panelHeight={770} videoStyle={videoStyle}/>
    {frame >= dockerAt && <div style={{position: 'absolute', left: 128, right: 128, top: 1150, textAlign: 'center', fontSize: 40, color: palette.secondary}}>{r.docker_label}</div>}
  </AbsoluteFill>;
}
