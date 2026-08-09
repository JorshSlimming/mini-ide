# Mini-IDE

Mini-IDE propio en **Python + GTK3** (nativo, ~83 MB de RAM) para reemplazar VS Code en el flujo:
**opencode escribe el código, el mini-IDE sirve para navegar/ver archivos y correr opencode**.

## Instalación como app

En cualquier equipo con Linux (debian/ubuntu, GTK3):

```bash
git clone https://github.com/JorshSlimming/mini-ide.git
cd mini-ide
./install.sh
```

El instalador copia el script a `~/.local/bin`, crea la entrada de menú
**Mini-IDE** y el icono. Luego:

- Búscalo en el menú de aplicaciones, o
- clic derecho sobre una carpeta > **Abrir con > Mini-IDE**

## Lanzamiento manual

```bash
python3 mini-ide.py /ruta/carpeta
# o si ya instalaste: mini-ide /ruta/carpeta
```

Se pueden abrir varias instancias (cada carpeta en su propia ventana).

## Funcionalidades

- Explorador de archivos con auto-refresh (GFileMonitor): lo que crea opencode o la terminal aparece solo, también en subcarpetas
- Doble clic abre según tipo: imagen, PDF, audio, CSV coloreado o texto (GtkSource con resaltado)
- Editor con pestañas, autoguardado (0.8 s), `Ctrl+S` para guardar
- Terminales de comandos con pestañas T1/T2 (`Ctrl+T` o botón `+`); seleccionar texto = copiar automático (estilo VS Code)
- Pestaña con terminal de **opencode** embebido en el proyecto, ocultable con el botón terminal de la barra
- **Multitarea**: hasta 3 proyectos en una ventana, cada uno con su opencode; si hay 2+ archivos abiertos el terminal de opencode pasa a ser una pestaña más para ahorrar espacio
- Al abrir sin carpeta: abre el **último proyecto** usado; si no hay, muestra directamente el selector de proyecto
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
- Binario de opencode — se busca en: variable `OPENCODE` → `PATH` → `~/.opencode/bin/opencode`
- Extensión Material Icon Theme 5.37.0 en VS Code (`pkief.material-icon-theme`) para los iconos (opcional, hay fallback)

## Ver también

- [NOTAS.md](NOTAS.md) — notas de uso y mejoras futuras anotadas
