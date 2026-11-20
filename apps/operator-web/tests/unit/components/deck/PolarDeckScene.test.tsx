import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Scene } from 'three';
import { describe, expect, it, vi } from 'vitest';
import PolarDeckScene from '../../../../src/components/deck/PolarDeckScene';

const { createInstrumentHead, mountPolarStudio } = vi.hoisted(() => ({
  createInstrumentHead: vi.fn(),
  mountPolarStudio: vi.fn(),
}));

vi.mock('@ursa-labs/polar-bear-twin', () => ({
  CAD_REST: { x: 195, y: 195, z: 35 },
  createInstrumentHead,
  mountPolarStudio,
}));

const pipette = { type: 'pipette', vendor: 'sartorius', pipette_model: 'picus2_1ch_5000', offset_x: 0, offset_y: 0 };
const probe = { type: 'mounted_tool', vendor: 'custom', offset_x: -36, offset_y: 18, depth: 32 };

function makeStage() {
  const rig = { carriage: new Group() };
  const stage = {
    fit: vi.fn(),
    fitObject: vi.fn(),
    scene: new Scene(),
    ready: Promise.resolve(rig),
    move: vi.fn(),
    redraw: vi.fn(),
    dispose: vi.fn(),
  };
  mountPolarStudio.mockReset().mockReturnValue(stage);
  return { rig, stage };
}

function makeHead() {
  const head = new Group();
  const mesh = new Mesh(new BoxGeometry(0.035, 0.15, 0.04), new MeshStandardMaterial());
  mesh.position.y = 0.075;
  head.add(mesh);
  return { head, mesh };
}

describe('3D instrument configuration', () => {
  it('hides the assembly reference pipette, then fits independent configured heads and tracks live axes', async () => {
    const { rig, stage } = makeStage();
    createInstrumentHead.mockReset().mockImplementation(async () => makeHead().head);
    const props = { deck: null, gantryType: 'genmitsu_4040_pro_max', yAxisMotion: 'head', onShow2D: vi.fn() } as const;
    const { rerender } = render(<PolarDeckScene {...props} instruments={null} gantryPosition={null} />);
    await screen.findByRole('button', { name: 'Fit' });
    expect(screen.queryByRole('button', { name: 'Tools' })).toBeNull();
    expect(mountPolarStudio.mock.lastCall?.[3]).toEqual({ showReferenceTool: false });
    expect(createInstrumentHead).not.toHaveBeenCalled();
    expect(stage.move).toHaveBeenLastCalledWith(null);

    const instruments = { reagent: pipette, sample: pipette, probe };
    rerender(<PolarDeckScene {...props} instruments={instruments} gantryPosition={{ x: 90, y: 40, z: 30 }} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Tools' }));
    expect(createInstrumentHead.mock.calls).toEqual([[pipette, 'reagent'], [pipette, 'sample'], [probe, 'probe']]);
    expect(rig.carriage.children[0].children.filter(child => child instanceof Group).map(child => child.name))
      .toEqual(['reagent', 'sample', 'probe']);
    expect(stage.fitObject).toHaveBeenCalledWith(rig.carriage.children[0]);
    expect(screen.getByRole('region', { name: '3D deck visualization' })).toHaveTextContent(/^FitToolsTop$/);
    expect(stage.move.mock.lastCall?.[0]).toMatchObject({ z: 30 });

    rerender(<PolarDeckScene {...props} instruments={instruments} gantryPosition={{ x: 93, y: 40, z: 25 }} />);
    expect(stage.move.mock.lastCall?.[0]).toMatchObject({ z: 25 });
    expect(stage.fitObject).toHaveBeenCalledOnce();
    expect(createInstrumentHead).toHaveBeenCalledTimes(3);
  });

  it('preserves camera positions without attaching a camera mesh or a bracket', async () => {
    const { rig, stage } = makeStage();
    createInstrumentHead.mockReset().mockResolvedValue(null);
    const cameras = {
      left: { type: 'camera', vendor: 'opencv', offset_x: -20, offset_y: 0 },
      right: { type: 'camera', vendor: 'mount_only', offset_x: 20, offset_y: 0 },
    };
    render(<PolarDeckScene deck={null} instruments={cameras} gantryPosition={{ x: 40, y: 20, z: 30 }} onShow2D={vi.fn()} />);
    await waitFor(() => expect(createInstrumentHead).toHaveBeenCalledTimes(2));
    expect(rig.carriage.children[0].children).toHaveLength(0);
    expect(stage.scene.getObjectByName('left')).toBeDefined();
    expect(stage.scene.getObjectByName('right')).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Tools' })).toBeNull();
    expect(screen.queryByText(/Model unavailable/)).toBeNull();
  });

  it('keeps successful heads visible when another model fails and clears feedback on config change', async () => {
    const { rig, stage } = makeStage();
    const { head } = makeHead();
    createInstrumentHead.mockReset().mockResolvedValueOnce(head).mockRejectedValueOnce(new Error('Missing GLB'));
    const props = { deck: null, gantryPosition: null, onShow2D: vi.fn() };
    const { rerender } = render(<PolarDeckScene {...props} instruments={{ sample: pipette, probe }} />);
    expect(await screen.findByText('Model unavailable · probe')).toHaveAttribute('role', 'status');
    expect(rig.carriage.children[0].children).toContain(head);
    fireEvent.click(screen.getByRole('button', { name: 'Tools' }));

    rerender(<PolarDeckScene {...props} instruments={null} />);
    expect(screen.queryByText(/Model unavailable/)).not.toBeInTheDocument();
    expect(stage.fit).toHaveBeenCalledWith('iso');
    expect(head.parent?.parent).toBeNull();
  });

  it('leaves attached head disposal to the studio on unmount', async () => {
    const { rig, stage } = makeStage();
    const { head, mesh } = makeHead();
    const disposed = vi.spyOn(mesh.geometry, 'dispose');
    stage.dispose.mockImplementation(() => {
      rig.carriage.traverse(child => {
        if (child instanceof Mesh) child.geometry.dispose();
      });
    });
    createInstrumentHead.mockReset().mockResolvedValueOnce(head);
    const { unmount } = render(<PolarDeckScene deck={null} instruments={{ probe }} gantryPosition={null} onShow2D={vi.fn()} />);
    await screen.findByRole('button', { name: 'Tools' });
    unmount();
    expect(disposed).toHaveBeenCalledOnce();
  });

  it('disposes a head that resolves after its configuration was replaced', async () => {
    const { rig } = makeStage();
    const { head, mesh } = makeHead();
    const disposed = vi.spyOn(mesh.geometry, 'dispose');
    let finishLoad: (value: Group) => void = () => {};
    createInstrumentHead.mockReset().mockReturnValueOnce(new Promise<Group>(resolve => { finishLoad = resolve; }));
    const props = { deck: null, gantryPosition: null, onShow2D: vi.fn() };
    const { rerender } = render(<PolarDeckScene {...props} instruments={{ probe }} />);
    await screen.findByRole('button', { name: 'Fit' });
    expect(createInstrumentHead).toHaveBeenCalledWith(probe, 'probe');
    await act(async () => {
      rerender(<PolarDeckScene {...props} instruments={null} />);
    });
    await act(async () => finishLoad(head));
    expect(disposed).toHaveBeenCalledOnce();
    expect(rig.carriage.children[0].children).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Tools' })).toBeNull();
  });
});
