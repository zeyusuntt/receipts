import {AbsoluteFill, Freeze, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {cueFrame, frames, replayPlan} from '../timing';
import {fonts, palette} from '../theme';
import type {SceneProps} from './types';

export function Reverify({beat, sequenceFrom, speechDuration, wordTimestamps}: SceneProps) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const media = story.media.reverify;
  const r = copy.reverify;
  const plan = replayPlan(media, speechDuration / fps, fps);
  const current = plan.segments.find(s => frame >= s.from && frame < s.from + s.durationInFrames);
  const dockerAt = cueFrame(beat, r.docker_cue, fps, sequenceFrom, wordTimestamps);
  // Enlarge the terminal 1.1x, the most at which its widest line (x 74 to 2074 of 2560) still fits
  // the panel, and crop the empty space below its last line (y 695 of 1440).
  const videoStyle = {position: 'absolute' as const, width: 2816, height: 1584, left: -30, top: -47};
  return <AbsoluteFill style={{background: palette.page}}>
    <div style={{position: 'absolute', left: 128, right: 128, top: 160, textAlign: 'center', fontSize: 48, fontWeight: 500, lineHeight: 1.3}}>{r.label}</div>
    <div style={{position: 'absolute', left: 128, right: 128, top: 270, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: fonts.mono, fontSize: 40}}>
      <span style={{color: palette.secondary}}>{r.recording_note}</span>
      <span data-replay-rate={current?.rate ?? 0} style={{background: current?.rate && current.rate > 1 ? palette.accent : palette.ink, color: palette.paper, padding: '10px 20px', borderRadius: 8}}>{current ? `${current.rate > 1 ? r.wait_label + ' · ' : ''}${current.rate.toFixed(current.rate > 1 ? 2 : 0)}${r.speed_suffix}` : r.hold_label}</span>
    </div>
    <div style={{position: 'absolute', left: 128, right: 128, top: 350, height: 770, borderRadius: 22, background: palette.black, overflow: 'hidden', boxShadow: '0 20px 65px rgba(18,22,28,0.12)'}}>
      {plan.segments.map((segment, i) => <Sequence key={i} from={segment.from} durationInFrames={segment.durationInFrames} layout="none">
        <OffthreadVideo src={staticFile(media.path)} trimBefore={frames(segment.sourceStart_s, fps)} playbackRate={segment.rate} muted style={videoStyle}/>
      </Sequence>)}
      <Sequence from={plan.holdFrom} layout="none"><Freeze frame={0}><OffthreadVideo src={staticFile(media.path)} trimBefore={frames(media.result_end_s, fps) - 1} muted style={videoStyle}/></Freeze></Sequence>
    </div>
    {frame >= dockerAt && <div style={{position: 'absolute', left: 128, right: 128, top: 1150, textAlign: 'center', fontSize: 40, color: palette.secondary}}>{r.docker_label}</div>}
  </AbsoluteFill>;
}
