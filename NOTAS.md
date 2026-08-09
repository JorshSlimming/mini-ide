# Mini-IDE — Notas y mejoras futuras

## Qué es
Mini-IDE propio (Python/GTK, nativo) creado para reemplazar VS Code (~8.4 GB RAM)
en el flujo: **opencode escribe el código, el mini-IDE sirve para navegar/ver archivos y
correr opencode**. Consumo: ~83 MB.

**Lanzamiento:** `python3 ~/.local/bin/mini-ide.py /ruta/carpeta`
(se puede abrir más de una instancia — cada carpeta en su propia ventana).

## Atajos y uso
- Doble clic en archivo → abre (imagen, PDF, audio, CSV coloreado o texto según tipo)
- Doble clic en carpeta → expande/colapsa
- `F2` → renombrar archivo/carpeta
- `Supr` → eliminar (con confirmación)
- `Ctrl+S` → guardar (hay autoguardado a los 0.8 s)
- `Ctrl+T` → nueva terminal de comandos (o botón `+` en la barra de pestañas T1/T2)
- `+ Archivo` / `+ Carpeta` → crear **in-place** en el árbol (Enter confirma, Esc cancela)
- `Abrir carpeta` (header) → abre la carpeta en una instancia nueva
- Drag & drop desde el explorador del sistema → copia a la carpeta destino del árbol
- Árbol con **auto-refresh** (GFileMonitor): los archivos creados por opencode/terminal
  aparecen solos, también en subcarpetas
- Terminales: seleccionar texto = copiar automático al portapapeles (estilo VS Code)
- Iconos: Material Icon Theme (Philipp Kief), mapeos exactos leídos de
  `dist/material-icons.json` de la extensión instalada en VS Code
- Paleta visual: VS Code Dark Modern (árbol #252526, header #3C3C3C, selección #094771)

## Mejoras futuras anotadas
1. **LSP en el mini-IDE** — autocompletado y diagnósticos en vivo en el editor
   (útil si algún día se escribe código a mano; opencode no lo necesita).
2. **Monitor de sesiones opencode** — ver cuántas sesiones hay abiertas y cerrar
   las inactivas con un clic (cada sesión idle cuesta ~600 MB-1 GB).
3. **Lazy-load de GStreamer** — inicializar el audio solo al abrir el primer archivo
   de audio, en vez de al arrancar (recupera ~5 MB al inicio).
4. **Verificar versión de Material Icon Theme** — si la extensión se actualiza en
   VS Code, apuntar `THEME_JSON` a la nueva ruta (hoy fijo en 5.37.0).

## Datos de consumo (medidos)
| Componente | RAM |
|---|---|
| mini-IDE (shell GTK) | 83 MB |
| opencode (por sesión, idle) | ~600 MB - 1 GB |
| VS Code (cerrado) | 8.4 GB cuando estaba abierto |
| Dart/Flutter helpers (solo si VS Code abierto) | ~390 MB |
