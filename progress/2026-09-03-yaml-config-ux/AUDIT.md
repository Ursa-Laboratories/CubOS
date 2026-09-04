# YAML config UI/UX audit (gantry, deck, protocol)

Date: 2026-09-03. Scope: the Workflow view of the Operator UI (`apps/operator-web`)
and the config routes in `services/api` that back it.

## How it works today

- `App.tsx` owns `gantryFile` / `deckFile` / `protocolFile` and `activeTab` as
  plain React state. Nothing about the workspace is persisted except the theme.
- Each tab has an `ImportFromFile` dropdown (aria-label "Import … config") that
  opens a file. For Deck it really imports: the picked file is copied into
  `cub_deck.yaml` and the tab shows the "imported from" name.
- Saving is a single text box + Save button. Empty box = overwrite the current
  file; typing a name = write a new file and switch to it.
- The API exposes list / get / put per kind. There is no delete and no rename.

## Findings

| # | Severity | Finding |
|---|----------|---------|
| 1 | High | **Refresh loses everything.** Reload lands on the Gantry tab with no file loaded, and the Protocol tab is disabled until Gantry and Deck are re-picked. Every save-then-reload cycle costs three dropdown picks. |
| 2 | High | **No way to delete a config.** No DELETE routes, no UI. Stale protocols and calibration experiments pile up in the dropdown forever. |
| 3 | High | **Discard in one tab throws away edits in the other two.** Each editor's Discard calls `onRefresh`, which is `refreshAll`: it nulls the local deck, gantry and protocol working copies together. Discarding a deck tweak silently drops unsaved protocol steps. |
| 4 | Medium | **Save vs Save-as is ambiguous.** One text box does both. Typing a name that already exists overwrites that file with no warning. `.yml` becomes `foo.yml.yaml`. |
| 5 | Medium | **No "New" for deck or protocol, and gantry's only appears when nothing is loaded.** To start a fresh protocol after loading one you have to remove every step by hand. |
| 6 | Medium | **"Import" is the wrong verb.** For gantry and protocol the dropdown just opens the file. Only deck imports (copies into the working file), and nothing on the tab says where edits actually go. |
| 7 | Medium | **No save confirmation.** After Save the only signal is the filename under the tab; there is no "Saved" acknowledgement and no Cmd/Ctrl+S. |
| 8 | Low | Deck import overwrites `cub_deck.yaml` without asking unless the editor is dirty. A hand-edited working deck can be clobbered by one dropdown pick. |
| 9 | Low | A file deleted or renamed on disk shows "load failed: Config not found" and stays selected. |
| 10 | High (found while testing) | **Concurrent config reads return corrupted YAML.** `yaml_io` shared one module-level ruamel round-trip `YAML` instance across request threads. Loading gantry, deck and protocol at the same time (which restore-on-reload now does) produced 400s such as `instruments: 'camer'` from files that were intact on disk. Reproduced with a 4-thread read loop: 35 of 120 reads corrupted. |

## Action items

Tackled in this branch (`feat/yaml-config-ux`):

1. Persist the active tab and the selected gantry / deck / protocol files per
   config directory in `localStorage`; restore on load; drop a selection whose
   file 404s. (Findings 1, 9)
2. Add `DELETE /api/v1/{deck,gantry,protocol}/{filename}` with safe-filename,
   404, and 409 guards (run active; gantry file currently connected). Wire a
   Delete button with confirm into every tab. (Finding 2)
3. Per-editor discard: Discard only resets that editor's working copy. (3)
4. Replace the import dropdown with a config picker: "Open" semantics, current
   file shown, New and Delete beside it, and a note on the Deck tab saying
   edits go to the working copy. (5, 6)
5. Save bar: explicit "Save" and "Save as…" with overwrite confirmation when
   the new name already exists; accept `.yml`; "Saved <file>" feedback;
   Cmd/Ctrl+S. (4, 7)
6. Build a fresh ruamel codec per read/write in `yaml_io`, with a threaded
   regression test that fails against the old shared instance. (10)

Follow-ups, not in this branch:

- Confirm before deck import overwrites a clean `cub_deck.yaml` (finding 8).
  Left as-is because the working-copy flow is deliberate; worth a one-line
  confirm once the picker copy is settled.
- Rename config files from the UI.
