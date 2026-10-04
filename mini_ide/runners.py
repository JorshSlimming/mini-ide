"""GitHub self-hosted runner status and controls integrated with PanelIDE.

- Descubrimiento dinámico por convención: basename de la carpeta del
  proyecto == nombre del repo; se busca en ~/actions-runners/*/.runner
  (legacy: ~/actions-runner*/.runner) por gitHubUrl + agentName.
  Casos raros van en MAP_OVERRIDE.
- Sin polling: el estado se consulta on-demand (eventos, click, hover) y
  con un refresh local barato (systemctl is-active, sin red).
- Encendido/apagado solo manual (toggle) o vía script ~/.local/bin/runners.
- Las units son user-units (systemctl --user): no requieren sudo.
"""
import json
import os
import subprocess
import threading
import time


HOME = os.path.expanduser("~")
USER_SYSTEMD = os.path.join(HOME, ".config", "systemd", "user")
RUNNERS_BIN = os.path.join(HOME, ".local", "bin", "runners")
GH_TIMEOUT = 12

# basename carpeta local -> basename repo (solo excepciones; lo normal es 1:1)
MAP_OVERRIDE = {}

# nombre corto CLI -> repo (para `runners up <corto>`)
SHORT_ALIAS = {"api": "product-api", "web": "product-web",
               "polybot": "autonomous-polybot", "urway": "urway-app",
               "lab": "product-lab"}


def _run(args, timeout=20):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def runner_dirs():
    out = []
    try:
        names = os.listdir(HOME)
    except OSError:
        names = []
    for n in sorted(names):
        d = os.path.join(HOME, n)
        if (n.startswith("actions-runner")
                and not os.path.islink(d)  # compat link -> contado abajo
                and os.path.isfile(os.path.join(d, ".runner"))):
            out.append(d)
    base = os.path.join(HOME, "actions-runners")
    try:
        sub = os.listdir(base)
    except OSError:
        return out
    for n in sorted(sub):
        d = os.path.join(base, n)
        if os.path.isfile(os.path.join(d, ".runner")):
            out.append(d)
    return out


def runner_meta(rdir):
    """(org, repo, agent) desde .runner (con BOM utf-8-sig)."""
    try:
        with open(os.path.join(rdir, ".runner"),
                  encoding="utf-8-sig") as f:
            j = json.load(f)
        url = (j.get("gitHubUrl") or "").rstrip("/")
        parts = url.split("/") if url else []
        org = parts[-2] if len(parts) >= 2 else "?"
        repo = parts[-1] if len(parts) >= 1 else "?"
        return org, repo, j.get("agentName") or "?"
    except (OSError, ValueError):
        return None


def unit_name(org, repo, agent):
    return "actions.runner.%s-%s.%s.service" % (org, repo, agent)


def discover():
    """{repo: {dir, org, agent, unit, installed}} para todos los runners."""
    found = {}
    for d in runner_dirs():
        meta = runner_meta(d)
        if not meta:
            continue
        org, repo, agent = meta
        u = unit_name(org, repo, agent)
        found[repo] = {"dir": d, "org": org, "repo": repo, "agent": agent,
                       "unit": u,
                       "installed": os.path.isfile(
                           os.path.join(USER_SYSTEMD, u))}
    return found


def resolve(root):
    """Info del runner para una carpeta de proyecto, o {'has_runner': False}."""
    base = os.path.basename(os.path.abspath(root))
    repo = MAP_OVERRIDE.get(base, base)
    info = discover().get(repo)
    if info is None:
        return {"has_runner": False, "repo": repo, "root": root}
    info = dict(info)
    info["has_runner"] = True
    info["root"] = root
    return info


def local_state(unit):
    """active|inactive|failed|... (solo systemctl local, sin red)."""
    r = _run(["systemctl", "--user", "is-active", unit], timeout=10)
    if r is None or r.returncode not in (0, 3):
        return "unknown"
    return r.stdout.strip() or "unknown"


def remote_state(org, repo, agent):
    """(online, busy) según GitHub API, o None si falla (sin red, etc)."""
    r = _run(["gh", "api", "repos/%s/%s/actions/runners" % (org, repo),
              "--jq", ".runners[] | [.name,.status,.busy] | @tsv"],
             timeout=GH_TIMEOUT)
    if r is None or r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[0] == agent:
            return (parts[1] == "online", parts[2] == "true")
    return None


def ensure_installed(info):
    """Instala la user-unit si falta (runsvc.sh o run.sh según versión)."""
    if info.get("installed"):
        return True
    rdir, org, repo, agent = (info["dir"], info["org"], info["repo"],
                              info["agent"])
    unit = info["unit"]
    if os.path.isfile(os.path.join(rdir, "runsvc.sh")):
        body = ("[Service]\nExecStart=%s/runsvc.sh\n"
                "WorkingDirectory=%s\nKillMode=process\n"
                "KillSignal=SIGTERM\nTimeoutStopSec=5min\n") % (rdir, rdir)
    else:  # runners viejos sin runsvc.sh
        body = ("[Service]\nType=simple\nWorkingDirectory=%s\n"
                "ExecStart=%s/run.sh\nRestart=always\n"
                "RestartSec=5\n") % (rdir, rdir)
    text = ("[Unit]\nDescription=GitHub Actions Runner "
            "(%s-%s.%s)\nAfter=network-online.target\n\n%s\n"
            "[Install]\nWantedBy=default.target\n") % (org, repo, agent,
                                                       body)
    try:
        os.makedirs(USER_SYSTEMD, exist_ok=True)
        with open(os.path.join(USER_SYSTEMD, unit), "w") as f:
            f.write(text)
    except OSError:
        return False
    info["installed"] = True
    r = _run(["systemctl", "--user", "daemon-reload"], timeout=20)
    return r is not None and r.returncode == 0


def start_unit(unit):
    r = _run(["systemctl", "--user", "start", unit], timeout=30)
    return r is not None and r.returncode == 0


def stop_unit(unit):
    r = _run(["systemctl", "--user", "stop", unit], timeout=60)
    return r is not None and r.returncode == 0


def start_async(info, on_done=None):
    """Prende en background (no bloquea GTK)."""
    def _job():
        ok = ensure_installed(info) and start_unit(info["unit"])
        if on_done is not None:
            on_done(ok)

    threading.Thread(target=_job, daemon=True).start()


def wait_inactive(unit, timeout=40, poll=1.0, cancelled=None):
    """Espera a que la unit quede inactive/failed. Para gates de cierre."""
    end = time.time() + timeout
    while time.time() < end:
        if cancelled is not None and cancelled():
            return False
        if local_state(unit) in ("inactive", "failed", "unknown"):
            return True
        time.sleep(poll)
    return local_state(unit) in ("inactive", "failed")


def wait_not_busy(org, repo, agent, poll=10.0, cancelled=None):
    """Espera a que el runner deje busy. None si se cancela/falla."""
    while True:
        if cancelled is not None and cancelled():
            return None
        st = remote_state(org, repo, agent)
        if st is None:
            return None
        _, busy = st
        if not busy:
            return True
        time.sleep(poll)


def presentation(info, local=None, state=None, compact=False):
    """Return state, visible label, CSS class, and tooltip for a runner.

    Local state is read without network access. The UI may pass a resolved
    state such as ``busy`` or ``wait`` when it has fresher information.
    """
    info = info or {}
    if not info.get("has_runner"):
        state = "none"
    elif state is None:
        if local is None:
            local = local_state(info.get("unit", ""))
        if local == "active":
            state = "on"
        elif local in ("inactive", "failed"):
            state = "off"
        else:
            state = "wait"

    labels = {
        "on": ("● RUNNER ON", "● ON", "runner-on"),
        "off": ("○ RUNNER OFF", "○ OFF", "runner-off"),
        "busy": ("◐ RUNNER BUSY", "◐ BUSY", "runner-busy"),
        "wait": ("… RUNNER …", "… WAIT", "runner-wait"),
        "none": ("— NO RUNNER", "— NONE", "runner-none"),
    }
    if state not in labels:
        state = "wait"

    if state == "none":
        root = os.path.basename(info.get("root") or "?")
        tooltip = ("%s has no configured runner.\n"
                   "Run ./config.sh from a ~/actions-runners/<name> folder, "
                   "then run `runners rescan`." % root)
    elif state == "on":
        tooltip = "%s\n%s\nClick to turn off." % (
            info.get("repo", "?"), info.get("unit", "?"))
    elif state == "off":
        tooltip = "%s\n%s\nClick to turn on." % (
            info.get("repo", "?"), info.get("unit", "?"))
    elif state == "busy":
        tooltip = ("%s: executing a job.\n"
                   "Click to stop it (confirmation required)."
                   % info.get("repo", "?"))
    else:
        tooltip = "Runner status is being checked or an operation is in progress."

    full_label, compact_label, css_class = labels[state]
    return (state, compact_label if compact else full_label,
            css_class, tooltip)
