"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");
const {
  buildBackendEnvironment,
  getRuntimePaths,
  hasYamlFiles,
  isBackendUrl,
  startBackend,
  seedConfigs,
  waitForBackend,
} = require("../src/runtime");

test("packaged runtime resolves the install and user data layout", () => {
  const installRoot = path.resolve("test-install", "UrsaLabs", "CubOS");
  const localAppData = path.resolve("test-user", "AppData", "Local");
  const paths = getRuntimePaths({
    executablePath: path.join(installRoot, "desktop", "CubOS.exe"),
    isPackaged: true,
    env: { LOCALAPPDATA: localAppData },
  });

  assert.equal(paths.installRoot, installRoot);
  assert.equal(paths.python, path.join(installRoot, "venv", "Scripts", "python.exe"));
  assert.equal(paths.configDir, path.join(localAppData, "UrsaLabs", "CubOS", "configs"));
});

test("backend environment uses a private dynamic port and bundled frontend", () => {
  const paths = {
    configDir: "C:\\config",
    dataDbPath: "C:\\data\\cubos.db",
    frontendDist: "C:\\CubOS\\operator-web\\dist",
  };
  const env = buildBackendEnvironment(paths, 49152, { PATH: "example" });

  assert.equal(env.CUBOS_HOST, "127.0.0.1");
  assert.equal(env.CUBOS_PORT, "49152");
  assert.equal(env.CUBOS_OPEN_BROWSER, "false");
  assert.equal(env.CUBOS_WEB_DIST, paths.frontendDist);
  assert.equal(env.PATH, "example");
});

test("seed configs are copied only into an empty config directory", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cubos-desktop-test-"));
  const seedConfigDir = path.join(root, "seeds");
  const configDir = path.join(root, "configs");
  fs.mkdirSync(path.join(seedConfigDir, "gantry"), { recursive: true });
  fs.writeFileSync(path.join(seedConfigDir, "gantry", "seed.yaml"), "name: seed\n");

  assert.equal(seedConfigs({ seedConfigDir, configDir }), true);
  assert.equal(hasYamlFiles(configDir), true);
  fs.writeFileSync(path.join(seedConfigDir, "gantry", "second.yaml"), "name: second\n");
  assert.equal(seedConfigs({ seedConfigDir, configDir }), false);
  assert.equal(fs.existsSync(path.join(configDir, "gantry", "second.yaml")), false);
});

test("backend readiness accepts a degraded health response", async () => {
  const child = { exitCode: null };
  const response = await waitForBackend("http://127.0.0.1:49152", { child }, {
    timeoutMs: 100,
    fetchImpl: async () => ({ status: 503 }),
  });

  assert.equal(response.status, 503);
});

test("backend readiness reports an early process exit", async () => {
  await assert.rejects(
    waitForBackend("http://127.0.0.1:49152", { child: { exitCode: 7 } }, { timeoutMs: 100 }),
    /exited during startup with code 7/,
  );
});


test("backend URL checks compare origins rather than prefixes", () => {
  const base = "http://127.0.0.1:49152";
  assert.equal(isBackendUrl(`${base}/api/v1/health`, base), true);
  assert.equal(isBackendUrl(`${base}@example.com/`, base), false);
  assert.equal(isBackendUrl("http://127.0.0.1:4915/", base), false);
  assert.equal(isBackendUrl("https://127.0.0.1:49152/", base), false);
  assert.equal(isBackendUrl("not a URL", base), false);
});

test("backend readiness rejects unrelated HTTP failures", async () => {
  await assert.rejects(
    waitForBackend("http://127.0.0.1:49152", { child: { exitCode: null } }, {
      timeoutMs: 10,
      fetchImpl: async () => ({ status: 404 }),
    }),
    /Health endpoint returned HTTP 404/,
  );
});

test("backend readiness reports termination by signal", async () => {
  await assert.rejects(
    waitForBackend("http://127.0.0.1:49152", { child: { exitCode: null, signalCode: "SIGTERM" } }),
    /SIGTERM/,
  );
});

function mockBackend() {
  const child = new EventEmitter();
  child.exitCode = null;
  child.stdin = new PassThrough();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = () => {
    child.emit("exit", null, "SIGTERM");
    child.emit("close");
  };
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cubos-backend-test-"));
  const backend = startBackend({
    installRoot: root, cubosDir: root, logDir: root, python: "python",
    configDir: root, dataDbPath: path.join(root, "data.db"), frontendDist: root,
  }, 49152, { spawnProcess: () => child });
  return { backend, child };
}

test("spawn errors are retained even before the readiness poll starts", async () => {
  const { backend, child } = mockBackend();
  const error = new Error("spawn python ENOENT");
  child.emit("error", error);
  child.emit("close");
  await assert.rejects(waitForBackend("http://127.0.0.1:49152", backend), error);
  await backend.stop();
});

test("shutdown waits for stream closure and is shared by concurrent callers", async () => {
  const { backend, child } = mockBackend();
  const stopping = backend.stop();
  assert.equal(backend.stop(), stopping);
  child.exitCode = 0;
  child.emit("exit", 0, null);
  child.stdout.write("final output\n");
  child.stdout.end();
  child.stderr.end();
  child.emit("close");
  await stopping;
});

test("shutdown kills an unresponsive backend once the grace period expires", async () => {
  const { backend, child } = mockBackend();
  let killed = false;
  const kill = child.kill;
  child.kill = () => { killed = true; kill(); };
  await backend.stop(1);
  assert.equal(killed, true);
});
