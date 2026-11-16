import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { toCreasedNormals } from "three/addons/utils/BufferGeometryUtils.js";
import type { SceneObject } from "./sceneModel";

export interface CadAssetDefinition {
  id: string;
  kind: string;
  modelName: string;
  file: string;
  expectedSize: THREE.Vector3Tuple;
  sizeTolerance: number;
  orientation: "identity" | "cubware-tip-holder";
  requiresEmptyHolder?: boolean;
}

export const CAD_ASSETS: readonly CadAssetDefinition[] = [
  {
    id: "tall_wellplate_holder",
    kind: "well_plate_holder",
    modelName: "tall_wellplate_holder",
    file: "tall-wellplate-holder.glb",
    expectedSize: [127.5, 176.4, 25],
    sizeTolerance: 0.1,
    orientation: "identity",
    requiresEmptyHolder: true,
  },
  {
    id: "cubware_tip_holder_visual",
    kind: "tip_rack",
    modelName: "cubware_tip_holder_visual",
    file: "cubware-tip-holder-visual.glb",
    expectedSize: [138, 21, 66],
    sizeTolerance: 0.1,
    orientation: "cubware-tip-holder",
  },
];

interface GeometryTemplate { geometries: { name: string; geometry: THREE.BufferGeometry }[] }
const templates = new Map<string, Promise<GeometryTemplate | null>>();

function sizeMatches(actual: readonly number[], expected: readonly number[], tolerance: number) {
  return actual.length === 3 && expected.length === 3 && actual.every((value, i) =>
    Number.isFinite(value) && Math.abs(value - expected[i]) <= tolerance,
  );
}

/** Exact model-name and native body-size gate. A null result means use fallback geometry. */
export function resolveCadAsset(object: SceneObject): CadAssetDefinition | null {
  if (!object.modelName) return null;
  const definition = CAD_ASSETS.find(asset => asset.kind === object.kind && asset.modelName === object.modelName);
  if (!definition) return null;
  if (definition.requiresEmptyHolder && object.hasChildren) return null;
  const size = object.body.size;
  return sizeMatches([size.x, size.y, size.z], definition.expectedSize, definition.sizeTolerance)
    ? definition
    : null;
}

function sourceOrientation(definition: CadAssetDefinition): THREE.Matrix4 {
  if (definition.orientation === "identity") return new THREE.Matrix4();
  // Match the visual-study alignment: source Z→deck X, source X→deck Y,
  // source Y→deck Z. This is a rigid axis permutation; it preserves scale.
  return new THREE.Matrix4().makeBasis(
    new THREE.Vector3(0, 1, 0),
    new THREE.Vector3(0, 0, 1),
    new THREE.Vector3(1, 0, 0),
  );
}

function disposeSceneResources(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse(object => {
    if (!(object instanceof THREE.Mesh)) return;
    geometries.add(object.geometry);
    for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
      materials.add(material);
      for (const value of Object.values(material)) {
        if (value instanceof THREE.Texture) value.dispose();
      }
    }
  });
  geometries.forEach(geometry => geometry.dispose());
  materials.forEach(material => material.dispose());
}

function parseTemplate(definition: CadAssetDefinition): Promise<GeometryTemplate | null> {
  const url = `${import.meta.env.BASE_URL}models/labware/${definition.file}`;
  return new GLTFLoader().loadAsync(url).then(gltf => {
    const source = gltf.scene;
    source.applyMatrix4(sourceOrientation(definition));
    source.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(source);
    const nativeSize = bounds.getSize(new THREE.Vector3());
    if (!sizeMatches([nativeSize.x, nativeSize.y, nativeSize.z], definition.expectedSize, definition.sizeTolerance)) {
      disposeSceneResources(source);
      return null;
    }
    const center = bounds.getCenter(new THREE.Vector3());
    const centerTransform = new THREE.Matrix4().makeTranslation(-center.x, -center.y, -center.z);
    const geometries: GeometryTemplate["geometries"] = [];
    source.traverse(object => {
      if (!(object instanceof THREE.Mesh)) return;
      const transformed = object.geometry.clone();
      transformed.applyMatrix4(centerTransform.clone().multiply(object.matrixWorld));
      const geometry = toCreasedNormals(transformed, Math.PI / 5);
      transformed.dispose();
      geometries.push({ name: object.name, geometry });
    });
    disposeSceneResources(source);
    return geometries.length ? { geometries } : null;
  }).catch(() => null);
}

/**
 * Load a fresh, independently disposable, centered CAD group. Meshes contain
 * cloned native-unit geometry and empty material arrays; the caller assigns
 * display materials and places/rotates the group from SceneObject.body.
 * Unknown, mismatched, and failed assets resolve to null for procedural fallback.
 */
export async function loadCadAsset(object: SceneObject): Promise<THREE.Group | null> {
  try {
    const definition = resolveCadAsset(object);
    if (!definition) return null;
    let pending = templates.get(definition.id);
    if (!pending) {
      pending = parseTemplate(definition);
      templates.set(definition.id, pending);
    }
    const template = await pending;
    if (!template) return null;
    const group = new THREE.Group();
    group.name = definition.id;
    group.userData.cadAssetId = definition.id;
    template.geometries.forEach(({ name, geometry }) => {
      const mesh = new THREE.Mesh(geometry.clone(), []);
      mesh.name = name;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
    });
    return group;
  } catch {
    return null;
  }
}

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    templates.forEach(promise => void promise.then(template => template?.geometries.forEach(part => part.geometry.dispose())));
    templates.clear();
  });
}
