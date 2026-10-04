import {Img, staticFile} from 'remotion';
import {fonts, palette} from '../theme';

type ConsoleHighlight = {label: string; x: number; y: number; w: number; h: number};
type ConsoleCaptureMeta = {
  size: number[];
  highlight: ConsoleHighlight;
};

export function ConsoleCapture({image, meta, label, width, height, focus, targetWidth}: {image: string; meta: ConsoleCaptureMeta; label: string; width: number; height: number; focus?: ConsoleHighlight; targetWidth?: number}) {
  const source = `captures/console/${image}.png`;
  const fit = focus && targetWidth ? targetWidth / focus.w : Math.min(width / meta.size[0], height / meta.size[1]);
  const imageWidth = meta.size[0] * fit;
  const imageHeight = meta.size[1] * fit;
  const left = focus ? (width - focus.w * fit) / 2 - focus.x * fit : (width - imageWidth) / 2;
  const top = focus ? (height - focus.h * fit) / 2 - focus.y * fit : (height - imageHeight) / 2;
  const highlight = focus ?? meta.highlight;
  const highlightWidth = Math.min(highlight.w * fit, imageWidth - highlight.x * fit);
  const highlightHeight = Math.min(highlight.h * fit, imageHeight - highlight.y * fit);
  return <div data-console-source={source} data-console-height={height} data-highlight-width={Math.round(highlightWidth)} style={{width, position: 'relative'}}>
    <div style={{position: 'relative', width, height, overflow: 'hidden', borderRadius: 18, border: `2px solid ${palette.border}`, background: palette.paper, boxShadow: '0 20px 65px rgba(18,22,28,0.12)'}}>
      <Img src={staticFile(source)} style={{position: 'absolute', left, top, width: imageWidth, height: imageHeight}}/>
      <div aria-label={highlight.label} style={{position: 'absolute', left: left + highlight.x * fit, top: top + highlight.y * fit, width: highlightWidth, height: highlightHeight, boxSizing: 'border-box', border: `6px solid ${palette.rejected}`, borderRadius: 12, transform: 'rotate(-0.6deg)', transformOrigin: 'center'}}/>
    </div>
    <div style={{fontFamily: fonts.sans, fontSize: 36, lineHeight: 1.25, color: palette.secondary, marginTop: 14}}>{label}</div>
  </div>;
}
