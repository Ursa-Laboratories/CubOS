import type { OriginPolicy } from '../../../../../src/types';
import { describe, expect, it } from 'vitest';
import { CAD_NOZZLE, cadRestPosition, deckRegistration, instrumentEndpoint } from '../../../../../src/components/deck/three/polarRegistration';

describe('Polar Bear display coordinates', () => {
  it.each([
    { xmin: 0, ymin: 0, zmin: 9.479, policy: 'deck_origin' as OriginPolicy },
    { xmin: -390, ymin: -390, zmin: -70, policy: 'home_origin' as OriginPolicy },
  ])('registers multiple endpoints and rest at origin $xmin, $ymin, $zmin', ({ xmin, ymin, zmin, policy }) => {
    const origin = deckRegistration([xmin, xmin + 390], [ymin, ymin + 390], [zmin, zmin + 70], policy);
    const rest = cadRestPosition(origin, [zmin, zmin + 70]);
    expect(origin.x + rest.x / 1000).toBeCloseTo(CAD_NOZZLE.x, 8);
    expect(origin.z - rest.y / 1000).toBeCloseTo(CAD_NOZZLE.z, 8);
    expect(rest.z).toBe(zmin + 35);
    expect(origin.y + (policy === 'home_origin' ? zmin : 0) / 1000).toBeCloseTo(-0.00365244, 8);

    const head = { x: xmin + 90, y: ymin + 12, z: zmin + 35 };
    const first = instrumentEndpoint(head, { offset_x: 15, offset_y: -5, depth: 19 }, origin);
    const second = instrumentEndpoint(head, { offset_x: -12, offset_y: 17 }, origin);
    expect(first.x).toBeCloseTo(origin.x + (xmin + 105) / 1000, 8);
    expect(first.y).toBeCloseTo(origin.y + (zmin + 16) / 1000, 8);
    expect(first.z).toBeCloseTo(origin.z - (ymin + 7) / 1000, 8);
    expect(second.x - first.x).toBeCloseTo(-0.027, 8);
    expect(second.y - first.y).toBeCloseTo(0.019, 8);
    expect(second.z - first.z).toBeCloseTo(-0.022, 8);
  });
});
