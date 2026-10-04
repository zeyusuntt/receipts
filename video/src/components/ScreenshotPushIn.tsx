import {Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {captureIssueRegion, captureRegion, type Capture} from '../timing';
import {palette} from '../theme';
import {clamp} from './Motion';
export function ScreenshotPushIn({page, capture, contains, width, height, duration, focus}: {page: string; capture: Capture; contains: string; width: number; height: number; duration: number; focus?: 'issue'}) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const region = focus === 'issue' ? captureIssueRegion(capture, contains) : captureRegion(capture, contains);
  const fit = Math.min(width / region.width, height / region.height);
  const push = interpolate(frame, [0, Math.max(1, duration - fps)], [1, 1.035], clamp);
  return <div style={{width, height, position: 'relative', overflow: 'hidden', borderRadius: 18, border: `1px solid ${palette.border}`, background: palette.page, boxShadow: '0 22px 80px rgba(18,22,28,0.09)'}}>
    <div style={{position: 'absolute', left: (width - region.width * fit) / 2, top: (height - region.height * fit) / 2, width: region.width * fit, height: region.height * fit, transform: `scale(${push})`, transformOrigin: 'center'}}>
      <Img src={staticFile(`captures/site/${page}.png`)} style={{position: 'absolute', width: region.pageWidth * fit, height: region.pageHeight * fit, maxWidth: 'none', left: -region.x * fit, top: -region.y * fit}} />
    </div>
  </div>;
}
