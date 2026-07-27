"use strict";

const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { spawn } = require("node:child_process");

function getRuntimePaths({ executablePath, isPackaged, env = process.env }) {
  const installRoot = env.CUBOS_INSTALL_DIR
    ? path.resolve(env.CUBOS_INSTALL_DIR)
    : isPackaged
      ? path.dirname(path.dirname(executablePath))
      : path.resolve(__dirname, "..", "..", "..");
  const cubosDir = path.join(installRoot, "app", "CubOS");
  const userRoot = path.join(
    env.LOCALAPPDATA || path.join(env.USERPROFILE || installRoot, "AppData", "Local"),
    "UrsaLabs",
    "CubOS",
  );

  return {
    installRoot,
    cubosDir,
    python: path.join(installRoot, "venv", "Scripts", "python.exe"),
    frontendDist: path.join(cubosDir, "apps", "operator-web", "dist"),
    seedConfigDir: path.join(cubosDir, "services", "api", "configs"),
    configDir: env.CUBOS_CONFIG_DIR || path.join(userRoot, "configs"),
    dataDbPath: env.CUBOS_DATA_DB_PATH || path.join(userRoot, "data", "panda_data.db"),
    logDir: path.join(userRoot, "logs"),
  };
}

function assertRuntimePaths(paths) {
  const required = [
    ["Python runtime", paths.python],
    ["CubOS application", paths.cubosDir],
    ["operator frontend", paths.frontendDist],
  ];
  for (const [label, candidate] of required) {
    if (!fs.existsSync(candidate)) {
      throw new Error(`${label} was not found at ${candidate}`);
    }
  }
}

function hasYamlFiles(root) {
  if (!fs.existsSync(root)) return false;
  const pending = [root];
  while (pending.length > 0) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const candidate = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(candidate);
      if (entry.isFile() && entry.name.toLowerCase().endsWith(".yaml")) return true;
    }
  }
  return false;
}

function seedConfigs(paths) {
  fs.mkdirSync(paths.configDir, { recursive: true });
  if (hasYamlFiles(paths.configDir) || !fs.existsSync(paths.seedConfigDir)) return false;
  fs.cpSync(paths.seedConfigDir, paths.configDir, { recursive: true });
  return true;
}

async function allocateLoopbackPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => {
        if (error) reject(error);
        else resolve(port);
      });
    });
  });
}

function buildBackendEnvironment(paths, port, env = process.env) {
  return {
    ...env,
    CUBOS_CONFIG_DIR: paths.configDir,
    CUBOS_DATA_DB_PATH: paths.dataDbPath,
    CUBOS_HOST: "127.0.0.1",
    CUBOS_PORT: String(port),
    CUBOS_OPEN_BROWSER: "false",
    CUBOS_WEB_DIR: path.dirname(paths.frontendDist),
    CUBOS_WEB_DIST: paths.frontendDist,
    PYTHONUTF8: "1",
  };
}

function timestamp() {
  return new Date().toISOString().replaceAll(":", "").replaceAll("-", "").replace(/\..+/, "");
}

function createLogFile(logDir) {
  fs.mkdirSync(logDir, { recursive: true });
  return path.join(logDir, `cubos-desktop-${timestamp()}.log`);
}

function startBackend(paths, port, { spawnProcess = spawn, env = process.env } = {}) {
  const logPath = createLogFile(paths.logDir);
  const log = fs.createWriteStream(logPath, { flags: "a" });
  log.write(`${new Date().toISOString()} Starting CubOS desktop backend\n`);
  log.write(`${new Date().toISOString()} Install directory: ${paths.installRoot}\n`);
  log.write(`${new Date().toISOString()} Private backend URL: http://127.0.0.1:${port}\n`);

  const child = spawnProcess(paths.python, ["-m", "cubos_api.desktop"], {
    cwd: paths.cubosDir,
    env: buildBackendEnvironment(paths, port, env),
    windowsHide: true,
    stdio: ["pipe", "pipe", "pipe"],
  });
  child.stdout.pipe(log, { end: false });
  child.stderr.pipe(log, { end: false });
  child.once("exit", (code, signal) => {
    log.write(
      `${new Date().toISOString()} Backend exited with code ${String(code)} signal ${String(signal)}\n`,
    );
  });

  let stopped = false;
  return {
    child,
    logPath,
    writeLog(message) {
      log.write(`${new Date().toISOString()} ${message}\n`);
    },
    async stop(timeoutMs = 5000) {
      if (stopped) return;
      stopped = true;
      if (child.exitCode === null && child.stdin.writable) child.stdin.end();
      if (child.exitCode === null) {
        await Promise.race([
          new Promise((resolve) => child.once("exit", resolve)),
          new Promise((resolve) => setTimeout(resolve, timeoutMs)),
        ]);
      }
      if (child.exitCode === null) child.kill();
      log.end();
    },
  };
}

async function waitForBackend(baseUrl, child, { timeoutMs = 45000, fetchImpl = fetch } = {}) {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`CubOS backend exited during startup with code ${child.exitCode}`);
    }
    try {
      const response = await fetchImpl(`${baseUrl}/api/v1/health`, {
        signal: AbortSignal.timeout(1500),
      });
      if (response.status >= 200 && response.status < 600) return response;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  const detail = lastError instanceof Error ? `: ${lastError.message}` : "";
  throw new Error(`CubOS backend did not become ready within ${timeoutMs / 1000} seconds${detail}`);
}

module.exports = {
  allocateLoopbackPort,
  assertRuntimePaths,
  buildBackendEnvironment,
  getRuntimePaths,
  hasYamlFiles,
  seedConfigs,
  startBackend,
  waitForBackend,
};
