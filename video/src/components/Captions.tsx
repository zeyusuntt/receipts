import {useCurrentFrame} from 'remotion';
import {timeline} from '../content';
import {beatCaptionChunks, frames, type Beat, type WordTimestamp} from '../timing';
import {fonts, layout} from '../theme';

// Timestamp values are global frames. A later recording can supply them by beat id.
export type CaptionTiming = Record<string, WordTimestamp[]>;
export function Captions({wordTimestamps, beats = timeline.beats}: {wordTimestamps?: CaptionTiming; beats?: Beat[]}) {
  const frame = useCurrentFrame();
  const beat = beats.find((b) => frame >= frames(b.start_s, timeline.fps) && frame < frames(b.end_s, timeline.fps));
  if (!beat) return null;
  const chunk = beatCaptionChunks(beat, timeline.fps, wordTimestamps?.[beat.id]).find((c) => frame >= c.start && frame < c.end);
  if (!chunk) return null;
  return <div style={{position: 'absolute', bottom: layout.captionBottom, left: 200, right: 200, display: 'flex', justifyContent: 'center', zIndex: 50}}>
    <div style={{fontFamily: fonts.sans, fontSize: 46, fontWeight: 400, lineHeight: 1.3, color: '#FFFFFF', background: 'rgba(11,13,16,0.86)', padding: '15px 32px 18px', borderRadius: 12, maxWidth: 2160, textAlign: 'center'}}>{chunk.text}</div>
  </div>;
}
