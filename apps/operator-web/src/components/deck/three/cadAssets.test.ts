import * as THREE from "three";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SceneObject } from "./sceneModel";
import { loadCadAsset, resolveCadAsset } from "./cadAssets";

const loaderMock = vi.hoisted(() => ({ loadAsync: vi.fn() }));
vi.mock("three/addons/loaders/GLTFLoader.js", () => ({
  GLTFLoader: class {
    loadAsync(url: string) { return loaderMock.loadAsync(url); }
  },
}));

function object(kind: string, modelName: string, x: number, y: number, z: number, hasChildren?: boolean): SceneObject {
  return {
    id: "test",
    kind,
    modelName,
    hasChildren,
    label: "Test object",
    points: [],
    info: "test",
    body: { shape: "box", center: { x: 0, y: 0, z: 0 }, size: { x, y, z }, rotationZ: 0, schematic: true },
  };
}

beforeEach(() => loaderMock.loadAsync.mockReset());

describe("resolveCadAsset", () => {
  it("matches the tall well plate holder only at its native body dimensions", () => {
    expect(resolveCadAsset(object("well_plate_holder", "tall_wellplate_holder", 127.5, 176.4, 25))?.id).toBe("tall_wellplate_holder");
    expect(resolveCadAsset(object("well_plate_holder", "tall_wellplate_holder", 127.5, 176.4, 25, true))).toBeNull();
    expect(resolveCadAsset(object("well_plate_holder", "tall_wellplate_holder", 127.5, 176.4, 30))).toBeNull();
    expect(resolveCadAsset(object("well_plate_holder", "other_holder", 127.5, 176.4, 25))).toBeNull();
  });

  it("keeps the demo-only tip holder distinct from configured Panda racks", () => {
    expect(resolveCadAsset(object("tip_rack", "cubware_tip_holder_visual", 138, 21, 66))?.id).toBe("cubware_tip_holder_visual");
    expect(resolveCadAsset(object("tip_rack", "panda_2x15_tip_rack", 66, 138, 22))).toBeNull();
    expect(resolveCadAsset(object("well_plate_holder", "cubware_tip_holder_visual", 138, 21, 66))).toBeNull();
  });

  it("accepts only small measurement tolerance", () => {
    expect(resolveCadAsset(object("well_plate_holder", "tall_wellplate_holder", 127.55, 176.35, 25.05))?.id).toBe("tall_wellplate_holder");
    expect(resolveCadAsset(object("well_plate_holder", "tall_wellplate_holder", 128, 176.4, 25))).toBeNull();
  });

  it("generates unit creased normals, preserves native bounds, and returns independent geometry clones", async () => {
    const geometry = new THREE.BoxGeometry(127.5, 176.4, 25);
    geometry.deleteAttribute("normal");
    const sourceMaterial = new THREE.MeshBasicMaterial();
    const source = new THREE.Group();
    source.add(new THREE.Mesh(geometry, sourceMaterial));
    loaderMock.loadAsync.mockResolvedValue({ scene: source });

    const fixture = object("well_plate_holder", "tall_wellplate_holder", 127.5, 176.4, 25);
    const first = await loadCadAsset(fixture);
    const second = await loadCadAsset(fixture);
    expect(loaderMock.loadAsync).toHaveBeenCalledTimes(1);
    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    const firstMesh = first!.children[0] as THREE.Mesh;
    const secondMesh = second!.children[0] as THREE.Mesh;
    expect(firstMesh.geometry).not.toBe(secondMesh.geometry);
    const bounds = new THREE.Box3().setFromBufferAttribute(firstMesh.geometry.getAttribute("position") as THREE.BufferAttribute);
    const size = bounds.getSize(new THREE.Vector3());
    expect(size.x).toBeCloseTo(127.5, 4);
    expect(size.y).toBeCloseTo(176.4, 4);
    expect(size.z).toBeCloseTo(25, 4);
    expect(bounds.getCenter(new THREE.Vector3()).length()).toBeLessThan(1e-5);

    const normals = firstMesh.geometry.getAttribute("normal");
    expect(normals).toBeDefined();
    for (let i = 0; i < normals.count; i += 1) {
      expect(new THREE.Vector3().fromBufferAttribute(normals, i).length()).toBeCloseTo(1, 5);
    }

    const secondGeometryDisposed = vi.fn();
    secondMesh.geometry.addEventListener("dispose", secondGeometryDisposed);
    firstMesh.geometry.dispose();
    expect(secondGeometryDisposed).not.toHaveBeenCalled();
    secondMesh.geometry.dispose();
  });
});
