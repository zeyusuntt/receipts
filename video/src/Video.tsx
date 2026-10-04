import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {ReactNode} from 'react';
import {timeline} from './content';
import {frames, sequenceWindows} from './timing';
import {fonts, palette} from './theme';
import {Captions, type CaptionTiming} from './components/Captions';
import {CornerStrip} from './components/CornerStrip';
import {clamp} from './components/Motion';
import {ColdOpen} from './scenes/cold_open';
import {WhoAndNumbers} from './scenes/who_and_numbers';
import {Receipts} from './scenes/receipts';
import {FeaturedSetup} from './scenes/featured_setup';
import {AgentWorks} from './scenes/agent_works';
import {Rejected} from './scenes/rejected';
import {AppealPasses} from './scenes/appeal_passes';
import {ChecksAndOfficial} from './scenes/checks_and_official';
import {Reverify} from './scenes/reverify';
import {PilotStory} from './scenes/pilot_story';
import {Results} from './scenes/results';
import {Close} from './scenes/close';
import {Placeholder} from './scenes/Placeholder';

export type VideoProps = {musicTrack?: string | null; musicVolume?: number; wordTimestamps?: CaptionTiming};
export const scenes = {cold_open: ColdOpen, who_and_numbers: WhoAndNumbers, receipts: Receipts, featured_setup: FeaturedSetup, agent_works: AgentWorks, rejected: Rejected, appeal_passes: AppealPasses, checks_and_official: ChecksAndOfficial, reverify: Reverify, pilot_story: PilotStory, results: Results, close: Close};
function Transition({children, first}: {children: ReactNode; first: boolean}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <AbsoluteFill style={{opacity: first ? 1 : interpolate(frame, [0, Math.round(fps * 0.2)], [0, 1], clamp)}}>{children}</AbsoluteFill>;
}
export function Video({musicTrack = null, musicVolume = 0.08, wordTimestamps}: VideoProps) {
  const cornerBeat = timeline.beats.find((b) => b.id === 'receipts');
  return <AbsoluteFill style={{background: palette.page, color: palette.ink, fontFamily: fonts.sans}}>
    <Audio src={staticFile(timeline.voice)}/>
    {musicTrack && <Audio src={staticFile(musicTrack)} loop volume={(frame) => {
      const rejected = timeline.beats.find((b) => b.id === 'rejected');
      const close = timeline.beats.find((b) => b.id === 'close');
      const duck = rejected && frame >= frames(rejected.end_s - 3, timeline.fps) && frame <= frames(rejected.end_s, timeline.fps);
      return duck || (close && frame >= frames(close.start_s, timeline.fps)) ? 0 : musicVolume;
    }}/>}
    {sequenceWindows(timeline).map(({beat, from, durationInFrames, speechStart, speechDuration}, index) => {
      const Scene = scenes[beat.id as keyof typeof scenes] ?? Placeholder;
      return <Sequence key={beat.id} from={from} durationInFrames={durationInFrames} name={beat.id}>
        <Transition first={index === 0}><Scene beat={beat} sequenceFrom={from} speechStart={speechStart} speechDuration={speechDuration} sceneDuration={durationInFrames} wordTimestamps={wordTimestamps?.[beat.id]}/></Transition>
      </Sequence>;
    })}
    {cornerBeat && <Sequence from={frames(cornerBeat.start_s, timeline.fps)} name="sponsor"><CornerStrip/></Sequence>}
    <Captions wordTimestamps={wordTimestamps}/>
    {/* A scratch timeline is a placeholder voice: mark every frame so a draft cannot pass for the final cut. */}
    {timeline.source.startsWith('scratch') && <div data-draft style={{position: 'absolute', left: 64, top: 48, padding: '8px 18px', borderRadius: 8, background: palette.rejected, color: palette.paper, fontFamily: fonts.mono, fontSize: 30}}>DRAFT · placeholder voice</div>}
  </AbsoluteFill>;
}
