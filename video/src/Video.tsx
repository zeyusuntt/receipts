import { AbsoluteFill } from "remotion";
import data from "./data.json";

// Placeholder until the beats are built; every number comes from data.json.
export const Video: React.FC = () => (
  <AbsoluteFill style={{ background: "#F4F5F7", color: "#12161C", justifyContent: "center", alignItems: "center", fontFamily: "IBM Plex Sans, system-ui, sans-serif" }}>
    <div style={{ fontSize: 160, fontWeight: 600 }}>Receipts</div>
    <div style={{ fontSize: 56, color: "#4B5563" }}>{`${data.A_false_pct}% of "done" was false`}</div>
  </AbsoluteFill>
);
