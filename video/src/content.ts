import story from './content/story.json';
import timeline from './content/timeline.json';
export {story, timeline};
export const copy = story.presentation;
export type BeatId = typeof timeline.beats[number]['id'];
