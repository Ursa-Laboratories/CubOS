# Windows installer — fix ASMI default-selection bug + repair-flow gaps

**Context:** Branch `codex/fix-windows-installer-runtime` (commit 97fd53c) moved installs into `{app}\venv` and made godirect an opt-in driver group. Review found one critical Inno Setup bug and several repair-path gaps. All files under `installer/windows/`. Backend tests: `.venv/bin/python -m pytest tests/test_windows_installer.py -q`.

## 1. CRITICAL — ASMI task is not actually selected by default (`Zoo.iss:32-33`)

Inno Setup task hierarchy is **positional**: `Name: "drivers\asmi"` (level 1) becomes a child of the immediately preceding level-0 task — `desktopicon`, which has `Flags: unchecked`. A child can't be selected unless its parent is, so a default wizard run leaves ASMI unselected, `GetDriverGroups` returns `''`, and godirect is never installed — opposite of what README and tests claim. Ticking ASMI also force-selects the desktop shortcut.

**Fix:** flatten the task name: `Name: "asmi"; Description: "ASMI Go Direct driver support (public godirect package, selected by default)"; GroupDescription: "Optional public hardware drivers:"`. In `[Code]`, change `WizardIsTaskSelected('drivers\asmi')` → `WizardIsTaskSelected('asmi')`. Update `tests/test_windows_installer.py:32-35`: assert the `Name: "asmi"` task line exists and lacks `unchecked`, and add an assertion that no task name in the file contains a backslash (guards against positional-parenting regressions).

## 2. MAJOR — repair flow loses driver selection (`Install-Runtime.ps1:96-100`, `Start-Zoo.ps1:62-79,102-106`)

Driver selection is persisted only inside `runtime-installed.txt`, written **after** all pip steps succeed. If install fails partway (Inno `[Run]` ignores nonzero exit codes, step is `runhidden` → silent), the launcher repairs with `-DriverGroups ""`, permanently omits godirect, then writes `DriverGroups=none` so every future repair omits it too.

**Fix:** persist selection separately. In `Install-Runtime.ps1`, immediately after computing `$SelectedDriverGroups` (before any pip call), write it to `Join-Path $InstallDir "driver-groups.txt"` — only when `$DriverGroups` was explicitly passed non-empty (so a repair invocation with empty groups doesn't clobber it). In `Start-Zoo.ps1`, `Get-InstalledDriverGroups` reads `driver-groups.txt` first, falls back to the marker's `DriverGroups=` line. `runtime-installed.txt` stays purely a completion flag.

## 3. MAJOR — `Export-Diagnostics.ps1` not updated for the venv (`Export-Diagnostics.ps1:8,40-47`)

Diagnostics still runs `pip freeze` and the `import zoo, gantry, deck, protocol_engine` check against `{app}\Python\python.exe`; packages now live in `{app}\venv`, so every healthy install produces a diagnostics zip that looks broken.

**Fix:** add `$RuntimePython = Join-Path $InstallDir "venv\Scripts\python.exe"` and use it (fall back to `$Python` with a note in the report if the venv is missing) for `--version`, `pip freeze`, and the import check. Also append `runtime-installed.txt` contents to `runtime.txt` so selected driver groups are visible in diagnostics.

## 4. MAJOR — EAP=Stop + `2>&1` around native pip calls can abort on benign stderr

In PS 5.1, `2>&1` with `$ErrorActionPreference='Stop'` turns the first stderr line of a native command into a terminating `NativeCommandError` even when it exits 0 (pip routinely warns to stderr). `Start-Zoo.ps1:132-140` already guards against this; `Invoke-LoggedNative` (Install-Runtime.ps1:23-34, also in Install-Python.ps1) and `Invoke-LauncherScript` (Start-Zoo.ps1:45-60) do not.

**Fix:** in all three wrappers, wrap the `& $FilePath @Arguments 2>&1 | Tee-Object ...` line with `$prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'; try { ... } finally { $ErrorActionPreference = $prev }`, keeping `$LASTEXITCODE` as the sole failure signal.

## 5. MINOR — stale venv survives reinstall/uninstall

`pip install --no-index --find-links $Wheelhouse --no-deps cubos zoo` is a no-op when the venv already has cubos/zoo (both statically pinned 0.1.0), and the uninstaller never removes runtime-created dirs.

**Fix:** (a) add `--force-reinstall` to the cubos/zoo install line in `Install-Runtime.ps1:92`; (b) add to `Zoo.iss`: `[UninstallDelete]` section with `Type: filesandordirs; Name: "{app}\venv"`, `Type: filesandordirs; Name: "{app}\Python"`, `Type: files; Name: "{app}\runtime-installed.txt"` (plus `driver-groups.txt` from item 2).

## 6. MINOR — sentinel `none` handling + stray godirect pin

- `Install-Runtime.ps1` `$SelectedDriverGroups` pipeline: after `.ToLowerInvariant()`, add `Where-Object { $_ -ne 'none' }` so the marker sentinel is harmless if passed straight through.
- Root `requirements.txt:9` still pins `godirect==1.2.1` as core — remove it or annotate as the optional asmi extra.

## 7. Test hardening

Existing tests are string greps that missed bug #1. Add: a PowerShell syntax-validity test over all `installer/windows/**/*.ps1` using `[System.Management.Automation.Language.Parser]::ParseFile` via `pwsh` (skip with `pytest.mark.skipif` when `pwsh` is not on PATH). Update the .iss assertions per item 1. Keep existing greps as tripwires; drop the brittle `'"--upgrade", "pip"' not in install_runtime` assertion if it conflicts.

**Done when:** all items implemented, `pytest tests/test_windows_installer.py -q` passes, and README (root + `installer/windows/README.md`) still accurately describes behavior (update wording if needed).
