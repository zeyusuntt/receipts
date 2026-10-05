import story from './content/story.json';
import timeline from './content/timeline.json';
import face from './content/face.json';
export {story, timeline, face};
export const copy = story.presentation;
export type BeatId = typeof timeline.beats[number]['id'];
