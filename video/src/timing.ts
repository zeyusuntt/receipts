export type AlignedWord = {w: string; start_s: number; end_s: number};
export type Beat = {id: string; text: string; start_s: number; end_s: number; words?: AlignedWord[]};
export type WordTimestamp = {word: string; start: number; end: number};
export type CaptionChunk = {text: string; start: number; end: number};
export type Capture = {scale: number; size: {width: number; height: number}; boxes: {tag: string; text: string; x: number; y: number; width: number; height: number}[]};

export const frames = (seconds: number, fps: number) => Math.round(seconds * fps);
export const totalFrames = (seconds: number, fps: number) => Math.ceil(seconds * fps);

export function sequenceWindows<T extends Omit<Beat, 'text'>>(timeline: {fps: number; total_s: number; beats: T[]}, overlapSeconds = 0.2) {
  const total = totalFrames(timeline.total_s, timeline.fps);
  return timeline.beats.map((beat, index) => {
    const from = index === 0 ? 0 : frames(beat.start_s, timeline.fps);
    const next = timeline.beats[index + 1];
    const end = next ? Math.min(total, frames(next.start_s + overlapSeconds, timeline.fps)) : total;
    return {beat, from, durationInFrames: end - from, speechStart: frames(beat.start_s, timeline.fps) - from, speechDuration: frames(beat.end_s, timeline.fps) - frames(beat.start_s, timeline.fps)};
  });
}

export function captionChunks(text: string, start: number, end: number, maxWords = 12, timestamps?: WordTimestamp[]): CaptionChunk[] {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const chunks: CaptionChunk[] = [];
  let first = 0;
  for (let i = 0; i < words.length; i++) {
    const sentenceEnd = /[.!?]["'’”]?$/u.test(words[i]);
    if (sentenceEnd || i - first + 1 >= maxWords || i === words.length - 1) {
      chunks.push({text: words.slice(first, i + 1).join(' '), start: timestamps?.[first]?.start ?? Math.round(start + (end - start) * first / words.length), end: timestamps?.[i]?.end ?? Math.round(start + (end - start) * (i + 1) / words.length)});
      first = i + 1;
    }
  }
  return chunks;
}

const normalizedWord = (value: string) => value.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
export function beatWordTimestamps(beat: Beat, fps: number, fallback?: WordTimestamp[]): WordTimestamp[] | undefined {
  return beat.words?.length ? beat.words.map(({w, start_s, end_s}) => ({word: w, start: frames(start_s, fps), end: frames(end_s, fps)})) : fallback;
}

export function beatCaptionChunks(beat: Beat, fps: number, timestamps?: WordTimestamp[]) {
  const aligned = beatWordTimestamps(beat, fps, timestamps);
  return captionChunks(beat.words?.length ? beat.words.map(w => w.w).join(' ') : beat.text, frames(beat.start_s, fps), frames(beat.end_s, fps), 12, aligned);
}

// Aligned words in timeline.json take priority over legacy frame props.
export function cueFrame(beat: Beat, phrase: string, fps: number, sequenceFrom = frames(beat.start_s, fps), timestamps?: WordTimestamp[]) {
  const words = beat.words?.length ? beat.words.map(w => w.w) : beat.text.trim().split(/\s+/);
  const tokens = phrase.trim().split(/\s+/).map(normalizedWord);
  const index = words.findIndex((_, i) => tokens.every((word, j) => normalizedWord(words[i + j] ?? '') === word));
  if (index < 0) throw new Error(`Narration cue missing: ${beat.id}: ${phrase}`);
  const start = frames(beat.start_s, fps);
  const end = frames(beat.end_s, fps);
  const aligned = beatWordTimestamps(beat, fps, timestamps);
  return aligned?.[index]?.start !== undefined ? aligned[index].start - sequenceFrom : Math.round(start + (end - start) * index / words.length) - sequenceFrom;
}

export function cueAnyFrame(beat: Beat, phrases: readonly string[], fps: number, sequenceFrom: number, timestamps?: WordTimestamp[]) {
  for (const phrase of phrases) {
    try { return cueFrame(beat, phrase, fps, sequenceFrom, timestamps); } catch { /* Try the next approved narration variant. */ }
  }
  throw new Error(`Narration cue missing: ${beat.id}: ${phrases.join(', ')}`);
}

export type ReplayMedia = {duration_s: number; command_start_s: number; command_end_s: number; result_start_s: number; result_end_s: number};
export type ReplaySegment = {from: number; durationInFrames: number; sourceStart_s: number; sourceEnd_s: number; rate: number};
export type ReplayPlan = {segments: ReplaySegment[]; holdFrom: number; total: number};
export function replayPlan(media: ReplayMedia, durationSeconds: number, fps: number, holdSeconds = 1): ReplayPlan {
  if (!(0 <= media.command_start_s && media.command_start_s < media.command_end_s && media.command_end_s < media.result_start_s && media.result_start_s < media.result_end_s && media.result_end_s <= media.duration_s)) throw new Error('Invalid recording boundaries');
  const total = frames(durationSeconds, fps);
  const command = frames(media.command_end_s - media.command_start_s, fps);
  const result = frames(media.result_end_s - media.result_start_s, fps);
  const hold = frames(holdSeconds, fps);
  const waiting = total - command - result - hold;
  if (waiting < 1) throw new Error('Replay beat too short for normal-speed typing, results and hold');
  return {total, holdFrom: total - hold, segments: [
    {from: 0, durationInFrames: command, sourceStart_s: media.command_start_s, sourceEnd_s: media.command_end_s, rate: 1},
    {from: command, durationInFrames: waiting, sourceStart_s: media.command_end_s, sourceEnd_s: media.result_start_s, rate: (media.result_start_s - media.command_end_s) / (waiting / fps)},
    {from: command + waiting, durationInFrames: result, sourceStart_s: media.result_start_s, sourceEnd_s: media.result_end_s, rate: 1},
  ]};
}

export function replaySourceSeconds(plan: ReplayPlan, frame: number, fps: number) {
  const segment = plan.segments.find(s => frame < s.from + s.durationInFrames);
  if (!segment) return plan.segments[plan.segments.length - 1].sourceEnd_s;
  return Math.min(segment.sourceEnd_s, segment.sourceStart_s + Math.max(0, frame - segment.from) / fps * segment.rate);
}

export function captureRegion(capture: Capture, contains: string) {
  const matches = capture.boxes.filter((box) => box.text.toLowerCase().includes(contains.toLowerCase()));
  const box = matches.find((candidate) => ['section', 'div', 'table', 'pre'].includes(candidate.tag)) ?? matches[0];
  if (!box) throw new Error(`Capture box missing: ${contains}`);
  const k = capture.scale;
  return {x: box.x * k, y: box.y * k, width: box.width * k, height: box.height * k, pageWidth: capture.size.width * k, pageHeight: capture.size.height * k};
}

export function captureIssueRegion(capture: Capture, contains: string) {
  const matches = capture.boxes.filter((box) => box.text.toLowerCase().includes(contains.toLowerCase()));
  const line = matches.find((box) => box.tag === 'issue-line');
  const row = line ?? matches.find((box) => box.tag === 'dd' || box.tag === 'tr');
  const card = matches.find((box) => box.tag === 'section');
  let x: number, y: number, width: number, height: number;
  if (row) {
    x = Math.max(0, row.x - 24);
    y = Math.max(0, row.y - 8);
    width = Math.min(460, row.width + 48);
    height = line ? row.height + 48 : 180;
  } else {
    if (!card) throw new Error(`Capture issue missing: ${contains}`);
    const heading = capture.boxes.find((box) => box.tag === 'h2' && box.text === 'The plan' && box.y >= card.y && box.y < card.y + card.height);
    if (!heading) throw new Error('Capture plan heading missing');
    // Legacy captures only recorded cards. Frame the plan's first rows with their labels
    // (Repository, Base commit, Issue) so the viewer sees what the text is; long issue lines
    // run past the right edge, where ScreenshotPushIn fades them out.
    x = heading.x - 10;
    y = heading.y + heading.height + 14;
    width = 460;
    height = 220;
  }
  const k = capture.scale;
  return {x: x * k, y: y * k, width: width * k, height: height * k, pageWidth: capture.size.width * k, pageHeight: capture.size.height * k};
}
