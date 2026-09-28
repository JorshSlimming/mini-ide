# PanelIDE visual specification

## Direction

**Graphite + Teal**. Dark-only, quiet, native-looking and harness-agnostic. The application shell owns the identity; the content running inside a terminal does not.

The design intentionally avoids looking like VS Code. The shell is flatter, borders are sparse, selection is conveyed primarily through a single teal line and subtle surface shifts, and semantic colors are reserved for real states.

## Core palette

| Token | Value | Use |
|---|---|---|
| Root | `#0F1418` | main background |
| Panel | `#1B2226` | sidebars/toolbars |
| Elevated | `#2A343A` | transient/elevated controls |
| Terminal | `#101517` | VTE background |
| Accent | `#00D1B2` | active tab line, focus, selected state |
| Highlight | `#7DD3FC` | sparse secondary highlight |
| Text | `#D9E0E5` | primary text |
| Secondary | `#91A0AA` | labels/metadata |
| Border | `#26343A` | only where separation is necessary |

Canonical values live in `theme/palette.json`.

## Geometry

- Headerbar: **36–38 px**.
- Editor/terminal tabs: **32–34 px**.
- Icon buttons: visual icon **16–18 px**, interactive box **28–32 px**.
- Tree rows: about **28 px**.
- Regular corner radius: **6 px**. Avoid rounded cards inside every pane.
- Pane dividers: **1 px** and low contrast.
- Active tab indicator: **2 px teal bottom line**.
- Multitask gaps should read as workspace separation, not table borders.

## Typography

Use the system UI font. Do **not** ship a custom font dependency. On Debian this keeps the application native and lightweight. Code and VTE should use the system monospace font.

## File icons

Keep the existing Material Icon Theme mappings in the file tree. The SVGs in `ui-icons/` are for **PanelIDE chrome only**: toolbar, panel controls, terminal, viewer controls, session/runner states, etc.

## Harness neutrality

Do not brand the main terminal surface around OMP/OpenCode/another harness. Treat it as a generic `harness` surface. Its own TUI may change completely without requiring a PanelIDE redesign.

## Viewer family

Image, PDF, CSV and audio should share the same visual grammar: one tab strip, one compact viewer toolbar, neutral canvas, quiet controls. CSV column identity should use low-saturation tints or header accents instead of fully saturated cell backgrounds.

## Compact multitask

- With 2+ projects, compress project chrome without hiding PanelIDE-specific meanings: keep icon + compact labels for Files and Terminal, and show the runner's short text state. Universal actions may remain icon-only. Project names remain visible; use ellipsizing only when space requires it.
- Files and Terminal collapse independently; the visible pane fills the bottom strip. Restoring both returns the saved divider position.
- Visual rule: universal action → icon-only is OK. PanelIDE-specific action → icon + label. Important state → color + explicit text.

## Accessibility notes

Keep visible focus states, preserve keyboard shortcuts, and avoid relying on color alone for runner/session state. Small icons may be 16 px visually but should keep a 28–32 px hit target.
