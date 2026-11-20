import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { chromium } from 'playwright';

const output = process.argv[2];
const base = new URL(process.argv[3] ?? 'http://127.0.0.1:5197/');
const expected = {
  pipettes: ['pipette-sartorius-5ml', 'pipette-opentrons-single', 'pipette-opentrons-multi'],
  'picus-300': ['pipette-sartorius-300', 'pipette-sartorius-multi'],
  mechanics: ['asmi-vernier', 'capper', 'mounted-tool'],
  cappers: ['capper'],
  optics: ['filmetrics-kla', 'uvvis-ccs-thorlabs', 'uv-curing-excelitas'],
  imaging: ['camera-raspberry-pi', 'lighting-ring', 'camera-flir'],
  electrochemistry: ['potentiostat-admiral', 'potentiostat-emstat'],
  raman: ['raman-probe'],
};

const browser = await chromium.launch({
  channel: process.env.PREVIEW_BROWSER_CHANNEL,
  args: ['--enable-webgl', `--use-angle=${process.env.PREVIEW_ANGLE ?? 'swiftshader'}`, '--enable-unsafe-swiftshader'],
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(base.href);
  const scene = page.getByRole('region', { name: '3D deck visualization' });
  const picker = page.getByLabel('Preview setup');
  const fit = scene.getByRole('button', { name: 'Fit', exact: true });
  const tools = scene.getByRole('button', { name: 'Tools', exact: true });
  await fit.waitFor({ timeout: 30_000 });
  const errors = [];
  const requests = [];
  const assets = new Set();
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    if (request.url().includes('/api/v1/')) requests.push(request.method());
  });
  page.on('response', response => {
    if (response.ok()) assets.add(new URL(response.url()).pathname.split('/').at(-1));
  });

  if (output) await mkdir(output, { recursive: true });
  for (const [setup, names] of Object.entries(expected)) {
    assets.clear();
    await page.goto(new URL('?setup=' + setup, base).href);
    await tools.waitFor({ timeout: 35_000 });
    assert.equal(await picker.inputValue(), setup);
    for (const name of ['assembly', ...names]) {
      assert.ok([...assets].some(asset => asset.startsWith(name + '-') && asset.endsWith('.glb')), name);
    }
    if (output) {
      await page.screenshot({ path: join(output, setup + '.png') });
      await tools.click();
      await scene.screenshot({ path: join(output, setup + '-tools.png') });
    }
    console.log(`PASS ${setup} (${names.length} distinct instrument assets)`);
  }

  const aliases = {
    'camera-mounts': 'imaging',
    multichannel: 'picus-300',
  };
  for (const [oldSetup, currentSetup] of Object.entries(aliases)) {
    assets.clear();
    await page.goto(new URL('?setup=' + oldSetup, base).href);
    await tools.waitFor({ timeout: 30_000 });
    assert.equal(await picker.inputValue(), currentSetup);
    assert.ok(![...assets].some(asset => asset.startsWith('camera-usb-')));
  }
  assert.match(await scene.textContent(), /Picus 2 · 1 ch · 300 µL.*Picus 2 · 8 ch · 300 µL/);
  console.log('PASS legacy setup links and dedicated Picus 300 µL comparison');

  await Promise.all([page.waitForURL('**/?setup=optics'), picker.selectOption('optics')]);
  await tools.waitFor({ timeout: 30_000 });
  assert.match(await scene.textContent(), /Filmetrics F20 probe.*Thorlabs CCS probe.*OmniCure light guide/);
  assert.ok(requests.length > 0 && requests.every(method => method === 'GET'));
  assert.deepEqual(errors, []);
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    const response = await page.request.fetch(new URL('/api/v1/gantry/home', base).href, {
      method,
    });
    assert.equal(response.status(), 405);
    assert.equal(response.headers().allow, 'GET, HEAD');
  }
  console.log('PASS selector, multi-head display and read-only API');

  const compact = await browser.newPage({ viewport: { width: 420, height: 850 } });
  await compact.goto(new URL('?setup=imaging', base).href);
  const compactScene = compact.getByRole('region', { name: '3D deck visualization' });
  await compactScene.getByRole('button', { name: 'Tools', exact: true }).waitFor({ timeout: 35_000 });
  const bounds = await compactScene.locator('canvas').boundingBox();
  assert.ok(bounds && bounds.width >= 300 && bounds.x + bounds.width <= 420);
  assert.equal(await compact.getByLabel('Preview setup').inputValue(), 'imaging');
  if (output) await compact.screenshot({ path: join(output, 'compact.png') });
  console.log('PASS compact viewport');
} finally {
  await browser.close();
}
