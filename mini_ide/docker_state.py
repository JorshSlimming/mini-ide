"""Estado y controles de Docker Compose por proyecto para PanelIDE.

Paralelo a mini_ide.runners, misma mecánica:
- Detección: compose.yaml (o docker-compose.yml, ...) en el root.
- Estado local on-demand: `docker compose ps --format json` (sin red).
- Encendido/apagado solo manual (toggle): `up -d` / `stop`, sin sudo.
- Sin polling remoto: el tick de PanelIDE refresca en un hilo aparte
  (ps tarda ~200ms; systemctl is-active del runner es ~10ms y va en
  el loop GTK).

Nota: `ps` sin `-f` refleja el compose por defecto del root
(incluye `docker-compose.override.yml`). Stacks levantados con
`-f` extra pueden verse como PARTIAL aunque estén completos.
Al cerrar un proyecto NO se tocan sus contenedores (a diferencia
del gate de runners): stop es manual vía el botón.
"""
import json
import os
import subprocess

COMPOSE_FILES = ("compose.yaml", "compose.yml",
                 "docker-compose.yaml", "docker-compose.yml")

PS_TIMEOUT = 20
UP_TIMEOUT = 180
STOP_TIMEOUT = 60


def _run(args, cwd=None, timeout=20):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired):
        return None


def find_compose(root):
    """Ruta del compose file en root, o None."""
    for name in COMPOSE_FILES:
        p = os.path.join(root, name)
        if os.path.isfile(p):
            return p
    return None


def resolve(root):
    """Info docker de un proyecto, o {'has_docker': False}."""
    root = os.path.abspath(root)
    compose = find_compose(root)
    if compose is None:
        return {"has_docker": False, "root": root}
    return {"has_docker": True, "root": root, "compose": compose,
            "project": os.path.basename(root)}


def containers(info):
    """[{name, state, status}] del proyecto, o None si falla docker."""
    root = (info or {}).get("root")
    if not root:
        return None
    r = _run(["docker", "compose", "ps", "--format", "json"],
             cwd=root, timeout=PS_TIMEOUT)
    if r is None:
        return None  # docker caído / timeout: estado desconocido
    if r.returncode != 0:
        return []  # compose inválido (ej. env faltante): 0 contenedores
    out = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except ValueError:
            continue
        out.append({"name": c.get("Name", "?"),
                    "state": (c.get("State") or "unknown").lower(),
                    "status": c.get("Status", "")})
    return out


def summarize(cts):
    """(running, total) de una lista de containers()."""
    cts = cts or []
    return (sum(1 for c in cts if c.get("state") == "running"), len(cts))


def state_of(cts):
    """on|partial|off. Definido pero sin contenedores creados = off."""
    running, total = summarize(cts)
    if total > 0 and running >= total:
        return "on"
    if running > 0:
        return "partial"
    return "off"


def presentation(info, cts=None, state=None, compact=False):
    """(state, label, css, tooltip) para el botón docker, como runners.

    cts es la lista de containers(); None significa "sin leer aún"
    (→ wait, salvo override explícito). state fuerza un estado
    ("wait" durante el toggle, "none" sin compose).
    """
    info = info or {}
    if not info.get("has_docker"):
        state = "none"
    elif state == "unknown" or (state is None and cts is None):
        state = "wait"
    elif state is None:
        state = state_of(cts)

    labels = {
        "on": ("● DOCKER ON", "● ON", "docker-on"),
        "off": ("○ DOCKER OFF", "○ OFF", "docker-off"),
        "partial": ("◐ DOCKER PARTIAL", "◐ PARTIAL", "docker-partial"),
        "wait": ("… DOCKER …", "… WAIT", "docker-wait"),
        "none": ("— NO DOCKER", "— NONE", "docker-none"),
    }
    if state not in labels:
        state = "wait"

    running, total = summarize(cts)
    if state == "none":
        root = os.path.basename(info.get("root") or "?")
        tooltip = ("%s has no compose file.\n"
                   "Add compose.yaml (or docker-compose.yml) "
                   "at the project root." % root)
    elif state == "on":
        tooltip = ("%s\n%d/%d running\nClick to stop." % (
            info.get("project", "?"), running, total))
    elif state == "off":
        tooltip = ("%s\nAll stopped.\nClick to start (`up -d`)." % (
            info.get("project", "?")))
    elif state == "partial":
        tooltip = ("%s\n%d/%d running.\nClick to stop all." % (
            info.get("project", "?"), running, total))
    else:
        tooltip = ("Docker status is being checked "
                   "or an operation is in progress.")

    full_label, compact_label, css_class = labels[state]
    return (state, compact_label if compact else full_label,
            css_class, tooltip)


def up(info):
    """`docker compose up -d` en el root. True si returncode 0."""
    r = _run(["docker", "compose", "up", "-d"],
             cwd=info["root"], timeout=UP_TIMEOUT)
    return r is not None and r.returncode == 0


def stop(info):
    """`docker compose stop` en el root. True si returncode 0."""
    r = _run(["docker", "compose", "stop"],
             cwd=info["root"], timeout=STOP_TIMEOUT)
    return r is not None and r.returncode == 0
