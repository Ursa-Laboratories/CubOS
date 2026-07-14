import type { WellPlateConfig, WellPosition } from "../../types";
import { viz as themeViz } from "../../theme";
import { machineToSvg, mmToSvgPixels } from "../../utils/coordinates";

interface Props {
  config: WellPlateConfig;
  wells: Record<string, WellPosition>;
  svgWidth: number;
  svgHeight: number;
  machineXRange: [number, number];
  machineYRange: [number, number];
}

export default function WellPlateRenderer({
  config,
  wells,
  svgWidth,
  svgHeight,
  machineXRange,
  machineYRange,
}: Props) {
  const wellRadius = Math.max(1.5, mmToSvgPixels(3, svgWidth, svgHeight, machineXRange, machineYRange));
  const wellEntries = Object.values(wells);
  if (wellEntries.length === 0) return null;

  // Derive bounding box from actual well positions (handles any orientation).
  const pitch = Math.max(Math.abs(config.x_offset), Math.abs(config.y_offset), 9);
  const pad = pitch * 0.5;
  const xs = wellEntries.map((w) => w.x);
  const ys = wellEntries.map((w) => w.y);
  const topLeft = machineToSvg(
    Math.min(...xs) - pad, Math.max(...ys) + pad,
    svgWidth, svgHeight, machineXRange, machineYRange
  );
  const bottomRight = machineToSvg(
    Math.max(...xs) + pad, Math.min(...ys) - pad,
    svgWidth, svgHeight, machineXRange, machineYRange
  );

  const rectX = Math.min(topLeft.sx, bottomRight.sx);
  const rectY = Math.min(topLeft.sy, bottomRight.sy);
  const rectW = Math.abs(bottomRight.sx - topLeft.sx);
  const rectH = Math.abs(bottomRight.sy - topLeft.sy);
  const labelY = rectY > 16 ? rectY - 4 : rectY + 13;

  return (
    <g>
      <rect
        x={rectX}
        y={rectY}
        width={rectW}
        height={rectH}
        fill={themeViz.plateFill}
        stroke={themeViz.plateStroke}
        strokeWidth={1.25}
        rx={3}
      />
      <text x={rectX + 4} y={labelY} fill={themeViz.label} fontSize={10} fontWeight={500} stroke={themeViz.halo} strokeWidth={3} paintOrder="stroke" strokeLinejoin="round">
        {config.name || "Well Plate"}
      </text>
      {Object.entries(wells).map(([id, pos]) => {
        const { sx, sy } = machineToSvg(
          pos.x,
          pos.y,
          svgWidth,
          svgHeight,
          machineXRange,
          machineYRange
        );
        return (
          <circle key={id} cx={sx} cy={sy} r={wellRadius} fill={themeViz.wellFill} stroke={themeViz.wellStroke} strokeWidth={1} strokeOpacity={0.8} opacity={0.9}>
            <title>
              {id}: ({pos.x}, {pos.y}, {pos.z})
            </title>
          </circle>
        );
      })}
    </g>
  );
}
