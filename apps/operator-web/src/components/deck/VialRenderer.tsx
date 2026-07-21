import type { VialConfig } from "../../types";
import { viz as themeViz } from "../../theme";
import { machineToSvg, mmToSvgPixels } from "../../utils/coordinates";

interface Props {
  label: string;
  config: VialConfig;
  svgWidth: number;
  svgHeight: number;
  machineXRange: [number, number];
  machineYRange: [number, number];
}

export default function VialRenderer({
  label,
  config,
  svgWidth,
  svgHeight,
  machineXRange,
  machineYRange,
}: Props) {
  const { sx, sy } = machineToSvg(
    config.location.x,
    config.location.y,
    svgWidth,
    svgHeight,
    machineXRange,
    machineYRange
  );
  const r = Math.max(2, mmToSvgPixels(config.diameter * 0.5, svgWidth, svgHeight, machineXRange, machineYRange));

  return (
    <g>
      <circle cx={sx} cy={sy} r={r} fill={themeViz.vialFill} stroke={themeViz.vialStroke} strokeWidth={1.5}>
        <title>
          {label}: ({config.location.x}, {config.location.y}, {config.location.z})
        </title>
      </circle>
      <text x={sx} y={sy - r - 3} fill={themeViz.vialLabel} fontSize={9} textAnchor="middle" fontWeight={500} stroke={themeViz.halo} strokeWidth={3} paintOrder="stroke" strokeLinejoin="round">
        {config.name}
      </text>
    </g>
  );
}
