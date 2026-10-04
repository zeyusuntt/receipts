import type {CSSProperties} from 'react';
import {Freeze, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {ReplayMedia, ReplayPlan} from '../timing';
import {frames, replaySourceSeconds} from '../timing';
import {fonts, palette} from '../theme';

type Props = {
  media: ReplayMedia & {path: string};
  plan: ReplayPlan;
  header: string;
  recordingNote: string;
  waitLabel: string;
  speedSuffix: string;
  holdLabel: string;
  headerTop: number;
  controlsTop: number;
  panelTop: number;
  panelHeight: number;
  videoStyle: CSSProperties;
  startAt?: number;
};

export function TerminalReplay({media, plan, header, recordingNote, waitLabel, speedSuffix, holdLabel, headerTop, controlsTop, panelTop, panelHeight, videoStyle, startAt = 0}: Props) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const replayFrame = frame - startAt;
  const current = plan.segments.find(segment => replayFrame >= segment.from && replayFrame < segment.from + segment.durationInFrames);
  const state = current ? current.rate > 1 ? 'waiting' : current === plan.segments[0] ? 'typing' : 'result' : 'hold';
  return <>
    <div data-terminal-replay data-replay-media={media.path} data-replay-state={state} data-replay-rates={plan.segments.map(segment => segment.rate).join(',')} data-replay-source-seconds={replaySourceSeconds(plan, replayFrame, fps).toFixed(3)}>
      <div style={{position: 'absolute', left: 128, right: 128, top: headerTop, textAlign: 'center', fontSize: 48, fontWeight: 500, lineHeight: 1.3, whiteSpace: 'nowrap'}}>{header}</div>
      <div style={{position: 'absolute', left: 128, right: 128, top: controlsTop, display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontFamily: fonts.mono, fontSize: 40}}>
        <span style={{color: palette.secondary}}>{recordingNote}</span>
        <span data-replay-rate={current?.rate ?? 0} style={{background: current?.rate && current.rate > 1 ? palette.accent : palette.ink, color: palette.paper, padding: '10px 20px', borderRadius: 8}}>{current ? `${current.rate > 1 ? waitLabel + ' · ' : ''}${current.rate.toFixed(current.rate > 1 ? 2 : 0)}${speedSuffix}` : holdLabel}</span>
      </div>
      <div style={{position: 'absolute', left: 128, right: 128, top: panelTop, height: panelHeight, borderRadius: 22, background: palette.black, overflow: 'hidden', boxShadow: '0 20px 65px rgba(18,22,28,0.12)'}}>
        {plan.segments.map((segment, index) => <Sequence key={index} from={startAt + segment.from} durationInFrames={segment.durationInFrames} layout="none">
          <OffthreadVideo src={staticFile(media.path)} trimBefore={frames(segment.sourceStart_s, fps)} playbackRate={segment.rate} muted style={videoStyle}/>
        </Sequence>)}
        <Sequence from={startAt + plan.holdFrom} layout="none"><Freeze frame={0}><OffthreadVideo src={staticFile(media.path)} trimBefore={frames(media.result_end_s, fps) - 1} muted style={videoStyle}/></Freeze></Sequence>
      </div>
    </div>
  </>;
}
