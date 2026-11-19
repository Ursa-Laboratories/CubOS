import type { OriginPolicy } from '../../../../../src/types';
import { describe, expect, it } from 'vitest';
import { assemblyDelta, deckRegistration } from '../../../../../src/components/deck/three/polarRegistration';

describe('Polar Bear display coordinates', () => {
  it.each([
    { xmin: 0, ymin: 0, zmin: 9.479, policy: 'deck_origin' as OriginPolicy },
    { xmin: -390, ymin: -390, zmin: -70, policy: 'home_origin' as OriginPolicy },
  ])('registers XY and the Z midpoint at origin $xmin, $ymin, $zmin', ({ xmin, ymin, zmin, policy }) => {
    const origin = deckRegistration([xmin, xmin + 390], [ymin, ymin + 390], [zmin, zmin + 70], policy);
    const head = { x: xmin + 90, y: ymin + 12, z: zmin + 35 };
    const offset = { x: 15, y: -5 };
    const delta = assemblyDelta(head, offset, origin, [zmin, zmin + 70]);
    expect(0.226493 + delta.x / 1000).toBeCloseTo(origin.x + (head.x + offset.x) / 1000, 8);
    expect(-0.330118 - delta.y / 1000).toBeCloseTo(origin.z - (head.y + offset.y) / 1000, 8);
    expect(delta.z).toBe(0);
    expect(origin.y + (policy === 'home_origin' ? zmin : 0) / 1000).toBeCloseTo(-0.00365244, 8);
  });
});
