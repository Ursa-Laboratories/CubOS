import * as THREE from "three";
import { getPointGeometryRadii } from "./pointGeometry";
import type { SceneObject } from "./overlayModel";

function polymer(color: number, roughness = 0.4) {
  return new THREE.MeshPhysicalMaterial({ color, roughness, metalness: 0, clearcoat: 0.22, clearcoatRoughness: 0.4 });
}

function roundedRect(width: number, depth: number, radius: number): THREE.Shape {
  const x = -width / 2, y = -depth / 2, r = Math.min(radius, width / 4, depth / 4);
  const shape = new THREE.Shape();
  shape.moveTo(x + r, y);
  shape.lineTo(x + width - r, y); shape.quadraticCurveTo(x + width, y, x + width, y + r);
  shape.lineTo(x + width, y + depth - r); shape.quadraticCurveTo(x + width, y + depth, x + width - r, y + depth);
  shape.lineTo(x + r, y + depth); shape.quadraticCurveTo(x, y + depth, x, y + depth - r);
  shape.lineTo(x, y + r); shape.quadraticCurveTo(x, y, x + r, y);
  return shape;
}

function edge(mesh: THREE.Mesh, opacity = 0.18) {
  const lines = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry, 35), new THREE.LineBasicMaterial({
    color: 0x223e5e, transparent: true, opacity, depthWrite: false,
  }));
  mesh.add(lines);
}

function block(group: THREE.Group, x: number, y: number, z: number, px: number, py: number, pz: number, mat: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(x, y, z), mat);
  mesh.position.set(px, py, pz); mesh.castShadow = true; mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function localPoint(object: SceneObject, point: THREE.Vector3) {
  const c = object.body.center;
  return point.sub(new THREE.Vector3(c.x, c.y, c.z)).applyAxisAngle(new THREE.Vector3(0, 0, 1), -object.body.rotationZ);
}

function addTray(group: THREE.Group, object: SceneObject, isRack: boolean) {
  const s = object.body.size;
  const { outerRadius, tipRadius, tipBaseRadius } = getPointGeometryRadii(object.points);
  const openingRadius = outerRadius * 0.85;
  const top = s.z / 2;
  const capDepth = Math.min(1.3, s.z / 4);
  const curveSegments = 12;
  // Shape samples each elliptical opening at twice the curve segment count.
  const radialSegments = curveSegments * 2;
  const topShape = roundedRect(s.x, s.y, 3);
  const localPoints = object.points.map(point => ({
    point, local: localPoint(object, new THREE.Vector3(point.position.x, point.position.y, point.position.z)),
  }));
  const valid = localPoints.filter(({ local }) => Math.abs(local.x) + openingRadius < s.x / 2 - 0.6 && Math.abs(local.y) + openingRadius < s.y / 2 - 0.6);
  for (const { local } of valid) {
    const hole = new THREE.Path();
    hole.absarc(local.x, local.y, openingRadius, 0, Math.PI * 2, true);
    topShape.holes.push(hole);
  }
  const shell = polymer(isRack ? 0xc2e3da : 0xeef2f4, isRack ? 0.36 : 0.28);
  const topMesh = new THREE.Mesh(new THREE.ExtrudeGeometry(topShape, {
    depth: capDepth, bevelEnabled: false, steps: 1, curveSegments,
  }), shell);
  topMesh.position.z = top - capDepth;
  topMesh.castShadow = true; topMesh.receiveShadow = true;
  group.add(topMesh);
  const frameMat = polymer(isRack ? 0x365c67 : 0xd0d9e2, 0.48);
  const baseDepth = Math.min(2.2, s.z / 4);
  const bottom = -s.z / 2 + baseDepth / 2;
  const wall = Math.min(1.8, s.x / 4, s.y / 4);
  const skirtHeight = s.z - baseDepth - capDepth;
  const skirtCenter = (baseDepth - capDepth) / 2;
  block(group, s.x, s.y, baseDepth, 0, 0, bottom, frameMat);
  for (const sign of [-1, 1]) {
    block(group, s.x, wall, skirtHeight, 0, sign * (s.y - wall) / 2, skirtCenter, shell);
    block(group, wall, s.y - 2 * wall, skirtHeight, sign * (s.x - wall) / 2, 0, skirtCenter, shell);
  }
  if (!valid.length) return;
  const wellDepth = Math.min(object.wellDepth ?? (isRack ? 12 : 25), s.z - baseDepth);
  const walls = new THREE.InstancedMesh(
    new THREE.CylinderGeometry(openingRadius, openingRadius * 0.78, wellDepth, radialSegments, 1, true),
    new THREE.MeshStandardMaterial({ color: isRack ? 0x6b9f91 : 0x8c9bad, roughness: 0.65, side: THREE.DoubleSide }),
    valid.length,
  );
  const bottoms = new THREE.InstancedMesh(new THREE.CircleGeometry(openingRadius * 0.78, radialSegments), polymer(isRack ? 0x416a64 : 0x556372, 0.8), valid.length);
  const matrix = new THREE.Matrix4(), rotation = new THREE.Matrix4().makeRotationX(Math.PI / 2);
  valid.forEach(({ local }, i) => {
    walls.setMatrixAt(i, matrix.makeTranslation(local.x, local.y, top - wellDepth / 2).multiply(rotation));
    bottoms.setMatrixAt(i, matrix.makeTranslation(local.x, local.y, top - wellDepth));
  });
  walls.name = "sockets";
  walls.receiveShadow = true;
  bottoms.receiveShadow = true;
  group.add(walls, bottoms);
  if (isRack) {
    const loaded = valid.filter(({ point }) => point.present !== false);
    if (!loaded.length) return;
    const tips = new THREE.InstancedMesh(new THREE.CylinderGeometry(tipRadius, tipBaseRadius, 13, 12, 1, true),
      new THREE.MeshPhysicalMaterial({ color: 0xf0f7f2, roughness: 0.2, transparent: true, opacity: 0.75, depthWrite: false, side: THREE.DoubleSide }), loaded.length);
    tips.name = "loaded-tips";
    loaded.forEach(({ local }, i) => tips.setMatrixAt(i, matrix.makeTranslation(local.x, local.y, local.z - 6.5).multiply(rotation)));
    group.add(tips);
  }
}

function addVial(group: THREE.Group, object: SceneObject) {
  const { x: diameter, z: height } = object.body.size;
  const r = diameter / 2, bottom = -height / 2, top = height / 2;
  const lip = Math.min(1, r * 0.15), neck = Math.min(5, height * 0.1);
  const profile = [
    new THREE.Vector2(0, bottom), new THREE.Vector2(r - lip, bottom),
    new THREE.Vector2(r, bottom + lip), new THREE.Vector2(r, top - neck),
    new THREE.Vector2(r * 0.86, top - neck * 0.35), new THREE.Vector2(r * 0.86, top),
    new THREE.Vector2(r * 0.86 - lip, top), new THREE.Vector2(r * 0.86 - lip, top - neck * 0.35),
    new THREE.Vector2(r - lip, top - neck), new THREE.Vector2(r - lip, bottom + 2 * lip),
    new THREE.Vector2(0, bottom + 2 * lip),
  ];
  const glass = new THREE.MeshPhysicalMaterial({
    color: 0xdce8ed, roughness: 0.12, clearcoat: 0.8, clearcoatRoughness: 0.15,
    transmission: 0.3, thickness: lip, ior: 1.45, side: THREE.DoubleSide,
  });
  const vial = new THREE.Mesh(new THREE.LatheGeometry(profile, 32), glass);
  vial.rotation.x = Math.PI / 2; vial.receiveShadow = true;
  group.add(vial);
  for (const z of [top - lip, top - 2.5 * lip]) {
    const rim = new THREE.Mesh(new THREE.TorusGeometry(r * 0.86, lip * 0.4, 6, 24), polymer(0xc3d5df, 0.18));
    rim.position.z = z; group.add(rim);
  }
}

/** Detailed illustrative fallback; all supplied positions remain unmodified. */
export function createLabwareMesh(object: SceneObject): THREE.Group {
  const group = new THREE.Group();
  const { center: c, size: s } = object.body;
  group.position.set(c.x, c.y, c.z);
  group.rotation.z = object.body.rotationZ;
  group.name = object.id;
  group.userData.geometrySource = "schematic";
  if (object.kind === "well_plate" || object.kind === "tip_rack") addTray(group, object, object.kind === "tip_rack");
  else if (object.kind === "vial") addVial(group, object);
  else if (object.kind === "tip_disposal") {
    const mat = polymer(0xc5d4e1, 0.6);
    block(group, s.x, s.y, 2, 0, 0, -s.z / 2 + 1, mat);
    for (const sign of [-1, 1]) {
      block(group, s.x, 2, s.z, 0, sign * (s.y / 2 - 1), 0, mat);
      block(group, 2, s.y - 2, s.z, sign * (s.x / 2 - 1), 0, 0, mat);
    }
  } else {
    const mat = polymer(0x355378, 0.5);
    const wall = Math.min(5, s.x / 8, s.y / 8);
    for (const sign of [-1, 1]) {
      edge(block(group, s.x, wall, s.z, 0, sign * (s.y / 2 - wall / 2), 0, mat));
      edge(block(group, wall, s.y - wall * 2, s.z, sign * (s.x / 2 - wall / 2), 0, 0, mat));
    }
  }
  return group;
}

