# PanelIDE

PanelIDE is a native Python/GTK3 workspace for browsing and editing project files, viewing media, and running terminals. The embedded **Harness** terminal is a generic executable-backed shell surface; the application UI does not assume a specific coding agent. GitHub Actions self-hosted runner controls remain an optional, separate feature.

## Install

From the repository checkout on Linux with GTK3:

```bash
./install.sh
```

The installer places the app and runtime assets in `~/.local/share/panelide`, creates the `panelide` launcher in `~/.local/bin`, and installs the desktop entry and hicolor icons. It also retains the optional `limit-cpu.sh` helper. Find **PanelIDE** in the application menu or launch it from a terminal.

## Launch

```bash
python3 panelide.py /path/to/project
# after installation
panelide /path/to/project
```

With no folder argument, PanelIDE restores the saved session when enabled, otherwise opens the most recent project; if there is no saved project, it opens a folder chooser. Multiple windows can be launched independently.

## Harness and configuration

Set `PANELIDE_HARNESS` to the executable path to run in the embedded Harness terminal. For compatibility, PanelIDE also accepts `MINI_IDE_OMP`; if neither variable is set, it looks for `omp` on `PATH` and then `~/.local/bin/omp`.

State is stored under `~/.config/panelide`. On first launch, `session.json` and `recent.json` are copied from `~/.config/mini-ide` only when the corresponding PanelIDE file does not already exist; the old files are left in place. `PANELIDE_CONFIG_DIR`, `PANELIDE_SESSION`, and `PANELIDE_RECENTS` can override the state paths. The legacy `MINI_IDE_SESSION` and `MINI_IDE_RECENTS` variables remain accepted.

## Features

- Auto-refreshing project tree with Material Icon Theme file/folder icons when the VS Code extension is installed; built-in fallback icons otherwise.
- Text editing with GtkSource syntax highlighting, tabs, autosave after 0.8 seconds, and `Ctrl+S`.
- Built-in image preview, CSV/TSV table viewer, PDF viewer, and audio player. PDF and audio support use optional Poppler and GStreamer components.
- Generic embedded Harness terminal plus separate command-terminal tabs. `Ctrl+T` creates a command terminal; selecting terminal text copies it to the clipboard.
- Session restore for projects, open files, terminal count, multitask mode, and collapsed panels.
- Multitask view for multiple projects in one window. Each project retains its own tree, editor, terminals, and harness; the compact project headers use icon controls with tooltips.
- File operations: create files/folders in the tree, rename with `F2`, delete with `Del`, drag files from the file manager to copy, and drag within the tree to move.
- Optional GitHub self-hosted runner status and controls.
- Dark-only Graphite + Teal GTK3 theme, matching GtkSource color scheme, SVG toolbar icons, and PanelIDE application icons. Material file-type icons are unchanged.

## Shortcuts

| Key | Action |
|---|---|
| Double-click file | Open by file type |
| Double-click folder | Expand or collapse |
| `F2` | Rename selected file/folder |
| `Del` | Delete selected file/folder (confirmation required) |
| `Ctrl+S` | Save the current text buffer |
| `Ctrl+T` | Create a command terminal |
| `Ctrl+V` in a terminal | Paste |
| `Enter` / `Esc` while creating in the tree | Confirm / cancel |
| `1`–`9` in multitask view | Focus the corresponding project tree |

## Dependencies

Required: Python 3, PyGObject, GTK3, GtkSource 4, and VTE 2.91. Poppler (PDF) and GStreamer (audio) are optional. The Material Icon Theme VS Code extension is optional and currently detected at version 5.37.0's standard extension path.

## Tests

Run the headless suite with:

```bash
python3 -m pytest -q
```

The suite covers file/document safety, autosave and external-change handling, runner state, multitask layout calculations, and legacy-config migration. GUI startup and GTK rendering require a display.

## Optional CPU profile helper

`~/.local/bin/limit-cpu.sh` can be run manually to control CPU power profiles. The installer does not configure automatic profile changes. See the script for its modes and the security notes before granting elevated permissions.

## Project notes

See [NOTES.md](NOTES.md) for current implementation notes and possible future work. The visual specification and palette are in [DESIGN_SPEC.md](DESIGN_SPEC.md).
