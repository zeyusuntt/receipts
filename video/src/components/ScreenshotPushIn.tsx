import {Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {captureIssueRegion, captureRegion, type Capture} from '../timing';
import {palette} from '../theme';
import {clamp} from './Motion';
// An issue crop shows only part of each long line: fade the right and bottom edges so the cut reads as deliberate.
const fadeMask = 'linear-gradient(to right, #000 78%, transparent 97%), linear-gradient(to bottom, #000 80%, transparent 98%)';
const fade = {maskImage: fadeMask, WebkitMaskImage: fadeMask, maskComposite: 'intersect', WebkitMaskComposite: 'source-in'} as const;
export function ScreenshotPushIn({page, capture, contains, width, height, duration, focus}: {page: string; capture: Capture; contains: string; width: number; height: number; duration: number; focus?: 'issue'}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const region = focus === 'issue' ? captureIssueRegion(capture, contains) : captureRegion(capture, contains);
  const fit = Math.min(width / region.width, height / region.height);
  const push = interpolate(frame, [0, Math.max(1, duration - fps)], [1, 1.035], clamp);
  return <div style={{width, height, position: 'relative', overflow: 'hidden', borderRadius: 18, border: `1px solid ${palette.border}`, background: focus === 'issue' ? palette.paper : palette.page, boxShadow: '0 22px 80px rgba(18,22,28,0.09)'}}>
    <div style={{position: 'absolute', inset: 0, ...(focus === 'issue' ? fade : {})}}>
    <div style={{position: 'absolute', left: (width - region.width * fit) / 2, top: (height - region.height * fit) / 2, width: region.width * fit, height: region.height * fit, transform: `scale(${push})`, transformOrigin: 'center'}}>
      <Img src={staticFile(`captures/site/${page}.png`)} style={{position: 'absolute', width: region.pageWidth * fit, height: region.pageHeight * fit, maxWidth: 'none', left: -region.x * fit, top: -region.y * fit}} />
    </div>
    </div>
  </div>;
}
