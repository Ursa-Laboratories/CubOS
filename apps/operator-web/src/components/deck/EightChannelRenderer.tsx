import type { GantryPosition, InstrumentConfig } from "../../types";
import { machineToSvg } from "../../utils/coordinates";
import { channelGeometryBounds } from "../../utils/pipetteGeometry";
import { viz } from "../../theme";

interface Props {
  label: string;
  instrument: InstrumentConfig;
  gantryPosition: GantryPosition | null;
  svgWidth: number;
  svgHeight: number;
  machineXRange: [number, number];
  machineYRange: [number, number];
  color: string;
}

export default function EightChannelRenderer(props: Props) {
  const { label, instrument, gantryPosition, color } = props;
  const bounds = channelGeometryBounds(instrument);
  if (!bounds) return null;
  const { geometry, spacing } = bounds;
  const connected = gantryPosition?.connected && gantryPosition.work_x != null && gantryPosition.work_y != null;
  const x = (connected ? gantryPosition.work_x! : 0) + (instrument.offset_x ?? 0);
  const y = (connected ? gantryPosition.work_y! : 0) + (instrument.offset_y ?? 0);
  const svg = (x: number, y: number) => machineToSvg(x, y, props.svgWidth, props.svgHeight, props.machineXRange, props.machineYRange);
  const origin = svg(0, 0);
  const reference = svg(x, y);
  const topLeft = svg(x + bounds.minX, y + bounds.maxY);
  const bottomRight = svg(x + bounds.maxX, y + bounds.minY);
  const referenceName = geometry.axis === "x" ? "leftmost" : "frontmost";
  return <g aria-label={`${label} 8-channel head`}>
    <title>{`${label}: ${geometry.length_mm} × ${geometry.width_mm} × ${geometry.height_mm} mm; ${referenceName} reference tip at (${x.toFixed(1)}, ${y.toFixed(1)})`}</title>
    {!connected && <line x1={origin.sx} y1={origin.sy} x2={reference.sx} y2={reference.sy} stroke={color} strokeDasharray="4 2" opacity={0.5} />}
    <rect data-testid="pipette-head" x={topLeft.sx} y={topLeft.sy} width={bottomRight.sx - topLeft.sx} height={bottomRight.sy - topLeft.sy}
      fill={color} fillOpacity={connected ? 0.16 : 0.05} stroke={color} strokeDasharray={connected ? undefined : "4 2"} />
    {Array.from({ length: 8 }, (_, index) => {
      const tip = svg(x + (geometry.axis === "x" ? index * spacing : 0), y + (geometry.axis === "y" ? index * spacing : 0));
      return <circle key={index} data-testid="pipette-channel" cx={tip.sx} cy={tip.sy} r={index === 0 ? 3.5 : 2}
        fill={index === 0 ? color : viz.canvas} stroke={color} strokeWidth={1.5}>
        <title>{index === 0 ? `${referenceName} reference tip (WPos + offset)` : `Channel ${index + 1}`}</title>
      </circle>;
    })}
    <text x={topLeft.sx} y={Math.max(12, topLeft.sy - 8)} fill={color} fontSize={9} fontWeight={600}
      stroke={viz.halo} strokeWidth={3} paintOrder="stroke">
      {label} · 8 ch · {geometry.length_mm} × {geometry.width_mm} mm
    </text>
  </g>;
}
