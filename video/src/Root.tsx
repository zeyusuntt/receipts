import { Composition } from "remotion";
import { Video } from "./Video";
import {ArchitectureStill} from './ArchitectureStill';
import {Cover} from './Cover';
import {timeline} from './content';
import {totalFrames} from './timing';

export const FPS = timeline.fps;
export const WIDTH = 2560;
export const HEIGHT = 1440;
export const SECONDS = timeline.total_s;

export const Root: React.FC = () => <>
  <Composition
    id="Receipts"
    component={Video}
    durationInFrames={totalFrames(SECONDS, FPS)}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
    defaultProps={{musicTrack: 'audio/music-wallpaper-norm.mp3', musicVolume: 0.08}}
  />
  <Composition id="ArchitectureMap" component={ArchitectureStill} durationInFrames={1} fps={FPS} width={WIDTH} height={HEIGHT}/>
  <Composition id="CoverWide" component={Cover} durationInFrames={60} fps={FPS} width={WIDTH} height={HEIGHT}/>
  <Composition id="CoverDevpost" component={Cover} durationInFrames={60} fps={FPS} width={2700} height={1800}/>
</>;
