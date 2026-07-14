/**
 * User-space coord -> SVG coord transform.
 *
 * User-space coordinates are positive with a bottom-left machine origin.
 * SVG origin (0,0) is top-left, so Y must be inverted for display.
 */

export const SVG_PADDING = 20;

export interface SvgViewport {
  originX: number;
  originY: number;
  width: number;
  height: number;
  scale: number;
}

export function getSvgViewport(
  svgWidth: number,
  svgHeight: number,
  machineXRange: [number, number],
  machineYRange: [number, number],
): SvgViewport {
  const drawW = svgWidth - 2 * SVG_PADDING;
  const drawH = svgHeight - 2 * SVG_PADDING;
  const xSpan = Math.max(machineXRange[1] - machineXRange[0], Number.EPSILON);
  const ySpan = Math.max(machineYRange[1] - machineYRange[0], Number.EPSILON);
  const pxPerMmX = drawW / xSpan;
  const pxPerMmY = drawH / ySpan;
  const scale = Math.min(pxPerMmX, pxPerMmY);
  const width = xSpan * scale;
  const height = ySpan * scale;

  return {
    originX: SVG_PADDING + (drawW - width) * 0.5,
    originY: SVG_PADDING + (drawH - height) * 0.5,
    width,
    height,
    scale,
  };
}

export function mmToSvgPixels(
  mm: number,
  svgWidth: number,
  svgHeight: number,
  machineXRange: [number, number],
  machineYRange: [number, number],
): number {
  return mm * getSvgViewport(svgWidth, svgHeight, machineXRange, machineYRange).scale;
}

export function machineToSvg(
  mx: number,
  my: number,
  svgWidth: number,
  svgHeight: number,
  machineXRange: [number, number],
  machineYRange: [number, number]
): { sx: number; sy: number } {
  const viewport = getSvgViewport(svgWidth, svgHeight, machineXRange, machineYRange);

  // Linear map: machineXRange[0] (0) -> left edge of the letterboxed draw area.
  const sx = viewport.originX + (mx - machineXRange[0]) * viewport.scale;
  // Invert Y so machineYRange[0] is bottom and machineYRange[1] is top.
  const sy = viewport.originY + (machineYRange[1] - my) * viewport.scale;

  return { sx, sy };
}
