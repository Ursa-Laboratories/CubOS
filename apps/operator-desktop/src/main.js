"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { app, BrowserWindow, dialog, shell } = require("electron");
const {
  allocateLoopbackPort,
  assertRuntimePaths,
  getRuntimePaths,
  seedConfigs,
  startBackend,
  waitForBackend,
} = require("./runtime");

let mainWindow = null;
let backend = null;
let allowQuit = false;
let stopping = null;

function iconPath() {
  return path.join(__dirname, "..", "assets", "cubos-icon.png");
}

async function stopAndQuit() {
  if (allowQuit) return;
  if (!stopping) {
    stopping = (async () => {
      if (backend) await backend.stop();
      allowQuit = true;
      app.quit();
    })();
  }
  await stopping;
}

function createWindow() {
  const window = new BrowserWindow({
    title: "CubOS",
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: "#0b0f14",
    icon: iconPath(),
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.setMenu(null);
  window.once("ready-to-show", () => window.show());
  window.on("close", (event) => {
    if (!allowQuit) {
      event.preventDefault();
      void stopAndQuit();
    }
  });
  return window;
}

async function launch() {
  const paths = getRuntimePaths({
    executablePath: process.execPath,
    isPackaged: app.isPackaged,
  });
  assertRuntimePaths(paths);
  seedConfigs(paths);

  const port = await allocateLoopbackPort();
  const baseUrl = `http://127.0.0.1:${port}`;
  backend = startBackend(paths, port);
  backend.child.once("exit", (code) => {
    if (stopping) return;
    dialog.showErrorBox(
      "CubOS stopped unexpectedly",
      `The CubOS service exited with code ${String(code)}.\n\nLog: ${backend.logPath}`,
    );
    void stopAndQuit();
  });
  mainWindow = createWindow();
  await mainWindow.loadFile(path.join(__dirname, "..", "assets", "loading.html"));

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(baseUrl)) return { action: "allow" };
    if (url.startsWith("https://") || url.startsWith("http://")) void shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!url.startsWith(baseUrl)) event.preventDefault();
  });

  await waitForBackend(baseUrl, backend.child);
  await mainWindow.loadURL(baseUrl);
  await mainWindow.webContents.executeJavaScript(
    "document.fonts.ready.then(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))))",
  );
  backend.writeLog(`Desktop UI ready: ${await mainWindow.webContents.getTitle()}`);

  const screenshotPath = process.env.CUBOS_DESKTOP_SCREENSHOT;
  if (screenshotPath) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const image = await mainWindow.webContents.capturePage();
    fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
    fs.writeFileSync(screenshotPath, image.toPNG());
    backend.writeLog(`Desktop screenshot saved: ${screenshotPath}`);
  }

  const readyFile = process.env.CUBOS_DESKTOP_READY_FILE;
  if (readyFile) {
    fs.mkdirSync(path.dirname(readyFile), { recursive: true });
    fs.writeFileSync(readyFile, baseUrl, "utf8");
  }

  const autoCloseMs = Number.parseInt(process.env.CUBOS_DESKTOP_AUTO_CLOSE_MS || "", 10);
  if (Number.isFinite(autoCloseMs) && autoCloseMs >= 0) {
    setTimeout(() => mainWindow?.close(), autoCloseMs);
  }
}

const hasInstanceLock = app.requestSingleInstanceLock();
if (!hasInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });

  app.on("before-quit", (event) => {
    if (!allowQuit) {
      event.preventDefault();
      void stopAndQuit();
    }
  });
  app.on("window-all-closed", () => void stopAndQuit());

  app.whenReady().then(launch).catch(async (error) => {
    const message = error instanceof Error ? error.message : String(error);
    const logDetail = backend ? `\n\nLog: ${backend.logPath}` : "";
    dialog.showErrorBox("CubOS could not start", `${message}${logDetail}`);
    await stopAndQuit();
  });
}
