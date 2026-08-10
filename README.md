# Mini-IDE

Custom **Python + GTK3** IDE (native, ~83 MB RAM) to replace VS Code in the workflow:
**opencode writes the code, Mini-IDE is used to browse/view files and run opencode**.

## Install as an app

On any Linux machine (debian/ubuntu, GTK3):

```bash
git clone https://github.com/JorshSlimming/mini-ide.git
cd mini-ide
./install.sh
```

The installer copies the script to `~/.local/bin`, creates the **Mini-IDE** menu entry
and the icon. Then:

- Find it in the application menu, or
- right-click a folder > **Open with > Mini-IDE**

## Manual launch

```bash
python3 mini-ide.py /path/to/folder
# or if installed: mini-ide /path/to/folder
```

Multiple instances can be opened (each folder in its own window).

## Features

- File browser with auto-refresh (GFileMonitor): files created by opencode or the terminal appear automatically, also in subfolders
- Double-click opens by type: image, PDF, audio, colored CSV or text (GtkSource with syntax highlighting)
- Editor with tabs, autosave (0.8 s), `Ctrl+S` to save
- Command terminals with T1/T2 tabs (`Ctrl+T` or `+` button), collapsible with the ▾ arrow; selecting text = automatic copy (VS Code style)
- **opencode** terminal embedded in the project; right-click menu with Copy/Paste and the Shift hint for selection
- **Multitasking**: choose 2 or 3 projects in one window, each with its own opencode; with 2+ open files the opencode terminal becomes an extra tab to save space
- Toolbar: copy folder path, open folder in file manager, `+ File` / `+ Folder` creation
- Drop zone above the tree (multitasking): drop files to copy them to the project root
- Opening without a folder: opens the **last project** used; if none, shows the project selector directly
- File management: rename (F2), delete (Del), create in-place with Enter/Esc
- Drag & drop from the system file manager → copies to the destination folder
- Material Icon Theme icons with the exact mappings from the VS Code extension
- VS Code Dark 2026 palette (matching your VS Code theme)

## Shortcuts

| Key | Action |
|---|---|
| Double-click file | Open (by type) |
| Double-click folder | Expand / collapse |
| `F2` | Rename |
| `Del` | Delete (with confirmation) |
| `Ctrl+S` | Save |
| `Ctrl+T` | New command terminal |
| `Ctrl+V` (in terminal) | Paste |
| Enter / Esc | Confirm / cancel creation in the tree |

## Dependencies

- Python 3 + PyGObject (Gtk 3, GtkSource 4, VTE 2.91)
- Optional: Poppler (PDF), GStreamer (audio), Cairo
- opencode binary — resolved from: `MINI_IDE_OPENCODE` env var → `PATH` → `~/.opencode/bin/opencode`
- Material Icon Theme 5.37.0 extension in VS Code (`pkief.material-icon-theme`) for icons (optional, has fallback)

## Tests

Core file/document logic lives in the `mini_ide/` package and is covered by a unit test suite (no display needed):

```bash
python3 -m unittest discover -s tests -v
```

Covers: atomic writes, safe create/rename path validation, project-root containment, recursive-copy protection, binary detection, per-buffer autosave timers and external-change conflict classification.

## Power profiles (optional)

`scripts/limit-cpu.sh` cycles CPU power profiles (max/medium/min) to control
temperature on laptops, and `scripts/limit-cpu-genmon.sh` shows the current
profile in the XFCE panel. See the scripts for usage.

## See also

- [NOTES.md](NOTES.md) — usage notes and planned improvements
