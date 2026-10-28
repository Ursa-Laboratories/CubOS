import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import type { Coordinate3D } from "../../../types";
import type { SceneModel } from "./sceneModel";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { loadCadAsset } from "./cadAssets";
import { createLabwareMesh, createCadTipOverlay, styleCadMesh } from "./labwareMeshes";

export interface SceneRenderer {
  update(model: SceneModel): void;
  select(id: string): void;
  labels(visible: boolean): void;
  frame(visible: boolean): void;
  view(view: "orbit" | "top" | "fit" | "focus"): void;
  zoom(factor: number): void;
  rotate(horizontal: number, vertical: number): void;
  dispose(): void;
}

type Label = { element: HTMLButtonElement; anchor: THREE.Vector3; id: string };
const vector = (p: Coordinate3D) => new THREE.Vector3(p.x, p.y, p.z);

function disposeGroup(group: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  group.traverse(object => {
    if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
      geometries.add(object.geometry);
      const list = Array.isArray(object.material) ? object.material : [object.material];
      list.forEach(material => materials.add(material));
    }
  });
  geometries.forEach(geometry => geometry.dispose());
  materials.forEach(material => material.dispose());
  group.clear();
}

function material(color: number, opacity = 1) {
  return new THREE.MeshPhysicalMaterial({ color, roughness: 0.4, metalness: 0.05, clearcoat: 0.2, transparent: opacity < 1, opacity });
}

function box(size: Coordinate3D, center: Coordinate3D, mat: THREE.Material) {
  const mesh = new THREE.Mesh(new RoundedBoxGeometry(size.x, size.y, size.z, 2, Math.min(1.5, size.x / 8, size.y / 8, size.z / 8)), mat);
  mesh.position.copy(vector(center));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function cylinder(radiusTop: number, radiusBottom: number, height: number, z: number, mat: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radiusTop, radiusBottom, height, 24), mat);
  mesh.rotation.x = Math.PI / 2;
  mesh.position.z = z;
  mesh.castShadow = true;
  return mesh;
}

/** Rendering uses CubOS XYZ directly; camera Z is up, floor is XY. */
export function createSceneRenderer(
  host: HTMLDivElement,
  labelHost: HTMLDivElement,
  axis: SVGSVGElement,
  onSelect: (id: string) => void,
  onFailure: (message: string) => void,
): SceneRenderer {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.VSMShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute("aria-label", "3D deck. Drag to orbit, scroll to zoom. Arrow keys rotate the view.");
  renderer.domElement.setAttribute("role", "img");
  host.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-300, 300, 300, -300, 0.1, 20000);
  camera.up.set(0, 0, 1);
  camera.position.set(400, -500, 500);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = false; // Render on demand, including on low-powered appliances.
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.minZoom = 0.1;
  controls.maxZoom = 30;
  const environmentRoom = new RoomEnvironment();
  const pmrem = new THREE.PMREMGenerator(renderer);
  const environment = pmrem.fromScene(environmentRoom, 0.04);
  scene.environment = environment.texture;
  scene.environmentIntensity = 0.7;
  scene.environmentRotation.set(Math.PI / 2, 0, 0);
  environmentRoom.dispose(); pmrem.dispose();
  const ambient = new THREE.HemisphereLight(0xffffff, 0x75889d, 0.7);
  ambient.position.set(0, 0, 1000);
  const light = new THREE.DirectionalLight(0xffffff, 2.3);
  light.position.set(-200, -300, 600);
  light.castShadow = true;
  light.shadow.mapSize.set(2048, 2048);
  light.shadow.radius = 4;
  light.shadow.blurSamples = 8;
  light.shadow.normalBias = 0.12;
  light.shadow.camera.left = -650;
  light.shadow.camera.right = 650;
  light.shadow.camera.top = 650;
  light.shadow.camera.bottom = -650;
  light.shadow.camera.far = 2000;
  light.shadow.bias = -0.0001;
  scene.add(ambient, light, light.target);

  const stage = new THREE.Group(), labware = new THREE.Group(), instruments = new THREE.Group(), frame = new THREE.Group();
  scene.add(stage, labware, instruments, frame);
  const selection = new THREE.Box3Helper(new THREE.Box3(), 0x3478f6);
  selection.visible = false;
  scene.add(selection);
  const selectable = new Map<string, THREE.Group>();
  const labels: Label[] = [];
  let selected = "", labelsVisible = true, frameVisible = false, disposed = false;
  let model: SceneModel | null = null;
  let signature = "", instrumentSignature = "", stageSignature = "";
  let instrumentVisibilitySignature = "";
  let pending = 0;
  let size = { width: 1, height: 1 };
  let bounds = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(300, 200, 150));
  let firstFit = true;
  let objectRevision = 0;
  let fitTargetId: string | null = null;

  function render() {
    pending = 0;
    if (disposed) return;
    const lightTheme = document.documentElement.dataset.theme === "light";
    scene.background = new THREE.Color(lightTheme ? 0xeff1f3 : 0x1b2330);
    renderer.render(scene, camera);
    const occupied: { x: number; y: number; width: number }[] = [];
    [...labels].sort((a, b) => Number(b.id === selected) - Number(a.id === selected)).forEach(label => {
      const p = label.anchor.clone().project(camera);
      const x = (p.x + 1) / 2 * size.width, y = (1 - p.y) / 2 * size.height;
      const width = Math.min(150, label.element.textContent!.length * 7 + 16);
      const overlaps = occupied.some(other => Math.abs(x - other.x) < (width + other.width) / 2 + 4 && Math.abs(y - other.y) < 27);
      const visible = labelsVisible && p.z > -1 && p.z < 1 && x > 10 && x < size.width - 10 && y > 60 && y < size.height - 30 && (!overlaps || label.id === selected);
      label.element.hidden = !visible;
      if (!visible) return;
      label.element.style.left = x + "px";
      label.element.style.top = y + "px";
      label.element.dataset.selected = String(label.id === selected);
      occupied.push({ x, y, width });
    });
    // A camera-relative axis triad stays meaningful while orbiting.
    const inverse = camera.quaternion.clone().invert();
    ["X", "Y", "Z"].forEach((name, i) => {
      const direction = new THREE.Vector3(i === 0 ? 1 : 0, i === 1 ? 1 : 0, i === 2 ? 1 : 0).applyQuaternion(inverse);
      const x = 32 + direction.x * 27, y = 43 - direction.y * 27;
      const line = axis.querySelector('[data-axis="' + name + '"]');
      line?.setAttribute("x2", String(x));
      line?.setAttribute("y2", String(y));
      const text = axis.querySelector('[data-label="' + name + '"]');
      text?.setAttribute("x", String(x + direction.x * 8));
      text?.setAttribute("y", String(y - direction.y * 8 + 3));
    });
  }
  function requestRender() { if (!pending && !disposed) pending = requestAnimationFrame(render); }
  controls.addEventListener("change", requestRender);
  const themeObserver = new MutationObserver(requestRender);
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

  function addLabel(id: string, text: string, anchor: THREE.Vector3) {
    const element = document.createElement("button");
    element.type = "button";
    element.className = "deck3d-label";
    element.textContent = text;
    element.title = text;
    element.setAttribute("aria-label", "Select " + text);
    element.addEventListener("click", () => onSelect(id));
    labelHost.appendChild(element);
    labels.push({ id, element, anchor });
  }
  function clearLabels() { labels.splice(0).forEach(label => label.element.remove()); }
  function updateSelection() {
    const group = selectable.get(selected);
    selection.visible = !!group;
    if (group) {
      group.updateWorldMatrix(true, true);
      selection.box.setFromObject(group).expandByScalar(0.8);
    }
    for (const [id, group] of selectable) {
      group.traverse(object => {
        if (!(object instanceof THREE.Mesh)) return;
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        materials.forEach(mat => {
          if (!(mat instanceof THREE.MeshStandardMaterial)) return;
          mat.emissive.set(id === selected ? 0x1c478c : 0x000000);
          mat.emissiveIntensity = id === selected ? 0.15 : 0;
        });
      });
    }
    requestRender();
  }
  function fit(targetBounds: THREE.Box3, direction?: THREE.Vector3, parts = [targetBounds]) {
    const center = targetBounds.getCenter(new THREE.Vector3());
    const offset = direction ?? camera.position.clone().sub(controls.target).normalize();
    const right = new THREE.Vector3().crossVectors(camera.up, offset).normalize();
    const up = new THREE.Vector3().crossVectors(offset, right).normalize();
    let halfWidth = 10, halfHeight = 10;
    for (const part of parts) {
      for (const x of [part.min.x, part.max.x]) for (const y of [part.min.y, part.max.y]) for (const z of [part.min.z, part.max.z]) {
        const corner = new THREE.Vector3(x, y, z).sub(center);
        halfWidth = Math.max(halfWidth, Math.abs(corner.dot(right)));
        halfHeight = Math.max(halfHeight, Math.abs(corner.dot(up)));
      }
    }
    const aspect = size.width / size.height;
    const extent = Math.max(halfHeight, halfWidth / aspect) * 1.15;
    camera.left = -extent * aspect; camera.right = extent * aspect;
    camera.top = extent; camera.bottom = -extent; camera.zoom = 1;
    const distance = Math.max(100, targetBounds.getSize(new THREE.Vector3()).length() * 2);
    controls.target.copy(center);
    camera.position.copy(center).addScaledVector(offset, distance);
    camera.near = 0.1; camera.far = Math.max(10000, distance * 4);
    camera.updateProjectionMatrix(); controls.update(); requestRender();
  }
  function visibleBounds() {
    // Fit what is drawn, not the empty height of the configured working volume.
    const result = stage.children[0] ? new THREE.Box3().setFromObject(stage.children[0]) : bounds.clone();
    if (labware.children.length) result.union(new THREE.Box3().setFromObject(labware));
    if (instruments.children.length) result.union(new THREE.Box3().setFromObject(instruments));
    if (frameVisible) result.union(new THREE.Box3().setFromObject(frame));
    return result.isEmpty() ? bounds : result;
  }
  function fitScene(direction?: THREE.Vector3) {
    fitTargetId = null;
    const parts = [...stage.children.slice(0, 2), ...labware.children, ...instruments.children, ...(frameVisible ? frame.children : [])]
      .map(object => new THREE.Box3().setFromObject(object));
    fit(visibleBounds(), direction, parts);
  }
  const resize = new ResizeObserver(() => {
    size = { width: Math.max(1, host.clientWidth), height: Math.max(1, host.clientHeight) };
    renderer.setSize(size.width, size.height, false);
    camera.left = -camera.top * size.width / size.height;
    camera.right = camera.top * size.width / size.height;
    camera.updateProjectionMatrix();
    if (firstFit && model) { fitScene(new THREE.Vector3(0.45, -1, 0.95).normalize()); firstFit = false; }
    else if (model) {
      const focused = fitTargetId ? selectable.get(fitTargetId) : null;
      if (focused) fit(new THREE.Box3().setFromObject(focused));
      else fitScene();
    }
    requestRender();
  });
  resize.observe(host);

  function buildStage(current: SceneModel) {
    disposeGroup(stage); disposeGroup(frame);
    const { x, y, z } = current.configuredBounds;
    const cx = (x[0] + x[1]) / 2, cy = (y[0] + y[1]) / 2;
    const width = Math.max(20, x[1] - x[0]), depth = Math.max(20, y[1] - y[0]);
    const floorZ = z[0];
    stage.add(box({ x: width + 16, y: depth + 16, z: 6 }, { x: cx, y: cy, z: floorZ - 3 }, material(0x697b90)));
    stage.add(box({ x: width + 20, y: 5, z: 9 }, { x: cx, y: y[0] - 8, z: floorZ - 4 }, material(0x233c78)));
    const gridSize = Math.ceil(Math.max(width, depth) / 50) * 50 + 100;
    const grid = new THREE.GridHelper(gridSize, Math.min(100, Math.round(gridSize / 10)), 0x7f94a8, 0x9faebd);
    grid.rotation.x = Math.PI / 2;
    grid.position.set(cx, cy, floorZ + 0.05);
    (grid.material as THREE.Material).transparent = true;
    (grid.material as THREE.Material).opacity = 0.18;
    stage.add(grid);
    const span = Math.max(width, depth);
    light.position.set(cx - span * 0.55, cy - span * 0.7, floorZ + span * 1.3);
    light.target.position.set(cx, cy, floorZ);
    light.target.updateMatrixWorld();
    light.shadow.camera.left = -span * 0.85; light.shadow.camera.right = span * 0.85;
    light.shadow.camera.top = span * 0.85; light.shadow.camera.bottom = -span * 0.85;
    light.shadow.camera.far = span * 4;
    light.shadow.camera.updateProjectionMatrix();
    const frameHeight = floorZ + Math.max(90, z[1] - z[0]) + 20;
    const ghost = material(0xa8c0d6, 0.15);
    ghost.depthWrite = false;
    for (const side of [x[0] - 8, x[1] + 8]) {
      frame.add(box({ x: 6, y: 8, z: frameHeight - floorZ }, { x: side, y: y[1] - 8, z: (frameHeight + floorZ) / 2 }, ghost));
    }
    for (const height of [frameHeight - 10, frameHeight - 28]) {
      frame.add(box({ x: width + 22, y: 5, z: 5 }, { x: cx, y: y[1] - 8, z: height }, ghost));
    }
    frame.visible = frameVisible;
  }
  function buildObjects(current: SceneModel) {
    const revision = ++objectRevision;
    disposeGroup(labware);
    for (const [id, group] of selectable) if (group.parent !== instruments) selectable.delete(id);
    current.objects.forEach(object => {
      const group = new THREE.Group();
      group.userData.selectId = object.id;
      group.add(createLabwareMesh(object));
      labware.add(group); selectable.set(object.id, group);
      void loadCadAsset(object).then(cad => {
        if (!cad) return;
        if (disposed || revision !== objectRevision || group.parent !== labware) { disposeGroup(cad); return; }
        styleCadMesh(cad, object.kind);
        cad.position.copy(vector(object.body.center));
        cad.rotation.z = object.body.rotationZ;
        disposeGroup(group);
        group.add(cad);
        group.add(createCadTipOverlay(object));
        host.dataset.cadModels = String(labware.children.filter(child => child.children[0]?.userData.geometrySource === "cad").length);
        updateSelection();
      });
    });
    host.dataset.cadModels = "0";
  }
  function buildInstruments(current: SceneModel) {
    for (const [id, group] of selectable) if (group.parent === instruments) selectable.delete(id);
    disposeGroup(instruments);
    current.instruments.forEach(instrument => {
      if (!instrument.position || !instrument.body) return;
      const group = new THREE.Group();
      group.userData.selectId = instrument.id;
      group.position.copy(vector(instrument.position));
      if (instrument.type.includes("pipette")) {
        group.add(cylinder(9, 7, 43, 61, material(0xf0efe6)));
        group.add(cylinder(3, 3, 24, 28, material(0x303d4d)));
        group.add(cylinder(2, 0.6, 16, 8, material(0x1d2938)));
        group.add(cylinder(9.3, 9.3, 4, 43, material(0x487fa5)));
        group.add(cylinder(4, 4, 3, 84, material(0xe0bd45)));
        group.add(box({ x: 10, y: 1, z: 9 }, { x: 0, y: -8.5, z: 65 }, material(0x203142)));
      } else {
        group.add(box({ x: 20, y: 18, z: 30 }, { x: 0, y: 0, z: 25 }, material(0xb8a9dc)));
        group.add(cylinder(2, 1, 10, 5, material(0x29364b)));
      }
      instruments.add(group);
      selectable.set(instrument.id, group);
    });
  }
  function refreshLabels(current: SceneModel) {
    clearLabels();
    const labelledParents = new Set(current.objects.map(object => object.id));
    current.objects.forEach(object => {
      let text = object.label;
      // Use one label per vial grid/holder; individual vials remain selectable.
      if (object.parentId && object.kind === "vial" && object.id !== selected) {
        if (labelledParents.has(object.parentId)) return;
        labelledParents.add(object.parentId);
        text = object.parentLabel ?? object.label;
      }
      const p = vector(object.body.center);
      p.z += object.body.size.z / 2 + (object.kind === "tip_rack" ? 14 : 5);
      addLabel(object.id, text, p);
    });
    current.instruments.forEach(instrument => {
      if (instrument.position) addLabel(instrument.id, instrument.label, vector(instrument.position).add(new THREE.Vector3(0, 0, 88)));
    });
  }

  const ray = new THREE.Raycaster();
  let pointerDown = { x: 0, y: 0 };
  function down(event: PointerEvent) { pointerDown = { x: event.clientX, y: event.clientY }; }
  function up(event: PointerEvent) {
    if (event.button !== 0 || Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y) > 5) return;
    const rect = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
    const hit = ray.intersectObjects([...labware.children, ...instruments.children], true)[0];
    let object: THREE.Object3D | null = hit?.object ?? null;
    while (object && !object.userData.selectId) object = object.parent;
    onSelect(object ? String(object.userData.selectId) : "");
  }
  function lost(event: Event) { event.preventDefault(); api.dispose(); onFailure("The 3D graphics context was lost. Switch to 2D, or reopen 3D to retry."); }
  renderer.domElement.addEventListener("pointerdown", down);
  renderer.domElement.addEventListener("pointerup", up);
  renderer.domElement.addEventListener("webglcontextlost", lost);

  const api: SceneRenderer = {
    update(current) {
      if (disposed) return;
      model = current;
      bounds = new THREE.Box3(new THREE.Vector3(current.bounds.x[0], current.bounds.y[0], current.bounds.z[0]), new THREE.Vector3(current.bounds.x[1], current.bounds.y[1], current.bounds.z[1]));
      const next = JSON.stringify(current.objects);
      const geometryChanged = next !== signature;
      if (geometryChanged) { buildObjects(current); signature = next; firstFit = true; }
      const nextStage = JSON.stringify(current.configuredBounds);
      if (nextStage !== stageSignature) { buildStage(current); stageSignature = nextStage; }
      const nextInstruments = JSON.stringify(current.instruments);
      if (nextInstruments !== instrumentSignature) { buildInstruments(current); instrumentSignature = nextInstruments; }
      const nextVisibility = JSON.stringify(current.instruments.filter(item => item.position).map(item => item.id));
      if (nextVisibility !== instrumentVisibilitySignature) {
        firstFit = true;
        instrumentVisibilitySignature = nextVisibility;
      }
      refreshLabels(current);
      if (firstFit && host.clientWidth > 0 && host.clientHeight > 0) {
        size = { width: host.clientWidth, height: host.clientHeight };
        camera.left = -camera.top * size.width / size.height;
    camera.right = camera.top * size.width / size.height;
        renderer.setSize(size.width, size.height, false);
        fitScene(new THREE.Vector3(0.45, -1, 0.95).normalize());
        firstFit = false;
      }
      updateSelection();
    },
    select(id) { if (disposed) return; selected = id; if (model) refreshLabels(model); updateSelection(); },
    labels(visible) { labelsVisible = visible; requestRender(); },
    frame(visible) { frameVisible = visible; frame.visible = visible; requestRender(); },
    view(view) {
      if (view === "focus") {
        const object = selectable.get(selected);
        if (object) { fitTargetId = selected; fit(new THREE.Box3().setFromObject(object)); }
      } else fitScene(view === "top" ? new THREE.Vector3(0, -0.0001, 1).normalize() : view === "orbit" ? new THREE.Vector3(0.45, -1, 0.95).normalize() : undefined);
    },
    zoom(factor) {
      camera.zoom = THREE.MathUtils.clamp(camera.zoom / factor, controls.minZoom, controls.maxZoom);
      camera.updateProjectionMatrix(); controls.update(); requestRender();
    },
    rotate(horizontal, vertical) {
      const offset = camera.position.clone().sub(controls.target);
      offset.applyAxisAngle(new THREE.Vector3(0, 0, 1), horizontal);
      const right = new THREE.Vector3().crossVectors(offset, camera.up).normalize();
      const candidate = offset.clone().applyAxisAngle(right, vertical);
      if (candidate.z > 1) offset.copy(candidate);
      camera.position.copy(controls.target).add(offset);
      controls.update(); requestRender();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      cancelAnimationFrame(pending);
      resize.disconnect(); themeObserver.disconnect(); controls.dispose();
      renderer.domElement.removeEventListener("pointerdown", down);
      renderer.domElement.removeEventListener("pointerup", up);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      clearLabels();
      [stage, labware, instruments, frame].forEach(disposeGroup);
      selection.geometry.dispose();
      (selection.material as THREE.Material).dispose();
      light.shadow.map?.dispose();
      environment.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    },
  };
  return api;
}
