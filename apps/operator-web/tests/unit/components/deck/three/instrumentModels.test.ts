import { BoxGeometry, Group, Mesh, MeshStandardMaterial, Vector3 } from 'three';
import { describe, expect, it, vi } from 'vitest';
import { createInstrumentBracket, disposeInstrumentModel, placeInstrumentModel } from '../../../../../src/components/deck/three/instrumentModels';
import { CAD_NOZZLE } from '../../../../../src/components/deck/three/polarRegistration';

describe('Polar Bear reference instruments', () => {
  it('places each bare endpoint independently and maintains separation as the carriage moves', () => {
    const carriage = new Group();
    const first = new Group();
    const second = new Group();
    carriage.add(first, second);
    placeInstrumentModel(first, { type: 'spectrometer', vendor: 'example', offset_x: 0, offset_y: 0 });
    placeInstrumentModel(second, { type: 'mounted_tool', vendor: 'example', offset_x: -45, offset_y: 20, depth: 36 });
    expect(first.position.toArray()).toEqual([CAD_NOZZLE.x, CAD_NOZZLE.y, CAD_NOZZLE.z]);
    carriage.position.set(0.040, -0.025, -0.078);
    const separation = second.getWorldPosition(new Vector3()).sub(first.getWorldPosition(new Vector3()));
    expect(separation.x).toBeCloseTo(-0.045, 8);
    expect(separation.y).toBeCloseTo(-0.036, 8);
    expect(separation.z).toBeCloseTo(-0.020, 8);
  });

  it('contacts the body behind each of two heads with a narrow cable above it', () => {
    const attachments = [-65, 55].map(offset_x => {
      const model = new Group();
      const body = new Mesh(new BoxGeometry(0.04, 0.09, 0.04), new MeshStandardMaterial());
      const cable = new Mesh(new BoxGeometry(0.003, 0.14, 0.003), new MeshStandardMaterial());
      body.position.y = 0.055;
      cable.position.y = 0.17;
      model.add(body, cable);
      placeInstrumentModel(model, { type: 'mounted_tool', vendor: 'example', offset_x, offset_y: 0 });

      const bracket = createInstrumentBracket(model);
      if (!bracket) throw new Error('Expected the body to need a bracket');
      const axis = new Vector3(0, bracket.geometry.parameters.height / 2, 0).applyQuaternion(bracket.quaternion);
      const contact = bracket.position.clone().add(axis);
      const anchor = bracket.position.clone().sub(axis);
      expect(contact.y).toBeLessThan(model.position.y + 0.1);
      expect(contact.z).toBeCloseTo(model.position.z - 0.02 + 0.001, 8);
      expect(anchor.z).toBeCloseTo(-0.380, 8);
      expect(anchor.x).toBeCloseTo(model.position.x, 8);
      disposeInstrumentModel(model);
      disposeInstrumentModel(bracket);
      return anchor;
    });
    expect(attachments[1].x - attachments[0].x).toBeCloseTo(0.120, 8);
  });

  it('omits the strut for a body already flush with the backboard', () => {
    const model = new Group();
    const body = new Mesh(new BoxGeometry(0.04, 0.16, 0.04), new MeshStandardMaterial());
    body.position.y = 0.10;
    model.add(body);
    model.position.set(0.23, 0.12, -0.359);
    expect(createInstrumentBracket(model)).toBeNull();
    disposeInstrumentModel(model);
  });

  it('releases detached geometry and materials', () => {
    const carriage = new Group();
    const mount = new Group();
    const body = new Mesh(new BoxGeometry(0.04, 0.14, 0.04), new MeshStandardMaterial());
    mount.add(body);
    carriage.add(mount);

    const freeGeometry = vi.spyOn(body.geometry, 'dispose');
    const freeMaterial = vi.spyOn(body.material, 'dispose');
    disposeInstrumentModel(mount);
    expect(carriage.children).toHaveLength(0);
    expect(freeGeometry).toHaveBeenCalledOnce();
    expect(freeMaterial).toHaveBeenCalledOnce();
  });
});
