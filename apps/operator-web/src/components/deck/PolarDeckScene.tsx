import { useEffect, useRef, useState } from 'react';
import { Group, Mesh, MeshBasicMaterial, SphereGeometry } from 'three';
import { CAD_REST, mountPolarStudio, type PolarStudio } from '@ursa-labs/polar-bear-twin';
import modelUrl from '@ursa-labs/polar-bear-twin/assembly.glb?url';
import lightUrl from '@ursa-labs/polar-bear-twin/studio.hdr?url';
import type { Coordinate3D, DeckResponse, GantryConfig, InstrumentConfig, OriginPolicy } from '../../types';
import { createDeckOverlay, disposeDeckOverlay } from './three/deckOverlay';
import { assemblyDelta, deckRegistration, type Range } from './three/polarRegistration';
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
  for (const [name, instrument] of Object.entries(instruments ?? {})) {
    const marker = new Mesh(geometry, material);
    marker.name = name;
    marker.renderOrder = 1;
    marker.position.set(instrument.offset_x / 1000, -(instrument.depth ?? 0) / 1000, -instrument.offset_y / 1000);
    group.add(marker);
  }
  return { group, dispose() { group.removeFromParent(); geometry.dispose(); material.dispose(); } };
}

export default function PolarDeckScene({ deck, instruments, gantryPosition, gantryType, yAxisMotion, originPolicy = 'deck_origin',
  machineXRange = [0, 390], machineYRange = [0, 390], machineZRange = [0, 70], onShow2D }: Props) {
  const canvas = useRef<HTMLDivElement>(null);
  const studio = useRef<PolarStudio | null>(null);
  const markers = useRef<Group | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const origin = deckRegistration(machineXRange, machineYRange, machineZRange, originPolicy);
  const { x, y, z } = origin;
  const [zMin, zMax] = machineZRange;
  const pipette = Object.values(instruments ?? {}).find(item => item.type === 'pipette' && item.vendor === 'sartorius');
  const trackSlide = gantryType === 'genmitsu_4040_pro_max' && yAxisMotion === 'head' && Boolean(pipette);

  useEffect(() => {
    let disposed = false;
    async function load() {
      const stage = mountPolarStudio(canvas.current!, modelUrl, lightUrl);
      studio.current = stage;
      await stage.ready;
      if (!disposed) setStatus('ready');
    }
    load().catch(() => { if (!disposed) setStatus('error'); });
    return () => { disposed = true; studio.current?.dispose(); studio.current = null; };
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
    if (!stage) return;
    const targets = instrumentTargets(instruments);
    stage.scene.add(targets.group);
    markers.current = targets.group;
    return () => { markers.current = null; targets.dispose(); };
  }, [instruments]);

  useEffect(() => {
    const stage = studio.current;
    if (!stage) return;
    let pose = null;
    if (gantryPosition && trackSlide && pipette) {
      const delta = assemblyDelta(gantryPosition, { x: pipette.offset_x, y: pipette.offset_y }, { x, y, z }, [zMin, zMax]);
      pose = { x: CAD_REST.x + delta.x, y: CAD_REST.y + delta.y, z: CAD_REST.z + delta.z };
    }
    if (markers.current) {
      markers.current.visible = Boolean(gantryPosition);
      if (gantryPosition) markers.current.position.set(x + gantryPosition.x / 1000, y + gantryPosition.z / 1000, z - gantryPosition.y / 1000);
    }
    stage.move(pose);
  }, [gantryPosition, instruments, pipette, trackSlide, x, y, z, zMin, zMax]);

  return <section className="polar-deck" aria-label="3D deck visualization" data-state={status}>
    <div className="polar-deck-canvas" tabIndex={0} aria-label="Orbit or zoom the deck" ref={canvas}
      onPointerDownCapture={event => event.currentTarget.focus({ preventScroll: true })} />
    {status === 'ready' ? <>
      <div className="polar-deck-camera" role="group" aria-label="3D camera">
        <button type="button" onClick={() => studio.current?.fit('iso')}>Fit</button>
        <button type="button" onClick={() => studio.current?.fit('tool')}>Tool</button>
        <button type="button" onClick={() => studio.current?.fit('top')}>Top</button>
      </div>
      <span className="polar-deck-caption">4040 · 5 mL reference{gantryPosition && trackSlide ? ' · Live axes' : gantryPosition ? ' · Live targets, CAD pose' : ' · CAD pose'}</span>
    </> : <div className="polar-deck-status" role="status">
      {status === 'loading' ? 'Loading 3D…' : <>3D unavailable <button type="button" onClick={onShow2D}>Show 2D</button></>}
    </div>}
  </section>;
}
