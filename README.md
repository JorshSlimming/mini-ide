# Mini-IDE

Mini-IDE propio en **Python + GTK3** (nativo, ~83 MB de RAM) para reemplazar VS Code en el flujo:
**opencode escribe el código, el mini-IDE sirve para navegar/ver archivos y correr opencode**.

## Lanzamiento

```bash
python3 mini-ide.py /ruta/carpeta
```

Se pueden abrir varias instancias (cada carpeta en su propia ventana).

## Funcionalidades

- Explorador de archivos con auto-refresh (GFileMonitor): lo que crea opencode o la terminal aparece solo, también en subcarpetas
- Doble clic abre según tipo: imagen, PDF, audio, CSV coloreado o texto (GtkSource con resaltado)
- Editor con pestañas, autoguardado (0.8 s), `Ctrl+S` para guardar
- Terminales de comandos con pestañas T1/T2 (`Ctrl+T` o botón `+`); seleccionar texto = copiar automático (estilo VS Code)
- Pestaña con terminal de **opencode** embebido en el proyecto
- **Multitarea**: hasta 3 proyectos en una ventana, cada uno con su opencode
- Gestión de archivos: renombrar (F2), eliminar (Supr), crear `+ Archivo` / `+ Carpeta` in-place en el árbol
- Drag & drop del explorador del sistema → copia a la carpeta destino
- Iconos Material Icon Theme con los mapeos exactos de la extensión de VS Code
- Paleta visual VS Code Dark Modern

## Atajos

| Tecla | Acción |
|---|---|
| Doble clic archivo | Abrir (según tipo) |
| Doble clic carpeta | Expandir / colapsar |
| `F2` | Renombrar |
| `Supr` | Eliminar (con confirmación) |
| `Ctrl+S` | Guardar |
| `Ctrl+T` | Nueva terminal de comandos |
| Enter / Esc | Confirmar / cancelar creación en el árbol |

## Dependencias

- Python 3 + PyGObject (Gtk 3, GtkSource 4, VTE 2.91)
- Opcional: Poppler (PDF), GStreamer (audio), Cairo
- Binario de opencode en `~/.opencode/bin/opencode`
- Extensión Material Icon Theme 5.37.0 en VS Code (`pkief.material-icon-theme`) para los iconos

## Ver también

- [NOTAS.md](NOTAS.md) — notas de uso y mejoras futuras anotadas
