import {spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {copy, story} from '../content';
import {fonts, palette} from '../theme';

export type MapNode = 'test' | 'agent' | 'witness' | 'gate' | 'receipt' | 'official';
export type MapEdge = 'test-agent' | 'agent-witness' | 'witness-gate' | 'gate-receipt';
type Props = {litNodes?: MapNode[]; visibleNodes?: MapNode[]; nodeFrames?: Partial<Record<MapNode, number>>; edge?: MapEdge; edgeProgress?: number; showCheckpoint?: boolean; rejected?: boolean; width?: number; witnessBranch?: string};
export const mapPositions = {test: [0, 100, 320, 360], agent: [360, 100, 650, 360], witness: [1050, 100, 590, 360], gate: [1680, 100, 260, 360], receipt: [1980, 100, 276, 360], official: [1680, 500, 576, 100]} as const;
const paths = {'test-agent': [320, 360], 'agent-witness': [1010, 1050], 'witness-gate': [1640, 1680], 'gate-receipt': [1940, 1980]} as const;

export function ArchitectureMap({litNodes = [], visibleNodes = ['test', 'agent', 'witness', 'gate', 'receipt', 'official'], nodeFrames = {}, edge, edgeProgress = 0, showCheckpoint = false, rejected = false, width = 2304, witnessBranch}: Props) {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const a = copy.architecture;
  const labels: Record<MapNode, string[]> = {test: [a.test], agent: [a.agent, a.agent_detail, story.featured.model.model], witness: [a.witness, a.witness_detail, [a.witness_role, witnessBranch].filter(Boolean).join(' · ')], gate: [a.gate, a.gate_detail], receipt: [a.receipt], official: [a.official]};
  const scale = width / 2256;
  const height = visibleNodes.includes('official') ? 614 : 480;
  return <div style={{width, height: height * scale, position: 'relative'}}>
    <div style={{position: 'absolute', width: 2256, height, transform: `scale(${scale})`, transformOrigin: 'top left'}}>
      <svg width={2256} height={height} style={{position: 'absolute', inset: 0}}>
        <defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10" fill={palette.border}/></marker></defs>
        {Object.entries(paths).map(([key, [x1, x2]]) => {
          const [from, to] = key.split('-') as MapNode[];
          if (!visibleNodes.includes(from) || !visibleNodes.includes(to)) return null;
          return <g key={key}><path d={`M${x1 + 8} 280H${x2 - 16}`} stroke={palette.border} strokeWidth={4} markerEnd="url(#arrow)"/>
            {edge === key && <circle cx={x1 + (x2 - x1) * edgeProgress} cy={280} r={10} fill={palette.accent}/>}</g>;
        })}
        {visibleNodes.includes('official') && <path d="M2070 464V490" stroke={palette.border} strokeWidth={3} strokeDasharray="7 7"/>}
        {showCheckpoint && <path d="M749 90V54H1393V90" fill="none" stroke={palette.accent} strokeWidth={3} strokeDasharray="8 6"/>}
      </svg>
      {showCheckpoint && <div style={{position: 'absolute', left: 850, top: 0, fontFamily: fonts.mono, fontSize: 36, color: palette.accent, background: palette.page, padding: '8px 18px'}}>{a.checkpoint} · {story.featured.checkpoint_id.slice(0, 8)}</div>}
      {(Object.keys(mapPositions) as MapNode[]).map((node) => {
        if (!visibleNodes.includes(node)) return null;
        const [left, top, w, h] = mapPositions[node];
        const at = nodeFrames[node];
        const entrance = at === undefined ? 1 : spring({frame: frame - at, fps, config: {damping: 24, stiffness: 130}, durationInFrames: Math.round(fps * 0.65)});
        const lit = litNodes.includes(node);
        const color = rejected && node === 'gate' ? palette.rejected : palette.accent;
        return <div key={node} data-map-node={node} style={{position: 'absolute', left, top, width: w, height: h, boxSizing: 'border-box', opacity: entrance, transform: `translateY(${(1 - entrance) * 24}px)`, border: `${lit ? 3 : 2}px solid ${lit ? color : palette.border}`, borderRadius: 16, padding: node === 'official' ? '12px 18px' : node === 'receipt' ? '25px 14px' : '25px 20px', background: lit ? (rejected && node === 'gate' ? '#FFF1E9' : '#ECF0FF') : palette.paper, display: 'flex', flexDirection: 'column', justifyContent: 'center', boxShadow: lit ? '0 12px 28px rgba(35,70,200,0.06)' : undefined}}>
          <div style={{fontFamily: fonts.sans, fontSize: node === 'official' ? 40 : 56, lineHeight: 1.18, fontWeight: 500, color: lit ? color : palette.ink, whiteSpace: node === 'test' || node === 'witness' || node === 'official' ? 'normal' : 'nowrap'}}>{labels[node][0]}</div>
          {labels[node][1] && <div style={{fontFamily: fonts.sans, fontSize: 40, lineHeight: 1.3, color: palette.secondary, marginTop: 16, whiteSpace: 'nowrap'}}>{labels[node][1]}</div>}
          {labels[node][2] && <div style={{fontFamily: fonts.mono, fontSize: 36, lineHeight: 1.25, overflowWrap: 'anywhere', color: lit ? color : palette.noVerdict, marginTop: 22}}>{labels[node][2]}</div>}
        </div>;
      })}
    </div>
  </div>;
}
