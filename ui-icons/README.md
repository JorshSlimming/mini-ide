# UI icon guide

All icons here are intentionally simple 24×24 SVGs designed for the PanelIDE shell.

## Rules

- File/folder type icons in the tree remain the existing Material Icon Theme assets.
- Normal chrome uses muted neutral icons.
- Teal is for selected/active state, not decoration everywhere.
- Green/amber/red are only semantic status colors.
- Prefer 16–18 px rendered icon size inside a 28–32 px button target.
- Every icon-only button should have a tooltip.

## Included neutral icons

`folder-open`, `multitask`, `session`, `files`, `files-hidden`, `runner`, `terminal`, `plus`, `close`, `copy`, `menu`, `more`, `search`, `preview`, `play`, `stop`, `mute`, `volume`, `previous`, `next`, `zoom-in`, `zoom-out`, `fit`, `save`, `trash`, `new-file`, `new-folder`, `chevron-up`, `chevron-down`, `sidebar`, `panel-bottom`, `grid`.

## Included semantic icons

`session-on`, `runner-on`, `runner-busy`, `runner-off`, `active-dot`.

The SVGs are source assets; you can load them directly with `GdkPixbuf` or install them into an icon theme directory and reference them by name.
