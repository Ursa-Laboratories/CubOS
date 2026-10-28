import * as THREE from "three";
import { describe, expect, it } from "vitest";
import type { SceneObject, ScenePoint } from "./sceneModel";
import { createLabwareMesh, styleCadMesh } from "./labwareMeshes";

function meshObject(overrides: Partial<SceneObject> = {}): SceneObject {
  return {
    id: "mesh-test",
    kind: "well_plate",
    label: "Test plate",
    points: [],
    info: "test",
    body: { shape: "box", center: { x: 0, y: 0, z: 5 }, size: { x: 100, y: 70, z: 10 }, rotationZ: 0, schematic: true },
    ...overrides,
  };
}

function gridPoints(rows: number, columns: number, pitch: number): ScenePoint[] {
  return Array.from({ length: rows }, (_, row) => Array.from({ length: columns }, (_, column) => ({
    id: `plate.${String.fromCharCode(65 + row)}${column + 1}`,
    label: `${String.fromCharCode(65 + row)}${column + 1}`,
    position: { x: (column - (columns - 1) / 2) * pitch, y: (row - (rows - 1) / 2) * pitch, z: 10 },
  }))).flat();
}

function topGeometry(group: THREE.Group) {
  const results: THREE.ExtrudeGeometry[] = [];
  group.traverse(object => { if (object instanceof THREE.Mesh && object.geometry instanceof THREE.ExtrudeGeometry) results.push(object.geometry); });
  if (!results.length) throw new Error("Expected an extruded tray top.");
  return results[0];
}

describe("labware mesh geometry", () => {
  it("builds a 384-well plate with 384 through-hole contours without changing resolved centers", () => {
    const points = gridPoints(16, 24, 4.5);
    const before = points.map(point => ({ ...point, position: { ...point.position } }));
    const group = createLabwareMesh(meshObject({ points, body: { shape: "box", center: { x: 0, y: 0, z: 5 }, size: { x: 127.76, y: 85.47, z: 10 }, rotationZ: 0, schematic: true } }));
    const top = topGeometry(group);
    const shape = top.parameters.shapes as THREE.Shape;
    expect(shape.holes).toHaveLength(384);
    expect(points).toEqual(before);
  });

  it("places rotated plate hole centers under the corresponding API points in world space", () => {
    const center = new THREE.Vector3(20, -30, 5);
    const rotation = Math.PI / 2;
    const apiPoints = [[-4.5, -4.5], [4.5, -4.5], [-4.5, 4.5]].map(([x, y], index) => {
      const world = new THREE.Vector3(x, y, 5).applyAxisAngle(new THREE.Vector3(0, 0, 1), rotation).add(center);
      return { id: `p${index}`, label: ["A1", "A2", "B1"][index], position: world };
    });
    const group = createLabwareMesh(meshObject({
      points: apiPoints,
      body: { shape: "box", center: { x: center.x, y: center.y, z: center.z }, size: { x: 30, y: 30, z: 10 }, rotationZ: rotation, schematic: true },
    }));
    group.updateMatrixWorld(true);
    const top = topGeometry(group);
    const shape = top.parameters.shapes as THREE.Shape;
    const mesh = group.children.find(child => child instanceof THREE.Mesh && child.geometry === top) as THREE.Mesh;
    mesh.updateWorldMatrix(true, false);
    const centers = shape.holes.map(path => {
      const arc = path.curves[0] as THREE.EllipseCurve;
      return mesh.localToWorld(new THREE.Vector3(arc.aX, arc.aY, 1.3));
    });
    expect(centers).toHaveLength(apiPoints.length);
    for (let i = 0; i < centers.length; i += 1) {
      expect(centers[i].distanceTo(apiPoints[i].position)).toBeLessThan(1e-6);
    }
  });

  it("keeps fallback enclosure bounds aligned with its declared body size", () => {
    const group = createLabwareMesh(meshObject({
      kind: "custom_holder",
      body: { shape: "box", center: { x: -20, y: 14, z: 30 }, size: { x: 48, y: 32, z: 24 }, rotationZ: 0, schematic: true },
    }));
    group.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(group);
    const size = bounds.getSize(new THREE.Vector3());
    expect([size.x, size.y, size.z]).toEqual([48, 32, 24]);
  });

  it("creates a hollow vial wall with finite geometry", () => {
    const group = createLabwareMesh(meshObject({
      kind: "vial",
      body: { shape: "cylinder", center: { x: 0, y: 0, z: 20 }, size: { x: 12, y: 12, z: 40 }, rotationZ: 0, schematic: true },
    }));
    const vial = group.children.find(child => child instanceof THREE.Mesh && child.geometry instanceof THREE.LatheGeometry) as THREE.Mesh;
    expect(vial).toBeDefined();
    const positions = vial.geometry.getAttribute("position").array;
    expect(Array.from(positions).every(Number.isFinite)).toBe(true);
    const profile = (vial.geometry as THREE.LatheGeometry).parameters.points;
    expect(Math.min(...profile.map(point => point.x))).toBe(0);
    expect(Math.max(...profile.map(point => point.x))).toBe(6);
    expect(profile.some(point => point.x > 0 && point.x < 6)).toBe(true);
  });

  it("applies CAD materials and edge lines without changing source vertices or transforms", () => {
    const group = new THREE.Group();
    group.position.set(10, -8, 3);
    group.rotation.set(0.1, -0.2, 0.3);
    group.scale.set(1.2, 0.9, 1.1);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(6, 8, 10), new THREE.MeshBasicMaterial());
    mesh.position.set(3, 4, 5);
    mesh.rotation.z = -0.4;
    group.add(mesh);
    const vertexSnapshot = Array.from(mesh.geometry.getAttribute("position").array);
    group.updateMatrix();
    mesh.updateMatrix();
    const groupTransform = group.matrix.clone();
    const meshPosition = mesh.position.clone(), meshRotation = mesh.rotation.clone(), meshScale = mesh.scale.clone();

    styleCadMesh(group, "well_plate_holder");

    expect(Array.from(mesh.geometry.getAttribute("position").array)).toEqual(vertexSnapshot);
    expect(group.matrix.equals(groupTransform)).toBe(true);
    expect(mesh.position.toArray()).toEqual(meshPosition.toArray());
    expect(mesh.rotation.toArray()).toEqual(meshRotation.toArray());
    expect(mesh.scale.toArray()).toEqual(meshScale.toArray());
  });
});
