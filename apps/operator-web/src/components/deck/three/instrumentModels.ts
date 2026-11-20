import {
  Box3, BoxGeometry, Mesh, MeshStandardMaterial, Raycaster, Vector3, type Object3D,
} from 'three';
import type { InstrumentConfig } from '../../../types';
import { CAD_NOZZLE } from './polarRegistration';

// Front face and edges of PANDA_backboard in the rest carriage frame.
const BACKBOARD = { minX: 0.0964, maxX: 0.3414, minY: 0.171, maxY: 0.356, z: -0.379 };

export function placeInstrumentModel(object: Object3D, config: InstrumentConfig) {
  object.position.set(
    CAD_NOZZLE.x + config.offset_x / 1000,
    CAD_NOZZLE.y - (config.depth ?? 0) / 1000,
    CAD_NOZZLE.z - config.offset_y / 1000,
  );
}

export function createInstrumentBracket(model: Object3D) {
  const bounds = new Box3().setFromObject(model);
  if (bounds.isEmpty()) return null;
  const center = bounds.getCenter(new Vector3());
  const ray = new Raycaster(new Vector3(), new Vector3(0, 0, 1));
  const rear = bounds.min.z - 0.002;
  const height = bounds.max.y - bounds.min.y;
  const shoulder = Math.min(0.008, (bounds.max.x - bounds.min.x) / 4);
  function surface(x: number, y: number) {
    ray.ray.origin.set(x, y, rear);
    return ray.intersectObject(model, true)[0]?.point;
  }
  let contact: Vector3 | undefined;
  let fallback: Vector3 | undefined;
  for (const level of [0.5, 0.4, 0.3, 0.22, 0.62, 0.72, 0.12, 0.84]) {
    const y = bounds.min.y + height * level;
    for (const x of [model.position.x, center.x]) {
      const point = surface(x, y);
      if (!point) continue;
      fallback ??= point;
      // A body-width contact takes precedence over a cable or slender probe.
      if (surface(x - shoulder, y) && surface(x + shoulder, y)) {
        contact = point;
        break;
      }
    }
    if (contact) break;
  }
  const end = contact ?? fallback;
  if (!end) return null;
  const anchor = new Vector3(
    Math.max(BACKBOARD.minX + 0.009, Math.min(BACKBOARD.maxX - 0.009, end.x)),
    Math.max(BACKBOARD.minY + 0.009, Math.min(BACKBOARD.maxY - 0.009, end.y)),
    BACKBOARD.z - 0.001,
  );
  if (anchor.distanceTo(end) <= 0.003) return null;
  end.z += 0.001;
  const span = end.clone().sub(anchor);
  const bracket = new Mesh(new BoxGeometry(0.018, span.length(), 0.01),
    new MeshStandardMaterial({ color: 0x454d58, metalness: 0.3, roughness: 0.55 }));
  bracket.position.copy(anchor).lerp(end, 0.5);
  bracket.quaternion.setFromUnitVectors(new Vector3(0, 1, 0), span.normalize());
  bracket.castShadow = bracket.receiveShadow = true;
  return bracket;
}

export function disposeInstrumentModel(object: Object3D) {
  object.removeFromParent();
  const geometries = new Set<Mesh['geometry']>();
  const materials = new Set<Exclude<Mesh['material'], unknown[]>>();
  object.traverse(child => {
    if (child instanceof Mesh) {
      geometries.add(child.geometry);
      for (const material of [child.material].flat()) materials.add(material);
    }
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
}
