import type { ScenePoint } from "./sceneModel";

export interface PointGeometryRadii {
  /** Resolved nearest-neighbor spacing in millimeters. */
  pitch: number;
  /** Outer radius of the display-only well/tip socket ring. */
  outerRadius: number;
  /** Radius of the filled well/tip socket. */
  fillRadius: number;
  /** Tube radius of the socket ring. */
  tubeRadius: number;
  /** Radius at the top of a schematic rack tip. */
  tipRadius: number;
  /** Radius at the bottom of a schematic rack tip. */
  tipBaseRadius: number;
}

const DEFAULT_PITCH_MM = 9;
const finite = (value: number) => Number.isFinite(value);
function distance(a: ScenePoint, b: ScenePoint): number {
  return Math.hypot(a.position.x - b.position.x, a.position.y - b.position.y);
}

/**
 * Pick display-only marker radii from API-resolved spacing. Named A1/A2 and
 * A1/B1 neighbors work for rotated grids and one-row/one-column layouts; the
 * nearest distinct pair is a conservative fallback for partial/missing IDs.
 */
export function getPointGeometryRadii(points: readonly ScenePoint[]): PointGeometryRadii {
  const byLabel = new Map(points.filter(p => finite(p.position.x) && finite(p.position.y)).map(p => [p.label, p]));
  const a1 = byLabel.get("A1");
  const namedDistances = a1
    ? [byLabel.get("A2"), byLabel.get("B1")].filter((p): p is ScenePoint => !!p).map(p => distance(a1, p))
    : [];
  const valid = points.filter(p => finite(p.position.x) && finite(p.position.y));
  let pitch = namedDistances.filter(d => finite(d) && d > 0).reduce((min, d) => Math.min(min, d), Infinity);
  if (!finite(pitch)) {
    pitch = Infinity;
    for (let i = 0; i < valid.length; i += 1) {
      for (let j = i + 1; j < valid.length; j += 1) {
        const d = distance(valid[i], valid[j]);
        if (finite(d) && d > 0) pitch = Math.min(pitch, d);
      }
    }
  }
  if (!finite(pitch)) pitch = DEFAULT_PITCH_MM;

  const outerRadius = Math.min(16, pitch * 0.38);
  const tubeRadius = Math.min(0.5, Math.max(0.15, pitch * 0.04));
  const tipRadius = Math.min(2.5, pitch * 0.33);
  return {
    pitch,
    outerRadius,
    fillRadius: outerRadius * 0.7,
    tubeRadius: Math.min(tubeRadius, outerRadius * 0.22),
    tipRadius,
    tipBaseRadius: tipRadius * 0.28,
  };
}
