# Mini-IDE — Notes and planned improvements

## What it is
Custom Mini-IDE (Python/GTK, native) created to replace VS Code (~8.4 GB RAM)
in the workflow: **opencode writes the code, the Mini-IDE is used to browse/view files and
run opencode**. Usage: ~83 MB.

**Launch:** `python3 ~/.local/bin/mini-ide.py /path/to/folder`
(multiple instances can be opened — each folder in its own window).

## Shortcuts and usage
- Double-click file → opens (image, PDF, audio, colored CSV or text depending on type)
- Double-click folder → expand/collapse
- `F2` → rename file/folder
- `Del` → delete (with confirmation)
- `Ctrl+S` → save (autosave after 0.8 s)
- `Ctrl+T` → new command terminal (or the `+` button in the T1/T2 tab bar)
- `+ File` / `+ Folder` → create **in-place** in the tree (Enter confirms, Esc cancels)
- `Open folder` (header) → opens the folder in a new instance
- Drag & drop from the system file manager → copies to the destination folder in the tree
- Tree with **auto-refresh** (GFileMonitor): files created by opencode/terminal
  appear on their own, also in subfolders
- Terminals: selecting text = automatic copy to clipboard (VS Code style)
- Icons: Material Icon Theme (Philipp Kief), exact mappings read from
  `dist/material-icons.json` of the extension installed in VS Code
- Visual palette: VS Code Dark Modern (tree #252526, header #3C3C3C, selection #094771)

## Planned improvements
1. **LSP in Mini-IDE** — autocomplete and live diagnostics in the editor
   (useful if code is ever written by hand; opencode doesn't need it).
2. **opencode session monitor** — see how many sessions are open and close
   idle ones with a click (each idle session costs ~600 MB-1 GB).
3. **Lazy-load GStreamer** — initialize audio only when the first audio file
   is opened, instead of at startup (recovers ~5 MB at boot).
4. **Verify Material Icon Theme version** — if the extension updates in
   VS Code, point `THEME_JSON` to the new path (currently fixed at 5.37.0).

## Usage data (measured)
| Component | RAM |
|---|---|
| Mini-IDE (GTK shell) | 83 MB |
| opencode (per session, idle) | ~600 MB - 1 GB |
| VS Code (closed) | 8.4 GB when it was open |
| Dart/Flutter helpers (only if VS Code open) | ~390 MB |
