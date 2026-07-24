import type { Coordinate3D } from "../../types";
import { machineToSvg } from "../../utils/coordinates";

export interface PositionBounds {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export function getPositionBounds(positions: Coordinate3D[]): PositionBounds | null {
  if (positions.length === 0) {
    return null;
  }

  return {
    minX: Math.min(...positions.map((position) => position.x)),
    maxX: Math.max(...positions.map((position) => position.x)),
    minY: Math.min(...positions.map((position) => position.y)),
    maxY: Math.max(...positions.map((position) => position.y)),
  };
}

export function getBoundsCenter(bounds: PositionBounds): { x: number; y: number } {
  return {
    x: (bounds.minX + bounds.maxX) * 0.5,
    y: (bounds.minY + bounds.maxY) * 0.5,
  };
}

export function toSvgRect(
  minX: number,
  minY: number,
  maxX: number,
  maxY: number,
  svgWidth: number,
  svgHeight: number,
  machineXRange: [number, number],
  machineYRange: [number, number],
): { x: number; y: number; width: number; height: number } {
  const topLeft = machineToSvg(minX, minY, svgWidth, svgHeight, machineXRange, machineYRange);
  const bottomRight = machineToSvg(maxX, maxY, svgWidth, svgHeight, machineXRange, machineYRange);

  return {
    x: Math.min(topLeft.sx, bottomRight.sx),
    y: Math.min(topLeft.sy, bottomRight.sy),
    width: Math.abs(bottomRight.sx - topLeft.sx),
    height: Math.abs(bottomRight.sy - topLeft.sy),
  };
}
