import type { Coordinate3D, OriginPolicy } from '../../../types';

// Survey of the CAD assembly in its native frame (metres, Y up, front +Z).
// The sheet is centred left/right. Its front edge is the visual Y datum.
const SHEET_CENTER_X = 0.21925;
const SHEET_FRONT_Z = -0.0007;
const SHEET_TOP_Y = -0.00365244;
const NOZZLE_X = 0.226493;
const NOZZLE_Z = -0.330118;

export type Range = [number, number];

export function deckRegistration(x: Range, y: Range, z: Range, policy: OriginPolicy) {
  return {
    x: SHEET_CENTER_X - (x[0] + x[1]) / 2000,
    // In deck-origin configurations a positive lower travel limit is above the surface.
    y: SHEET_TOP_Y - (policy === 'home_origin' ? z[0] : 0) / 1000,
    z: SHEET_FRONT_Z + y[0] / 1000,
  };
}

export function assemblyDelta(head: Coordinate3D, toolOffset: { x: number; y: number }, origin: Coordinate3D, z: Range) {
  // Align the CAD nozzle axis with configured XY. The Z slide is visually
  // centred in its travel at the midpoint of the configured work range.
  return {
    x: head.x + toolOffset.x + (origin.x - NOZZLE_X) * 1000,
    y: head.y + toolOffset.y - (origin.z - NOZZLE_Z) * 1000,
    z: head.z - (z[0] + z[1]) / 2,
  };
}
