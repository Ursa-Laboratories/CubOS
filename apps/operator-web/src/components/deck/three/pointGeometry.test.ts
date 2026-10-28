import { describe, expect, it } from "vitest";
import type { ScenePoint } from "./sceneModel";
import { getPointGeometryRadii } from "./pointGeometry";

function points(rows: number, columns: number, pitchX: number, pitchY: number, angle = 0): ScenePoint[] {
  const cos = Math.cos(angle), sin = Math.sin(angle);
  return Array.from({ length: rows }, (_, r) => Array.from({ length: columns }, (_, c) => {
    const x = c * pitchX, y = r * pitchY;
    return {
      id: `${String.fromCharCode(65 + r)}${c + 1}`,
      label: `${String.fromCharCode(65 + r)}${c + 1}`,
      position: { x: x * cos - y * sin, y: x * sin + y * cos, z: 0 },
    };
  })).flat();
}

describe("getPointGeometryRadii", () => {
  it.each([
    [4.5, 1.71], // 384 well pitch
    [9, 3.42], // 96 well pitch
    [18, 6.84], // 24 well pitch
    [39, 14.82], // 6 well pitch
  ])("scales safely at pitch %s mm", (pitch, expectedOuterRadius) => {
    const radii = getPointGeometryRadii(points(2, 2, pitch, pitch));
    expect(radii.pitch).toBeCloseTo(pitch);
    expect(radii.outerRadius).toBeCloseTo(expectedOuterRadius);
    expect(radii.outerRadius * 2).toBeLessThan(pitch);
  });

  it("uses Euclidean neighbor spacing for rotated coordinates", () => {
    const radii = getPointGeometryRadii(points(2, 2, 4.5, 4.5, Math.PI / 3));
    expect(radii.pitch).toBeCloseTo(4.5);
  });

  it("resolves one-row and one-column pitches from the available named neighbor", () => {
    expect(getPointGeometryRadii(points(1, 4, 9, 9)).pitch).toBeCloseTo(9);
    expect(getPointGeometryRadii(points(4, 1, 9, 9)).pitch).toBeCloseTo(9);
  });

  it("falls back to the nearest valid pair when A1/A2/B1 are missing", () => {
    const sparse: ScenePoint[] = [
      { id: "p1", label: "P1", position: { x: 100, y: 100, z: 0 } },
      { id: "p2", label: "P2", position: { x: 104.5, y: 100, z: 0 } },
      { id: "p3", label: "P3", position: { x: 109, y: 100, z: 0 } },
    ];
    expect(getPointGeometryRadii(sparse).pitch).toBeCloseTo(4.5);
  });

  it("uses a conservative pitch for a single valid point", () => {
    const radii = getPointGeometryRadii([{ id: "only", label: "A1", position: { x: 10, y: 20, z: 0 } }]);
    expect(radii.pitch).toBe(9);
    expect(radii.outerRadius * 2).toBeLessThan(radii.pitch);
  });
});
