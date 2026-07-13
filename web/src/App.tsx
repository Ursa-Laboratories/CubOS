import React, { useRef, useState, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import AppLayout from "./components/layout/AppLayout";
import DeckVisualization from "./components/deck/DeckVisualization";
import GantryPositionWidget from "./components/gantry/GantryPositionWidget";
import EditorTabs from "./components/editor/EditorTabs";
import DeckEditor from "./components/editor/DeckEditor";
import GantryEditor from "./components/editor/GantryEditor";
import ProtocolEditor from "./components/editor/ProtocolEditor";
import DataOutputPanel from "./components/data/DataOutputPanel";
import { settingsApi, deckApi, protocolApi, gantryApi } from "./api/client";
import { useDeckConfigs, useDeck, useSaveDeck } from "./hooks/useDeck";
import {
  useGantryPosition,
  useGantryConfigs,
  useGantry,
  useSaveGantry,
  useInstrumentTypes,
  useInstrumentSchemas,
  useInstrumentMethods,
} from "./hooks/useGantryPosition";
import { useProtocolCommands, useProtocolConfigs, useProtocol, useSaveProtocol, useValidateProtocolSetup, useRunStatus } from "./hooks/useProtocol";
import { useExperimentData } from "./hooks/useExperimentData";
import type {
  DeckResponse,
  WellPosition,
  ProtocolValidationResponse,
  ProtocolStep,
  ProtocolConfig,
  GantryResponse,
  WorkingVolume,
  ProtocolRunResponse,
} from "./types";
import type { SettingsResponse } from "./api/client";
import * as theme from "./theme";

function configDirFromSettings(settings: SettingsResponse): string {
  return settings.config_dir ?? "";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function errorHasStatus(error: unknown, status: number): boolean {
  return (
    typeof error === "object"
    && error !== null
    && "status" in error
    && (error as { status?: unknown }).status === status
  );
}

const WORKING_DECK_FILENAME = "panda-deck.yaml";

export default function App() {
  const qc = useQueryClient();
  const [activeView, setActiveView] = useState<"Workflow" | "Results">("Workflow");
  const [activeTab, setActiveTab] = useState("Gantry");
  const [uiTheme, setUiTheme] = useState<"light" | "dark">(() => (document.documentElement.dataset.theme === "light" ? "light" : "dark"));
  const [configDir, setConfigDir] = useState<string | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);

  const [deckFile, setDeckFile] = useState<string | null>(null);
  const [gantryFile, setGantryFile] = useState<string | null>(null);
  const [protocolFile, setProtocolFile] = useState<string | null>(null);
  const [validationResult, setValidationResult] = useState<ProtocolValidationResponse | null>(null);
  const [runResult, setRunResult] = useState<ProtocolRunResponse | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isCancelingRun, setIsCancelingRun] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // Load the local config directory on mount.
  React.useEffect(() => {
    settingsApi.get()
      .then((s) => setConfigDir(configDirFromSettings(s)))
      .catch((err) => console.error("Failed to load settings:", err));
  }, []);

  const handleBrowse = async () => {
    setBrowseLoading(true);
    try {
      const browseResult = await settingsApi.browse();
      const selectedPath = configDirFromSettings(browseResult);
      if (
        selectedPath !== configDir
        && !confirmDiscard(
          unsavedConfigs.length > 0,
          "Discard unsaved config changes and switch config directory?",
        )
      ) {
        return;
      }
      const savedSettings = await settingsApi.update(selectedPath);
      const nextConfigDir = configDirFromSettings(savedSettings);
      setConfigDir(nextConfigDir);
      if (nextConfigDir !== configDir) {
        setDeckFile(null);
        setGantryFile(null);
        setProtocolFile(null);
        setValidationResult(null);
        setImportError(null);
      }
      refreshAll();
    } catch (err) {
      // Distinguish cancellation (no selected path) from a real API failure.
      if (err instanceof Error && err.message !== "cancelled") {
        console.error("Browse/settings update failed:", err);
      }
    } finally {
      setBrowseLoading(false);
    }
  };

  const deckConfigs = useDeckConfigs();
  const deckQuery = useDeck(deckFile);
  const saveDeck = useSaveDeck();

  const gantryConfigs = useGantryConfigs();
  const gantryQuery = useGantry(gantryFile);
  const saveGantry = useSaveGantry();
  const instrumentTypes = useInstrumentTypes();
  const instrumentSchemas = useInstrumentSchemas();
  const instrumentMethods = useInstrumentMethods();

  const protocolCommands = useProtocolCommands();
  const protocolConfigs = useProtocolConfigs();
  const protocolQuery = useProtocol(protocolFile);
  const saveProtocol = useSaveProtocol();
  const validateProtocolSetup = useValidateProtocolSetup();
  const runStatus = useRunStatus();
  const serverRunActive = runStatus.data?.active ?? false;
  const protocolRunActive = isRunning || serverRunActive;
  const gantryPosition = useGantryPosition(true);
  const experimentData = useExperimentData();

  // Local working copies of each editor's edits, kept in App state so
  // they survive tab switches (each editor unmounts on tab-away, which
  // would otherwise discard its useState). Cleared on refresh/load via
  // refreshAll and on save via each editor's mutation onSuccess.
  const [localDeck, setLocalDeck] = useState<DeckResponse | null>(null);
  const [localGantry, setLocalGantry] = useState<GantryResponse | null>(null);
  const [localProtocolSteps, setLocalProtocolSteps] = useState<ProtocolStep[] | null>(null);
  const [localProtocolPositions, setLocalProtocolPositions] = useState<ProtocolConfig["positions"] | undefined>(undefined);
  // Imports always save to WORKING_DECK_FILENAME so the source file
  // isn't touched — but we remember what the user picked so the Deck
  // tab can display that label instead of the working-copy name.
  const [deckImportedFrom, setDeckImportedFrom] = useState<string | null>(null);
  const [previewWells, setPreviewWells] = useState<Record<string, Record<string, WellPosition>>>({});
  const previewTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // Compute well positions via CubOS when user edits a deck locally.
  React.useEffect(() => {
    if (!localDeck) {
      setPreviewWells({});
      return;
    }
    clearTimeout(previewTimerRef.current);
    previewTimerRef.current = setTimeout(async () => {
      const result: Record<string, Record<string, WellPosition>> = {};
      for (const item of localDeck.labware) {
        if (item.config.type === "well_plate") {
	          try {
	            result[item.key] = await deckApi.previewWells(item.config);
	          } catch (err) {
	            // 400 = config still incomplete during editing — expected, skip silently.
	            const is400 = errorHasStatus(err, 400);
	            if (!is400) {
	              console.error("Unexpected well preview error for", item.key, err);
	            }
          }
        }
      }
      setPreviewWells(result);
    }, 300);
    return () => clearTimeout(previewTimerRef.current);
  }, [localDeck]);

  // Clear each local working copy when the user selects a different
  // file — the new server data is the source of truth for a fresh load.
  // deckImportedFrom is cleared too when the user picks a non-import
  // path (dropdown selection etc.); handleImportDeck sets both deckFile
  // and deckImportedFrom in the same render, so this effect preserves
  // the imported label by only nulling it when deckFile drops back to
  // the working-copy filename without a fresh import.
  React.useEffect(() => {
    setLocalDeck(null);
    if (deckFile !== WORKING_DECK_FILENAME) {
      setDeckImportedFrom(null);
    }
  }, [deckFile]);
  React.useEffect(() => {
    setLocalGantry(null);
  }, [gantryFile]);
  React.useEffect(() => {
    setLocalProtocolSteps(null);
    setLocalProtocolPositions(undefined);
    setValidationResult(null);
    setRunResult(null);
    setRunError(null);
  }, [protocolFile]);

  React.useEffect(() => {
    if (!protocolRunActive) {
      setIsCancelingRun(false);
    }
  }, [protocolRunActive]);

	  const displayDeck = useMemo(() => {
	    const base = localDeck ?? deckQuery.data ?? null;
	    if (!base) return null;
	    // Merge server-computed or preview wells into each labware item.
	    return {
	      ...base,
	      labware: base.labware.map((item) => ({
	        ...item,
	        wells: localDeck ? previewWells[item.key] ?? item.wells ?? null : item.wells ?? previewWells[item.key] ?? null,
	      })),
	    };
	  }, [localDeck, deckQuery.data, previewWells]);

  const displayGantry = localGantry ?? gantryQuery.data ?? null;
  const gantryConnected = gantryPosition.data?.connected ?? false;
  const calibrationWarning = gantryPosition.data?.calibration_warning ?? null;
  const workingVolume: WorkingVolume | null = displayGantry?.config.working_volume ?? null;
  const yAxisMotion = displayGantry?.config.cnc?.y_axis_motion ?? "head";
  const machineXRange: [number, number] = workingVolume
    ? [workingVolume.x_min, workingVolume.x_max]
    : [0, 300];
  const machineYRange: [number, number] = workingVolume
    ? [workingVolume.y_min, workingVolume.y_max]
    : [0, 200];

  // Unsaved-edit tracking. Each editor reports edits up into the local
  // working copies above; a non-null/defined working copy means the user
  // has changes that are NOT yet written to disk. handleRunProtocol below
  // posts only filenames, so CubOS re-reads the saved YAML — any unsaved
  // edit would silently run stale config. We surface the dirty state and
  // block Run until the user saves, like saving a document.
  const deckDirty = localDeck !== null;
  const gantryDirty = localGantry !== null;
  const protocolDirty = localProtocolSteps !== null || localProtocolPositions !== undefined;
  const unsavedConfigs = [
    gantryDirty ? "Gantry" : null,
    deckDirty ? "Deck" : null,
    protocolDirty ? "Protocol" : null,
  ].filter((name): name is string => name !== null);

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["deck"] });
    qc.invalidateQueries({ queryKey: ["gantry"] });
    qc.invalidateQueries({ queryKey: ["protocol"] });
    qc.invalidateQueries({ queryKey: ["data"] });
    setLocalDeck(null);
    setLocalGantry(null);
    setLocalProtocolSteps(null);
    setLocalProtocolPositions(undefined);
    setDeckImportedFrom(null);
  };

  // Warn before the tab/window closes while any editor has unsaved edits —
  // Run Protocol already blocks on this in-app, but a hard reload/close
  // would otherwise silently drop the edits with no confirmation at all.
  React.useEffect(() => {
    if (unsavedConfigs.length === 0) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [unsavedConfigs.length]);

  // Guard for switching away from a dirty editor via its file picker: only
  // prompts when that specific tab actually has unsaved edits, so normal
  // (non-dirty) selection and the editors' own post-save onSelectFile
  // bookkeeping calls are never intercepted.
  const confirmDiscard = (dirty: boolean, message: string): boolean => !dirty || window.confirm(message);

  const handleImportGantry = (filename: string) => {
    if (!confirmDiscard(gantryDirty, "Discard unsaved gantry changes?")) return;
    setGantryFile(filename);
  };

  const handleImportProtocol = (filename: string) => {
    if (!confirmDiscard(protocolDirty, "Discard unsaved protocol changes?")) return;
    setProtocolFile(filename);
  };

  const handleImportDeck = async (filename: string) => {
    if (!confirmDiscard(
      deckDirty,
      `Discard unsaved deck changes and overwrite ${WORKING_DECK_FILENAME} with "${filename}"?`,
    )) return;
    setImportError(null);
    try {
      const importedDeck = await deckApi.get(filename);
      const labware = Object.fromEntries(
        importedDeck.labware.map((item) => [item.key, structuredClone(item.config)]),
      );
      await saveDeck.mutateAsync({
        filename: WORKING_DECK_FILENAME,
        body: { labware },
      });
      setDeckFile(WORKING_DECK_FILENAME);
      setDeckImportedFrom(filename);
      setLocalDeck(null);
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleRunProtocol = async () => {
    if (!gantryFile || !deckFile || !protocolFile) return;
    if (unsavedConfigs.length > 0) {
      // Defensive gate behind the disabled Run button: never run stale
      // saved config when the user has unsaved edits in any tab.
      setRunResult(null);
      setRunError(
        `Save your changes to ${unsavedConfigs.join(", ")} before running — `
          + "Run Protocol uses the saved files, not your unsaved edits.",
      );
      return;
    }
    if (!gantryConnected) {
      setRunResult(null);
      setRunError("Connect gantry before running a protocol.");
      return;
    }
    if (calibrationWarning) {
      setRunResult(null);
      setRunError(calibrationWarning);
      return;
    }
    setIsRunning(true);
    setIsCancelingRun(false);
    setRunResult(null);
    setRunError(null);
    qc.setQueryData(["protocol", "run-status"], { active: true, protocol_file: protocolFile });
    try {
      const result = await protocolApi.run({
        gantry_file: gantryFile,
        deck_file: deckFile,
        protocol_file: protocolFile,
      });
      setRunResult(result);
      qc.invalidateQueries({ queryKey: ["data", "campaigns"] });
    } catch (err: unknown) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsRunning(false);
      setIsCancelingRun(false);
      qc.invalidateQueries({ queryKey: ["protocol", "run-status"] });
    }
  };

  const handleCancelRun = async () => {
    if (!protocolRunActive || isCancelingRun) return;
    setIsCancelingRun(true);
    setRunError(null);
    try {
      const result = await protocolApi.cancelRun();
      setRunError(result.warning ? `Protocol cancellation requested: ${result.warning}` : "Protocol cancellation requested.");
    } catch (err: unknown) {
      setRunError(`Cancel failed: ${err instanceof Error ? err.message : String(err)}`);
      setIsCancelingRun(false);
    }
  };

  const toggleTheme = () => {
    setUiTheme((current) => {
      const next = current === "dark" ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try {
        localStorage.setItem("zoo-theme", next);
      } catch {
        // Ignore unavailable storage.
      }
      return next;
    });
  };

  const headerBar = (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
        <div style={brandMarkStyle} aria-hidden="true">
          🐼
        </div>
        <div style={{ lineHeight: 1.25 }}>
          <h1 style={brandTitleStyle}>Zoo</h1>
          <p style={brandTaglineStyle}>An online pen for managing Pandas</p>
        </div>
      </div>
      <div style={viewToggleStyle} aria-label="Workspace view">
        {(["Workflow", "Results"] as const).map((view) => (
          <button
            key={view}
            type="button"
            onClick={() => setActiveView(view)}
            style={{
              ...viewToggleButtonStyle,
              background: activeView === view ? theme.chrome.segmentActiveBg : "transparent",
              color: activeView === view ? theme.color.ink : theme.color.textMuted,
              boxShadow: activeView === view ? theme.chrome.segmentActiveShadow : "none",
            }}
          >
            {view}
          </button>
        ))}
      </div>
      <div style={{ flex: "1 1 auto" }} />
      {protocolRunActive && (
        <div className="zoo-pulse" style={runStatusBannerStyle} role="status">
          <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
            <span style={{ whiteSpace: "nowrap" }}>● Protocol running…</span>
            {runError && (
              <span style={runStatusWarningStyle} title={runError}>{runError}</span>
            )}
          </div>
          <button
            type="button"
            onClick={handleCancelRun}
            disabled={isCancelingRun}
            style={headerCancelButtonStyle}
          >
            {isCancelingRun ? "Cancelling..." : "Cancel"}
          </button>
        </div>
      )}
      <button
        type="button"
        aria-label="Toggle theme"
        title="Toggle light/dark theme"
        onClick={toggleTheme}
        style={themeToggleStyle}
      >
        {uiTheme === "dark" ? "☀" : "☾"}
      </button>
      <label style={headerFieldStyle}>
        <span style={headerFieldLabelStyle}>Last Campaign</span>
        <input
          type="text"
          value={runResult ? `#${runResult.campaign_id}` : ""}
          readOnly
          placeholder="Created after run"
          style={{
            ...headerInputStyle,
            width: 130,
            color: runResult ? theme.color.ink : theme.color.textFaint,
          }}
        />
      </label>
      <label style={headerFieldStyle}>
        <span style={headerFieldLabelStyle}>Config Directory</span>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input
            type="text"
            value={configDir ?? ""}
            readOnly
            placeholder="Not set"
            title={configDir ?? undefined}
            style={{
              ...headerInputStyle,
              ...theme.mono,
              width: 220,
              fontSize: 11.5,
              textOverflow: "ellipsis",
              color: configDir ? theme.color.textSecondary : theme.color.textFaint,
            }}
          />
          <button onClick={handleBrowse} disabled={browseLoading} style={browseButtonStyle}>
            {browseLoading ? "..." : "Browse"}
          </button>
        </div>
      </label>
    </>
  );

  const left = (
    <div>
      {activeView === "Workflow" && (
        <>
          <EditorTabs
          activeTab={activeTab}
          onTabChange={setActiveTab}
          dirtyTabs={unsavedConfigs}
          disabledTabs={!deckQuery.data || !gantryQuery.data ? ["Protocol"] : []}
          disabledMessage={(() => {
            const missing = [
              !gantryQuery.data && "Gantry",
              !deckQuery.data && "Deck",
            ].filter(Boolean);
            if (missing.length === 0) return null;
            return `Please load ${missing.join(", ")} config${missing.length > 1 ? "s" : ""} first.`;
          })()}
          loadedFilenames={{
            // Only show the filename once the fetch actually succeeded —
            // a failed or pending load leaves the tab with just its
            // section label, so the user isn't misled into thinking a
            // broken file was loaded.
            // Deck is special: imports get copied into WORKING_DECK_FILENAME
            // so the source file isn't touched; show the user-facing
            // "imported from" label instead of the working-copy name.
            Gantry: gantryQuery.data?.filename ?? null,
            Deck: deckImportedFrom ?? deckQuery.data?.filename ?? null,
            Protocol: protocolQuery.data?.filename ?? null,
          }}
        />
          {activeTab === "Deck" && (
        <>
          {importError && (
            <div style={importErrorStyle}>Import failed: {importError}</div>
          )}
          {deckQuery.isError && deckFile && (
            <div style={importErrorStyle}>Deck load failed: {errorMessage(deckQuery.error)}</div>
          )}
          <DeckEditor
            key={deckQuery.data ? `loaded:${deckQuery.data.filename}` : `selected:${deckFile ?? "none"}`}
            configs={deckConfigs.data ?? []}
            selectedFile={deckFile}
            onSelectFile={setDeckFile}
            onImportFile={handleImportDeck}
            deck={localDeck ?? deckQuery.data ?? null}
            baseline={deckQuery.data ?? null}
            dirty={deckDirty}
            onSave={async (filename, body) => {
              await saveDeck.mutateAsync({ filename, body });
              setLocalDeck(null);
            }}
            onLocalChange={setLocalDeck}
            onRefresh={refreshAll}
          />
        </>
          )}
          {activeTab === "Gantry" && (
        <>
          {gantryQuery.isError && gantryFile && (
            <div style={importErrorStyle}>Gantry load failed: {errorMessage(gantryQuery.error)}</div>
          )}
          <GantryEditor
            key={gantryQuery.data ? `loaded:${gantryQuery.data.filename}` : `selected:${gantryFile ?? "none"}`}
            configs={gantryConfigs.data ?? []}
            selectedFile={gantryFile}
            onSelectFile={setGantryFile}
            onImportFile={handleImportGantry}
            gantry={localGantry ?? gantryQuery.data ?? null}
            baseline={gantryQuery.data ?? null}
            instrumentTypes={instrumentTypes.data ?? []}
            instrumentSchemas={instrumentSchemas.data ?? {}}
            dirty={gantryDirty}
            onSave={async (filename, body) => {
              await saveGantry.mutateAsync({ filename, body });
              setLocalGantry(null);
            }}
            onLocalChange={setLocalGantry}
            onRefresh={refreshAll}
          />
        </>
          )}
          {activeTab === "Protocol" && deckQuery.data && gantryQuery.data && (
        <>
          {protocolQuery.isError && protocolFile && (
            <div style={importErrorStyle}>Protocol load failed: {errorMessage(protocolQuery.error)}</div>
          )}
          <ProtocolEditor
            key={protocolQuery.data ? `loaded:${protocolQuery.data.filename}` : `selected:${protocolFile ?? "none"}`}
            configs={protocolConfigs.data ?? []}
            selectedFile={protocolFile}
            onSelectFile={setProtocolFile}
            onImportFile={handleImportProtocol}
            commands={protocolCommands.data ?? []}
            deck={(displayDeck ?? deckQuery.data)!}
            gantry={(displayGantry ?? gantryQuery.data)!}
            instrumentMethods={instrumentMethods.data ?? {}}
            steps={localProtocolSteps ?? protocolQuery.data?.steps ?? null}
            positions={localProtocolPositions !== undefined ? localProtocolPositions : protocolQuery.data?.positions ?? null}
            baseline={protocolQuery.data ?? null}
            onSave={async (filename, body) => {
              await saveProtocol.mutateAsync({ filename, body });
              setLocalProtocolSteps(null);
              setLocalProtocolPositions(undefined);
            }}
            onLocalChange={(steps) => {
              setLocalProtocolSteps(steps);
              setValidationResult(null);
            }}
            onPositionsChange={(positions) => {
              setLocalProtocolPositions(positions);
              setValidationResult(null);
            }}
            onValidate={() => {
              if (!gantryFile || !deckFile || !protocolFile) {
                setValidationResult({
                  valid: false,
                  errors: ["Select gantry, deck, and protocol files before setup validation."],
                });
                return;
              }
              if (unsavedConfigs.length > 0) {
                setValidationResult({
                  valid: false,
                  errors: ["Save your changes first — Validate checks the saved files."],
                });
                return;
              }
              validateProtocolSetup.mutate({
                gantry_file: gantryFile,
                deck_file: deckFile,
                protocol_file: protocolFile,
              }, {
                onSuccess: (res) => setValidationResult(res),
                onError: (err) => setValidationResult({
                  valid: false,
                  errors: [String(err instanceof Error ? err.message : err)],
                }),
              });
            }}
            validationErrors={validationResult?.errors ?? null}
            isValidating={validateProtocolSetup.isPending}
            onRefresh={refreshAll}
            onRun={handleRunProtocol}
            onCancelRun={handleCancelRun}
            unsavedConfigs={unsavedConfigs}
            canRun={gantryConnected && !calibrationWarning}
            runDisabledReason={calibrationWarning}
            isRunning={protocolRunActive}
            isCancelingRun={isCancelingRun}
            runResult={runResult}
            runError={runError}
          />
        </>
          )}
        </>
      )}
      {activeView === "Results" && (
        <DataOutputPanel
          campaigns={experimentData.data ?? []}
          isLoading={experimentData.isLoading}
          error={experimentData.error}
          onRefresh={() => experimentData.refetch()}
        />
      )}
    </div>
  );

  const topRight = (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <h3 style={{ ...theme.panelTitle, margin: "0 0 10px", flex: "0 0 auto" }}>Deck Visualization</h3>
      <div style={deckVisualizationFrameStyle}>
        <DeckVisualization
          deck={displayDeck}
          instruments={displayGantry?.config.instruments ?? null}
          gantryPosition={gantryPosition.data ?? null}
          machineXRange={machineXRange}
          machineYRange={machineYRange}
          yAxisMotion={yAxisMotion}
        />
      </div>
    </div>
  );

  const bottomRight = (
    <GantryPositionWidget
      position={gantryPosition.data ?? null}
      workingVolume={workingVolume}
      gantryFile={displayGantry ? gantryFile : null}
      gantry={displayGantry}
      isRunning={protocolRunActive}
      onSaveCalibrated={async (filename, body) => {
        const previousGantryFile = gantryFile;
        const saved = await saveGantry.mutateAsync({ filename, body });
        setGantryFile(saved.filename);
        setLocalGantry(null);
        if (previousGantryFile && saved.filename !== previousGantryFile) {
          await gantryApi.disconnect();
          await gantryApi.connect(saved.filename);
        }
      }}
    />
  );

  return <AppLayout header={headerBar} left={left} topRight={topRight} bottomRight={bottomRight} />;
}

const brandMarkStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: 32,
  height: 32,
  borderRadius: 9,
  background: theme.color.accentTint,
  border: `1px solid ${theme.color.accentTintBorder}`,
  boxShadow: theme.chrome.brandGlow,
  fontSize: 17,
  flex: "0 0 auto",
};

const brandTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 15,
  fontWeight: 650,
  letterSpacing: "-0.02em",
  color: theme.color.ink,
};

const brandTaglineStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 11,
  color: theme.color.textFaint,
  whiteSpace: "nowrap",
};

const headerFieldStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 2,
};

const headerFieldLabelStyle: React.CSSProperties = {
  ...theme.sectionLabel,
  fontSize: 10,
};

const headerInputStyle: React.CSSProperties = {
  ...theme.input,
  padding: "3px 8px",
  fontSize: 12,
  background: theme.color.surfaceMuted,
};

const themeToggleStyle: React.CSSProperties = {
  background: "transparent",
  border: `1px solid ${theme.color.borderStrong}`,
  borderRadius: 999,
  color: theme.color.textMuted,
  fontSize: 14,
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  width: 30,
  height: 30,
};

const importErrorStyle: React.CSSProperties = {
  ...theme.notice.error,
  marginBottom: 10,
};

const browseButtonStyle: React.CSSProperties = {
  ...theme.btn.secondary,
  ...theme.btnSmall,
};

const runStatusBannerStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  padding: "5px 12px",
  borderRadius: 999,
  border: `1px solid ${theme.color.warningBorder}`,
  background: theme.color.warningBg,
  color: theme.color.warningText,
  fontSize: 12,
  fontWeight: 600,
  maxWidth: 420,
};

const headerCancelButtonStyle: React.CSSProperties = {
  ...theme.btn.danger,
  ...theme.btnSmall,
  borderRadius: 999,
};

const runStatusWarningStyle: React.CSSProperties = {
  color: theme.color.dangerText,
  fontWeight: 500,
  lineHeight: 1.35,
  maxWidth: 260,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const viewToggleStyle: React.CSSProperties = {
  display: "inline-flex",
  gap: 2,
  padding: 3,
  borderRadius: 9,
  background: theme.color.surfaceSunken,
};

const viewToggleButtonStyle: React.CSSProperties = {
  border: "none",
  borderRadius: 7,
  padding: "5px 16px",
  fontSize: 12.5,
  fontWeight: 600,
  cursor: "pointer",
};

const deckVisualizationFrameStyle: React.CSSProperties = {
  flex: "0 1 auto",
  minHeight: 240,
  maxHeight: "100%",
  aspectRatio: "600 / 420",
  width: "100%",
};
