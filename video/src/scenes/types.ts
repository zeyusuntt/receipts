import type {Beat, WordTimestamp} from '../timing';
export type SceneProps = {beat: Beat; sequenceFrom: number; speechStart: number; speechDuration: number; sceneDuration?: number; wordTimestamps?: WordTimestamp[]};
