import type { Coordinate3D, InstrumentConfig, OriginPolicy } from '../../../types';

// Survey of the CAD assembly in its native frame (metres, Y up, front +Z).
const SHEET_CENTER_X = 0.21925;
const SHEET_FRONT_Z = -0.0007;
const SHEET_TOP_Y = -0.00365244;
export const CAD_NOZZLE = { x: 0.226493, y: 0.116740, z: -0.330118 };

export type Range = [number, number];

export function deckRegistration(x: Range, y: Range, z: Range, policy: OriginPolicy) {
  return {
    x: SHEET_CENTER_X - (x[0] + x[1]) / 2000,
    // In deck-origin configurations a positive lower travel limit is above the surface.
    y: SHEET_TOP_Y - (policy === 'home_origin' ? z[0] : 0) / 1000,
    z: SHEET_FRONT_Z + y[0] / 1000,
  };
}

export function cadRestPosition(origin: Coordinate3D, z: Range): Coordinate3D {
  return {
    x: (CAD_NOZZLE.x - origin.x) * 1000,
    y: (origin.z - CAD_NOZZLE.z) * 1000,
    z: (z[0] + z[1]) / 2,
  };
}

export function instrumentEndpoint(
  head: Coordinate3D,
  instrument: Pick<InstrumentConfig, 'offset_x' | 'offset_y' | 'depth'>,
  origin: Coordinate3D,
): Coordinate3D {
  return {
    x: origin.x + (head.x + instrument.offset_x) / 1000,
    y: origin.y + (head.z - (instrument.depth ?? 0)) / 1000,
    z: origin.z - (head.y + instrument.offset_y) / 1000,
  };
}
