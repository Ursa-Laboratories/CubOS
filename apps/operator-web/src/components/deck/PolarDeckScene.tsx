import { useEffect, useRef, useState } from 'react';
import { Group, Mesh, MeshBasicMaterial, SphereGeometry } from 'three';
import { CAD_REST, createInstrumentHead, instrumentHeadLabel, mountPolarStudio, type Assembly, type PolarStudio } from '@ursa-labs/polar-bear-twin';
import modelUrl from '@ursa-labs/polar-bear-twin/assembly.glb?url';
import lightUrl from '@ursa-labs/polar-bear-twin/studio.hdr?url';
import type { Coordinate3D, DeckResponse, GantryConfig, InstrumentConfig, OriginPolicy } from '../../types';
import { createDeckOverlay, disposeDeckOverlay } from './three/deckOverlay';
import { createInstrumentBracket, disposeInstrumentModel, placeInstrumentModel } from './three/instrumentModels';
import { cadRestPosition, deckRegistration, instrumentEndpoint, type Range } from './three/polarRegistration';
import './polarDeck.css';

interface Props {
  deck: DeckResponse | null;
  instruments: Record<string, InstrumentConfig> | null;
  gantryPosition: Coordinate3D | null;
  machineXRange?: Range;
  machineYRange?: Range;
  machineZRange?: Range;
  originPolicy?: OriginPolicy;
  gantryType?: GantryConfig['gantry_type'];
  yAxisMotion?: 'head' | 'bed';
  onShow2D: () => void;
}

function instrumentTargets(instruments: Record<string, InstrumentConfig> | null) {
  const group = new Group();
  const geometry = new SphereGeometry(0.0025, 12, 8);
  const material = new MeshBasicMaterial({ color: 0x009a85, depthTest: false });
  const markers = Object.entries(instruments ?? {}).map(([name, config]) => {
    const marker = new Mesh(geometry, material);
    marker.name = name;
    marker.renderOrder = 1;
    group.add(marker);
    return { marker, config };
  });
  return {
    update(position: Coordinate3D | null, origin: Coordinate3D) {
      group.visible = position !== null;
      if (!position) return;
      for (const { marker, config } of markers) {
        const { x, y, z } = instrumentEndpoint(position, config, origin);
        marker.position.set(x, y, z);
      }
    },
    group,
    dispose() { group.removeFromParent(); geometry.dispose(); material.dispose(); },
  };
}

export default function PolarDeckScene({ deck, instruments, gantryPosition, gantryType, yAxisMotion, originPolicy = 'deck_origin',
  machineXRange = [0, 390], machineYRange = [0, 390], machineZRange = [0, 70], onShow2D }: Props) {
  const canvas = useRef<HTMLDivElement>(null);
  const studio = useRef<PolarStudio | null>(null);
  const selectedTools = useRef<Group | null>(null);
  const markers = useRef<ReturnType<typeof instrumentTargets> | null>(null);
  const [rig, setRig] = useState<Assembly | null>(null);
  const [error, setError] = useState(false);
  const [loadedTools, setLoadedTools] = useState<{ config: Props['instruments']; group: Group; missing: string[] } | null>(null);
  const toolLabels = Object.entries(instruments ?? {}).map(([name, config]) => `${name} · ${instrumentHeadLabel(config, name)}`);
  const tools = loadedTools?.config === instruments ? loadedTools : null;
  const status = error ? 'error' : rig ? 'ready' : 'loading';
  const { x, y, z } = deckRegistration(machineXRange, machineYRange, machineZRange, originPolicy);
  const [zMin, zMax] = machineZRange;
  const liveAxes = gantryType === 'genmitsu_4040_pro_max' && yAxisMotion === 'head';

  useEffect(() => {
    let disposed = false;
    async function load() {
      const stage = mountPolarStudio(canvas.current!, modelUrl, lightUrl, { showReferenceTool: false });
      studio.current = stage;
      const assembly = await stage.ready;
      if (!disposed) setRig(assembly);
    }
    load().catch(() => { if (!disposed) setError(true); });
    return () => {
      disposed = true;
      studio.current?.dispose();
      studio.current = null;
    };
  }, []);

  useEffect(() => {
    const stage = studio.current;
    if (!deck || !stage) return;
    const overlay = createDeckOverlay(deck);
    overlay.scale.setScalar(0.001);
    overlay.position.set(x, y, z);
    stage.scene.add(overlay);
    stage.redraw();
    return () => { disposeDeckOverlay(overlay); stage.redraw(); };
  }, [deck, x, y, z]);

  useEffect(() => {
    const stage = studio.current;
    if (!stage || !rig) return;
    const targets = instrumentTargets(instruments);
    stage.scene.add(targets.group);
    markers.current = targets;
    const heads = new Group();
    rig.carriage.add(heads);
    let disposed = false;
    const configs = Object.entries(instruments ?? {});
    Promise.allSettled(configs.map(async ([name, config]) => {
      const head = await createInstrumentHead(config, name);
      if (!head) return;
      head.name = name;
      if (disposed) {
        disposeInstrumentModel(head);
      } else {
        placeInstrumentModel(head, config);
        const bracket = createInstrumentBracket(head);
        heads.add(head);
        if (bracket) heads.add(bracket);
        stage.redraw();
      }
    })).then(results => {
      if (disposed) return;
      const missing = configs.filter((_, index) => results[index].status === 'rejected').map(([name]) => name);
      setLoadedTools({ config: instruments, group: heads, missing });
    });
    return () => {
      disposed = true;
      markers.current = null;
      // The unmounted studio already disposed its carriage subtree.
      if (studio.current === stage) {
        disposeInstrumentModel(heads);
        if (selectedTools.current === heads) stage.fit('iso');
      } else {
        heads.removeFromParent();
      }
      if (selectedTools.current === heads) selectedTools.current = null;
      targets.dispose();
      stage.redraw();
    };
  }, [instruments, rig]);

  useEffect(() => {
    const stage = studio.current;
    if (!stage || !rig) return;
    const origin = { x, y, z };
    const rest = cadRestPosition(origin, [zMin, zMax]);
    markers.current?.update(gantryPosition, origin);
    stage.move(gantryPosition && liveAxes ? {
      x: CAD_REST.x + gantryPosition.x - rest.x,
      y: CAD_REST.y + gantryPosition.y - rest.y,
      z: CAD_REST.z + gantryPosition.z - rest.z,
    } : null);
  }, [gantryPosition, instruments, liveAxes, rig, x, y, z, zMin, zMax]);

  return <section className="polar-deck" aria-label="3D deck visualization" data-state={status}>
    <div className="polar-deck-canvas" tabIndex={0} aria-label="Orbit or zoom the deck" ref={canvas}
      onPointerDownCapture={event => event.currentTarget.focus({ preventScroll: true })} />
    {status === 'ready' ? <>
      <div className="polar-deck-camera" role="group" aria-label="3D camera">
        <button type="button" onClick={() => {
          selectedTools.current = null;
          studio.current?.fit('iso');
        }}>Fit</button>
        {tools && tools.group.children.length > 0 && <button type="button" onClick={() => {
          selectedTools.current = tools.group;
          studio.current?.fitObject(tools.group);
        }}>Tools</button>}
        <button type="button" onClick={() => {
          selectedTools.current = null;
          studio.current?.fit('top');
        }}>Top</button>
      </div>
      <div className="polar-deck-caption">
        <div>4040 reference · {gantryPosition ? liveAxes ? 'Live axes and targets' : 'Live targets' : 'CAD pose'}</div>
        {toolLabels.length > 0 && <div>{toolLabels.join(' / ')}</div>}
        {Boolean(tools?.missing.length) && <div role="status">Model unavailable · {tools?.missing.join(', ')}</div>}
      </div>
    </> : <div className="polar-deck-status" role="status">
      {status === 'loading' ? 'Loading 3D…' : <>3D unavailable <button type="button" onClick={onShow2D}>Show 2D</button></>}
    </div>}
  </section>;
}
