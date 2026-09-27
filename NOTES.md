# PanelIDE — Notes

## What it is

PanelIDE is a GTK3 project browser/editor and terminal workspace. Its project UI is independent of the executable hosted in the embedded **Harness** terminal. The shell uses a dark Graphite + Teal theme, compact icon-first controls, and a separate GtkSource color scheme. File/folder icons continue to come from Material Icon Theme when available.

Launch from a checkout with `python3 panelide.py /path/to/project`, or use `panelide /path/to/project` after installing. See `README.md` for dependencies, configuration variables, and legacy-state migration.

## Current behavior

- Project tree updates through GFileMonitor, including nested folders.
- Text tabs autosave after 0.8 seconds; Ctrl+S saves immediately.
- CSV/TSV tables, images, PDFs, and audio use dedicated viewers.
- Multitask view maintains independent project panels and can restore projects, open files, terminal counts, and collapsed-panel state.
- Runner controls inspect/manage configured GitHub Actions self-hosted runners; they are separate from the generic Harness terminal.
- `PANELIDE_HARNESS` selects the embedded executable. The old `MINI_IDE_OMP` setting and `omp` default remain for migration compatibility.

## Possible future work

1. Add optional LSP completion and diagnostics to the GtkSource editor.
2. Initialize GStreamer only when an audio file is opened.
3. Detect Material Icon Theme versions dynamically instead of relying on the installed extension's 5.37.0 path.
