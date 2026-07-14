import type { GantryPosition } from "../../types";
import { viz as themeViz } from "../../theme";
import { machineToSvg } from "../../utils/coordinates";

interface Props {
  position: GantryPosition;
  svgWidth: number;
  svgHeight: number;
  machineXRange: [number, number];
  machineYRange: [number, number];
}

export default function GantryMarker({
  position,
  svgWidth,
  svgHeight,
  machineXRange,
  machineYRange,
}: Props) {
  if (!position.connected) return null;

  const posX = position.work_x ?? position.x;
  const posY = position.work_y ?? position.y;
  const { sx, sy } = machineToSvg(
    posX,
    posY,
    svgWidth,
    svgHeight,
    machineXRange,
    machineYRange
  );
  const arm = 12;
  const labelY = Math.max(10, sy - 2);

  return (
    <g>
      <circle cx={sx} cy={sy} r={9} fill={themeViz.markerHalo} />
      <line x1={sx - arm} y1={sy} x2={sx + arm} y2={sy} stroke={themeViz.marker} strokeWidth={1.5} />
      <line x1={sx} y1={sy - arm} x2={sx} y2={sy + arm} stroke={themeViz.marker} strokeWidth={1.5} />
      <circle cx={sx} cy={sy} r={4} fill={themeViz.marker} stroke={themeViz.halo} strokeWidth={1} opacity={0.9} />
      <text x={sx + arm + 2} y={labelY} fill={themeViz.markerLabel} fontSize={8} fontWeight={600} stroke={themeViz.halo} strokeWidth={3} paintOrder="stroke" strokeLinejoin="round">
        HEAD
      </text>
    </g>
  );
}
