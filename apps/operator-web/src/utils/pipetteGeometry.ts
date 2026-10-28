import type { InstrumentConfig } from "../types";

export function channelGeometryBounds(instrument: InstrumentConfig) {
  const geometry = instrument.type === "pipette" ? instrument.channel_geometry : undefined;
  if (!geometry) return null;
  const spacing = geometry.spacing_mm ?? 9;
  const span = 7 * spacing;
  if (![spacing, geometry.length_mm, geometry.width_mm, geometry.height_mm].every(v => Number.isFinite(v) && v > 0)
    || geometry.length_mm <= span || !["x", "y"].includes(geometry.axis)) return null;
  const overhang = (geometry.length_mm - span) / 2;
  return {
    minX: geometry.axis === "x" ? -overhang : -geometry.width_mm / 2,
    maxX: geometry.axis === "x" ? span + overhang : geometry.width_mm / 2,
    minY: geometry.axis === "y" ? -overhang : -geometry.width_mm / 2,
    maxY: geometry.axis === "y" ? span + overhang : geometry.width_mm / 2,
    spacing,
    geometry,
  };
}

export function channelCalibrationHint(instrument: InstrumentConfig | undefined): string | null {
  if (instrument?.type !== "pipette" || !instrument.channel_geometry) return null;
  const axis = instrument.channel_geometry.axis;
  return `Use the ${axis === "x" ? "leftmost" : "frontmost"} tip (or bare nozzle) for every capture. The other seven tips extend along +${axis.toUpperCase()}. WPos plus this instrument's offset locates that reference tip, not the head center. Keep all eight channels and the full head clear of the block and rails.`;
}
