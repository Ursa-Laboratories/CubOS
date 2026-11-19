import { Group, InstancedMesh, Mesh, LineSegments, type BufferGeometry, type Material } from "three";
import type { DeckResponse } from "../../../types";
import { createLabwareMesh } from "./labwareMeshes";
import { buildOverlayModel } from "./overlayModel";

/** The group is in millimetres, with deck (x, y, z) mapped to Three (x, z, -y). */
export function createDeckOverlay(deck: DeckResponse): Group {
  const overlay = new Group();
  overlay.name = "ConfiguredDeck";
  const deckFrame = new Group();
  deckFrame.rotation.x = -Math.PI / 2;
  overlay.add(deckFrame);
  for (const item of buildOverlayModel(deck)) deckFrame.add(createLabwareMesh(item));
  return overlay;
}

export function disposeDeckOverlay(overlay: Group): void {
  const geometries = new Set<BufferGeometry>();
  const materials = new Set<Material>();
  overlay.traverse(object => {
    if (object instanceof InstancedMesh) object.dispose();
    if (!(object instanceof Mesh || object instanceof LineSegments)) return;
    geometries.add(object.geometry);
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      materials.add(material);
    }
  });
  geometries.forEach(geometry => geometry.dispose());
  materials.forEach(material => material.dispose());
  overlay.clear();
  overlay.removeFromParent();
}
