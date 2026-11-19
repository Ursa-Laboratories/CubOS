import { expect, test } from '@playwright/test';
import { installApiMocks } from './apiMocks';

test('draws both configured heads and isolates a missing tool mesh', async ({ page }) => {
  const api = await installApiMocks(page);
  await page.route('**/api/v1/gantry/cub.yaml', route => route.fulfill({ json: {
    filename: 'cub.yaml', config: {
      serial_port: 'OFFLINE', gantry_type: 'genmitsu_4040_pro_max',
      cnc: { factory_z_travel_mm: 80, y_axis_motion: 'head' },
      working_volume: { x_min: 0, x_max: 390, y_min: 0, y_max: 390, z_min: 0, z_max: 70 },
      instruments: {
        camera: { type: 'camera', vendor: 'flir', offset_x: -42, offset_y: 0, depth: 0 },
        asmi: { type: 'asmi', vendor: 'vernier', offset_x: 50, offset_y: 0, depth: 6 },
      },
    },
  } }));
  const models = new Set<string>();
  page.on('response', response => {
    const path = new URL(response.url()).pathname;
    if (response.ok() && path.endsWith('.glb') && response.request().resourceType() === 'fetch') {
      models.add(path.split('/').pop()!);
    }
  });
  await page.goto('/');
  await page.getByLabel('Gantry config', { exact: true }).selectOption('cub.yaml');
  const modes = page.getByRole('group', { name: 'Deck view' });
  await modes.getByRole('button', { name: '3D' }).click();
  await expect(page.getByRole('button', { name: 'Tools', exact: true })).toBeVisible({ timeout: 30000 });
  await expect(page.locator('.polar-deck-caption')).toContainText('FLIR camera');
  await expect(page.locator('.polar-deck-caption')).toContainText('Vernier ASMI');
  expect([...models].some(name => name.startsWith('camera-flir'))).toBe(true);
  expect([...models].some(name => name.startsWith('asmi-vernier'))).toBe(true);
  expect([...models].some(name => name.startsWith('pipette'))).toBe(false);

  await modes.getByRole('button', { name: '2D' }).click();
  await page.route(/camera-flir[^/]*\.glb$/, route => route.fulfill({ status: 404 }));
  await modes.getByRole('button', { name: '3D' }).click();
  await expect(page.locator('.polar-deck')).toContainText(/unavailable.*camera|camera.*unavailable/i);
  await page.getByRole('button', { name: 'Tools', exact: true }).click();
  await expect(page.locator('.polar-deck')).toHaveAttribute('data-state', 'ready');
  expect(api.requests.filter(req => req.method !== 'GET')).toEqual([]);
});
