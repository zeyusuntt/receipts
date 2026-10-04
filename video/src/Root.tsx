import { Composition } from "remotion";
import { Video } from "./Video";

export const FPS = 30;
export const WIDTH = 2560;
export const HEIGHT = 1440;
export const SECONDS = 170;

export const Root: React.FC = () => (
  <Composition
    id="Receipts"
    component={Video}
    durationInFrames={SECONDS * FPS}
    fps={FPS}
    width={WIDTH}
    height={HEIGHT}
  />
);
