import type { Coordinate3D, GeometryResponse } from "../../types";
import { viz as themeViz } from "../../theme";
import { toSvgRect, getBoundsCenter, getPositionBounds } from "./renderUtils";

interface Props {
  label: string;
  geometry: GeometryResponse | null;
  anchor: Coordinate3D | null;
  childPositions: Coordinate3D[];
  svgWidth: number;
  svgHeight: number;
  machineXRange: [number, number];
  machineYRange: [number, number];
}

export default function HolderRenderer({
  label,
  geometry,
  anchor,
  childPositions,
  svgWidth,
  svgHeight,
  machineXRange,
  machineYRange,
}: Props) {
  if (!geometry) {
    return null;
  }

  const bounds = getPositionBounds(childPositions);
  const center = bounds
    ? getBoundsCenter(bounds)
    : anchor
      ? { x: anchor.x, y: anchor.y }
      : null;

  if (!center) {
    return null;
  }

  const length = geometry.length ?? 20;
  const width = geometry.width ?? 20;
  const rect = toSvgRect(
    center.x - length * 0.5,
    center.y - width * 0.5,
    center.x + length * 0.5,
    center.y + width * 0.5,
    svgWidth,
    svgHeight,
    machineXRange,
    machineYRange,
  );
  const labelY = rect.y > 16 ? rect.y - 4 : rect.y + 13;

  return (
    <g>
      <rect
        x={rect.x}
        y={rect.y}
        width={rect.width}
        height={rect.height}
        fill={themeViz.holderFill}
        stroke={themeViz.holderStroke}
        strokeWidth={1.5}
        strokeDasharray="6 3"
        rx={4}
      />
      <text x={rect.x + 4} y={labelY} fill={themeViz.holderLabel} fontSize={10} fontWeight={500} stroke={themeViz.halo} strokeWidth={3} paintOrder="stroke" strokeLinejoin="round">
        {label}
      </text>
    </g>
  );
}
