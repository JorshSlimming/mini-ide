#!/usr/bin/env python3
# PanelIDE: dynamic multitask layout (projects can be added or closed freely).
import sys, os, shutil, csv, json, subprocess, math, time
from itertools import islice
from mini_ide.settings import (WARN_LARGE, MAX_LARGE, MAX_PDF_PIXELS,
                               migrate_legacy_config)
from mini_ide.file_ops import (atomic_write, atomic_create,
                               atomic_write_checked, file_state,
                               FileChangedError, validate_child_name,
                               create_new_file, create_new_dir, path_inside,
                               copy_dest_safe)
from mini_ide.document import DocumentState, doc_relocator, docs_under
from mini_ide import branch_sync as ide_branch_sync
from mini_ide import runners as ide_runners
from mini_ide import docker_state as ide_docker
from mini_ide import git_state as ide_git
from mini_ide import tree_state as ide_tree
from mini_ide import multitask_ui as mt_ui


import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Vte', '2.91')
gi.require_version('GtkSource', '4')
from gi.repository import Gtk, Gdk, Vte, GtkSource, GLib, Pango, GdkPixbuf, Gio

HAS_POPPLER = HAS_GST = False
try:
    gi.require_version('Poppler', '0.18')
    from gi.repository import Poppler
    HAS_POPPLER = True
except Exception:
    pass
try:
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    Gst.init(None)
    HAS_GST = True
except Exception:
    pass

FOLDER = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
HARNESS_CMD = (os.environ.get("PANELIDE_HARNESS")
               or os.environ.get("MINI_IDE_OMP")
               or shutil.which("omp")
               or os.path.expanduser("~/.local/bin/omp"))
ICONS = os.path.expanduser("~/.vscode/extensions/pkief.material-icon-theme-5.37.0/icons")
SCRIPT = os.path.abspath(__file__)
SCRIPT_DIR = os.path.dirname(SCRIPT)
CONFIG_DIR = (os.environ.get("PANELIDE_CONFIG_DIR")
              or os.path.expanduser("~/.config/panelide"))
LEGACY_CONFIG_DIR = os.path.expanduser("~/.config/mini-ide")
migrate_legacy_config(LEGACY_CONFIG_DIR, CONFIG_DIR)
RECENT_FILE = (os.environ.get("PANELIDE_RECENTS")
               or os.environ.get("MINI_IDE_RECENTS")
               or os.path.join(CONFIG_DIR, "recent.json"))
SESSION_FILE = (os.environ.get("PANELIDE_SESSION")
                or os.environ.get("MINI_IDE_SESSION")
                or os.path.join(CONFIG_DIR, "session.json"))
APP_ICON = os.path.join(SCRIPT_DIR, "app-icon", "png", "panelide-256.png")
CSS_FILE = os.path.join(SCRIPT_DIR, "theme", "panelide-gtk3.css")
SOURCE_THEME_DIR = os.path.join(SCRIPT_DIR, "theme")
UI_ICON_DIR = os.path.join(SCRIPT_DIR, "ui-icons")

IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "tiff", "svg", "avif"}
AUD_EXT = {"mp3", "ogg", "oga", "wav", "flac", "m4a", "opus", "wma", "aac", "mid", "midi"}
CSV_EXT = {"csv", "tsv"}
CSV_COLORS = ["#1B3433", "#1C303A", "#343222", "#33272A", "#2B2936"]

# How long a Git worktree classification may be reused. The classification
# runs in a worker thread, never on the GTK thread, and new entries force an
# early refresh instead of waiting for this TTL.
WORKTREE_TTL = 2.0


def set_button_icon(button, name, size=16, semantic=False):
    category = "semantic" if semantic else "neutral"
    icon_path = os.path.join(UI_ICON_DIR, category, name + ".svg")
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            icon_path, size, size, True)
    except Exception:
        button.set_image(None)
        return False
    button.set_image(Gtk.Image.new_from_pixbuf(pixbuf))
    button.set_always_show_image(True)
    return True


def icon_button(name, tooltip, callback=None, toggle=False, *classes,
                label=None):
    button_type = Gtk.ToggleButton if toggle else Gtk.Button
    button = button_type()
    if name:
        set_button_icon(button, name)
    if label is not None:
        button.set_label(label)
        button.set_image_position(Gtk.PositionType.LEFT)
    button.set_tooltip_text(tooltip)
    context = button.get_style_context()
    context.add_class("chrome")
    context.add_class("icon-btn")
    for css_class in classes:
        context.add_class(css_class)
    if callback is not None:
        button.connect("toggled" if toggle else "clicked", callback)
    return button

THEME_JSON = os.path.expanduser("~/.vscode/extensions/pkief.material-icon-theme-5.37.0/dist/material-icons.json")

def _load_theme():
    try:
        d = json.load(open(THEME_JSON))
    except Exception:
        return None
    defs = d.get("iconDefinitions", {})
    base = os.path.dirname(THEME_JSON)

    def resolve(id_or_path):
        if not id_or_path:
            return None
        if id_or_path in defs:
            p = defs[id_or_path].get("iconPath")
            if not p:
                return None
            id_or_path = p
        p = os.path.normpath(os.path.join(base, id_or_path))
        return p if os.path.exists(p) else None

    return {
        "ext": {str(k).lower(): v for k, v in d.get("fileExtensions", {}).items()},
        "name": {str(k).lower(): v for k, v in d.get("fileNames", {}).items()},
        "folder": {str(k).lower(): v for k, v in d.get("folderNames", {}).items()},
        "folder_open": {str(k).lower(): v for k, v in d.get("folderNamesExpanded", {}).items()},
        "default_file": resolve(d.get("file")),
        "default_folder": resolve(d.get("folder")),
        "default_folder_open": resolve(d.get("folderExpanded")),
        "resolve": resolve,
    }

THEME = _load_theme()
_icon_cache = {}

def load_icon(name, size=16):
    p = os.path.join(ICONS, name + ".svg")
    if not os.path.exists(p):
        return None
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_size(p, size, size)
    except Exception:
        return None

def themed_icon(id_or_path, size=16):
    if not THEME:
        return None
    p = THEME["resolve"](id_or_path)
    if not p:
        return None
    key = (p, size)
    if key not in _icon_cache:
        try:
            _icon_cache[key] = GdkPixbuf.Pixbuf.new_from_file_at_size(p, size, size)
        except Exception:
            _icon_cache[key] = None
    return _icon_cache[key]

def icon_for(name, is_dir=False, expanded=False):
    if THEME:
        if is_dir:
            k = name.lower()
            if expanded:
                return themed_icon(THEME["folder_open"].get(k)) or themed_icon(
                    THEME["default_folder_open"]) or load_icon("folder-open")
            return themed_icon(THEME["folder"].get(k)) or themed_icon(
                THEME["default_folder"]) or load_icon("folder")
        k = name.lower()
        ext = k.rsplit(".", 1)[-1] if "." in k else ""
        id_ = THEME["name"].get(k) or THEME["ext"].get(ext)
        return themed_icon(id_) or themed_icon(THEME["default_file"]) or load_icon("file")
    if is_dir:
        return load_icon("folder-" + name.lower().lstrip('.')) or load_icon("folder")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return load_icon(ext) if load_icon(ext) else load_icon("file")


class ProjectPanel(Gtk.Box):
    """A complete project: harness + editor + tree + terminals.
    layout 'full' (normal mode) or 'compact' (multitasking)."""

    def __init__(self, root, layout="full", on_close=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.root = os.path.abspath(root)
        self.layout = layout
        self.on_close = on_close
        self._refresh_id = None
        self._pending = None
        self._edit_target = None
        self.monitors = {}
        self.open_widgets = {}
        self.ed_paths = {}
        self.players = []
        self.harness_pid = None
        self._compact_tabbed = False
        self._shutdown = False
        self._reloading = False
        self.docs = {}
        self.tab_labels = {}
        self.audio_state = {}
        self._tree_collapsed = False
        self._tabs_collapsed = False
        self._tree_positions = {"full": None, "compact": None}
        self._tabs_positions = {"full": None, "compact": None}
        self._compact_needs_size = True
        # runner self-hosted (manual, sin daemons): se resuelve por convención
        self.runner_info = ide_runners.resolve(self.root)
        self.runner_state = "unknown"  # on|off|busy|none|wait|unknown
        self.runner_btn = None
        self._runner_op = False
        # docker compose por proyecto (manual, sin sudo)
        self.docker_info = ide_docker.resolve(self.root)
        self.docker_state = "unknown"  # on|off|partial|none|wait|unknown
        self.docker_btn = None
        self._docker_op = False
        self._docker_cts = None
        # rama git del proyecto (selector local, sin red)
        self.git_info = {"is_repo": False, "root": None, "branch": None,
                         "head": None, "detached": False, "unborn": False,
                         "dirty": False}
        self._branch_op = False
        self._branch_thread = None
        self._branch_info_busy = False
        self._branch_info_gen = 0
        self._branch_info_pending = False
        self._branch_info_reconcile = True
        self._branch_names = []
        self._branch_menu_current = None
        self._tree_git_ready = False
        self._worktree_state = None
        self._worktree_state_at = 0.0
        self._worktree_state_root = None
        self._state_cache = {}
        self._state_requests = set()
        self._state_force = set()
        self._force_state_roots = set()
        self._nested_roots = set()

        self.lang_mgr = GtkSource.LanguageManager.get_default()
        self.style_mgr = GtkSource.StyleSchemeManager.get_default()
        if SOURCE_THEME_DIR not in self.style_mgr.get_search_path():
            self.style_mgr.append_search_path(SOURCE_THEME_DIR)
        self.dark_scheme = (self.style_mgr.get_scheme("panelide-dark")
                            or self.style_mgr.get_scheme("oblivion")
                            or self.style_mgr.get_scheme("vs-dark"))

        # editor with tabs
        self.ed_tabs = Gtk.Notebook()
        self.ed_tabs.set_scrollable(True)
        self.ed_tabs.set_tab_pos(Gtk.PositionType.TOP)
        self.editor_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.editor_pane.pack_start(self.ed_tabs, True, True, 0)
        self.editor_pane.hide()

        # Generic harness terminal
        self.harness_term = self.make_terminal()
        self.spawn_harness()

        # command terminals
        self.tabs = Gtk.Notebook()
        self.tabs.set_scrollable(True)
        self.tabs.set_tab_pos(Gtk.PositionType.TOP)
        self.cmd_terms = []
        tab_actions = Gtk.Box(spacing=2)
        tab_actions.get_style_context().add_class("terminal-actions")
        self.tab_actions = tab_actions
        plus_btn = icon_button("plus", "New terminal (Ctrl+T)",
                               lambda w: self.add_command_tab())
        tab_actions.pack_start(plus_btn, False, False, 0)
        self.btn_collapse = icon_button(
            "panel-bottom", "Hide command terminals", self.toggle_tabs,
            False, "panel-toggle")
        tab_actions.pack_start(self.btn_collapse, False, False, 0)
        self.tabs.set_action_widget(tab_actions, Gtk.PackType.END)
        tab_actions.show_all()
        self.add_command_tab()

        # tree: icon, name, path, kind, state label, tooltip, state code
        self.store = Gtk.TreeStore(GdkPixbuf.Pixbuf, str, str, str, str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        r_icon = Gtk.CellRendererPixbuf()
        r_name = Gtk.CellRendererText()
        r_name.set_property("editable", False)
        r_name.set_property("ypad", 6)
        r_name.connect("edited", self.on_name_edited)
        r_name.connect("editing-canceled", self.on_editing_canceled)
        self.r_name = r_name
        col = Gtk.TreeViewColumn("Files")
        col.pack_start(r_icon, False)
        col.pack_start(r_name, True)
        col.add_attribute(r_icon, "pixbuf", 0)
        col.add_attribute(r_name, "text", 1)
        self.tree.append_column(col)
        r_badge = Gtk.CellRendererText()
        r_badge.set_property("xpad", 4)
        r_badge.set_property("ypad", 6)
        r_badge.set_property("xalign", 1.0)
        self.r_badge = r_badge
        badge_col = Gtk.TreeViewColumn("State")
        badge_col.pack_start(r_badge, False)
        badge_col.set_cell_data_func(r_badge, self._badge_data)
        badge_col.set_min_width(64)
        badge_col.set_max_width(96)
        badge_col.set_resizable(False)
        self.tree.append_column(badge_col)
        self.tree.set_headers_visible(False)
        self.tree.set_has_tooltip(True)
        self.tree.connect("query-tooltip", self.on_tree_tooltip)
        self.tree.connect("row-activated", self.on_enter)
        self.tree.connect("button-press-event", self.on_tree_btn)
        self.tree.connect("row-expanded", self.on_expand)
        self.tree.connect("row-collapsed", self.on_collapse)
        self.tree.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                                  [Gtk.TargetEntry.new("application/x-panelide-path", 0, 81)],
                                  Gdk.DragAction.MOVE)
        self.tree.connect("drag-data-get", self.on_drag_data_get)
        self.tree.drag_dest_set(Gtk.DestDefaults.ALL,
                                [Gtk.TargetEntry.new("application/x-panelide-path", 0, 81),
                                 Gtk.TargetEntry.new("text/uri-list", 0, 80)],
                                Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        self.tree.connect("drag-data-received", self.on_drop)
        self.scroll_tree = Gtk.ScrolledWindow()
        self.scroll_tree.add(self.tree)

        btn_newfile = icon_button(
            "new-file", "New file", lambda w: self.start_new("newfile"))
        btn_newfolder = icon_button(
            "new-folder", "New folder", lambda w: self.start_new("newfolder"))
        self.branch_btn, self.branch_lbl = self._make_branch_button()

        self.path_lbl = Gtk.Label(xalign=0)
        self.path_lbl.set_width_chars(12)
        self.path_lbl.set_max_width_chars(18)
        self.path_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.path_lbl.set_tooltip_text(self.root)
        self.path_lbl.get_style_context().add_class("secondary-label")
        self.path_lbl.set_text(self.root)
        btn_copy = icon_button("copy", "Copy folder path", self.copy_path)
        btn_open = icon_button(
            "folder-open", "Open folder in file manager", self.open_in_fm)

        self.row_path = Gtk.Box(spacing=4)
        self.row_path.get_style_context().add_class("tree-path")
        self.row_path.pack_start(self.path_lbl, True, True, 6)
        self.row_path.pack_end(btn_open, False, False, 0)
        self.row_path.pack_end(btn_copy, False, False, 0)
        self.row_new = Gtk.Box(spacing=4)
        self.row_new.get_style_context().add_class("tree-actions")
        self.row_new.pack_start(btn_newfile, False, False, 0)
        self.row_new.pack_start(btn_newfolder, False, False, 0)
        self.row_new.pack_start(self.branch_btn, True, True, 0)
        self.local_legend = Gtk.Label(xalign=0)
        self.local_legend.set_ellipsize(Pango.EllipsizeMode.END)
        self.local_legend.set_text("untracked · ignored · mixed · empty = local content")
        self.local_legend.get_style_context().add_class("secondary-label")
        self.local_legend.set_tooltip_text(
            "Entries marked untracked, ignored, mixed, local or empty are "
            "not part of the current Git commit. PanelIDE shows them from "
            "disk and keeps local files when switching branches. A repo "
            "badge marks a nested Git repository managed by its own branch. "
            "A ? badge means Git classification is unavailable or stale.")
        self.local_legend.set_no_show_all(True)
        self.tree_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.tree_bar.get_style_context().add_class("tree-toolbar")
        self.tree_bar.pack_start(self.row_path, False, False, 0)
        self.tree_bar.pack_start(self.row_new, False, False, 0)
        self.tree_bar.pack_start(self.local_legend, False, False, 0)

        self.root_drop = Gtk.Box(spacing=6)
        self.root_drop.get_style_context().add_class("root-drop")
        ico = load_icon("folder") or load_icon("folder-open")
        if ico:
            self.root_drop.pack_start(Gtk.Image.new_from_pixbuf(ico), False, False, 0)
        drop_lbl = Gtk.Label(label="Drop here to copy to root", xalign=0)
        self.root_drop.pack_start(drop_lbl, False, False, 0)
        self.root_drop.drag_dest_set(Gtk.DestDefaults.ALL,
                                     [Gtk.TargetEntry.new("text/uri-list", 0, 80)],
                                     Gdk.DragAction.COPY)
        self.root_drop.connect("drag-data-received", self.on_root_drop)
        self.root_drop.set_visible(False)

        self.tree_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tree_box.pack_start(self.tree_bar, False, False, 3)
        self.tree_box.pack_start(self.root_drop, False, False, 0)
        self.tree_box.pack_start(self.scroll_tree, True, True, 0)

        self.connect("key-press-event", self.on_key)
        self.set_layout(layout)
        self.populate(None, self.root, self.store)
        self.watch_path(self.root)
        GLib.idle_add(self._branch_refresh)

    # ---------------- self-hosted runner (100% manual) ----------------
    def _runner_paint(self, button=None, compact=None):
        btn = button if button is not None else self.runner_btn
        if btn is None:
            return
        if compact is None:
            compact = self.layout == "compact"
        state = self.runner_state
        if state in (None, "unknown"):
            state = None
        state, label, cls, tip = ide_runners.presentation(
            self.runner_info, state=state, compact=compact)
        self.runner_state = state
        context = btn.get_style_context()
        for old in ("runner-on", "runner-off", "runner-busy",
                    "runner-none", "runner-wait"):
            context.remove_class(old)
        context.add_class(cls)
        self._runner_cls = cls
        btn.set_label(label)
        btn.set_tooltip_text(tip)


    def _runner_refresh(self, button=None):
        """Refresh local runner state without network access."""
        if self._runner_op:
            return False
        info = self.runner_info or {}
        if not info.get("has_runner"):
            self.runner_state = "none"
        else:
            ls = ide_runners.local_state(info.get("unit", ""))
            if ls == "active":
                if self.runner_state != "busy":
                    self.runner_state = "on"
            elif ls in ("inactive", "failed"):
                self.runner_state = "off"
            else:
                self.runner_state = "unknown"
        try:
            self._runner_paint(button)
        except Exception:
            pass
        return False


    def _runner_refresh_remote(self):
        """Fetch remote online/busy state on hover, off the GTK thread."""
        info = self.runner_info or {}
        if not info.get("has_runner") or not info.get("installed"):
            return
        st = ide_runners.remote_state(info["org"], info["repo"],
                                      info["agent"])
        if st is None or self._runner_op:
            return
        online, busy = st
        ls = ide_runners.local_state(info["unit"])
        if busy and ls == "active":
            self.runner_state = "busy"
        elif not online and ls == "active":
            self.runner_state = "wait"
        elif ls == "active":
            self.runner_state = "on"
        else:
            self.runner_state = "off"
        GLib.idle_add(self._sync_runner_display)

    def _sync_runner_display(self):
        self._runner_paint()
        window = self.get_toplevel()
        if hasattr(window, "_hb_runner_sync"):
            window._hb_runner_sync()
        return False

    def on_runner_hover(self, w, ev):
        import threading
        threading.Thread(target=self._runner_refresh_remote,
                         daemon=True).start()
        return False

    # ---------------- docker compose por proyecto (manual) ----------------
    def _docker_paint(self, button=None, compact=None):
        btn = button if button is not None else self.docker_btn
        if btn is None:
            return
        if compact is None:
            compact = self.layout == "compact"
        state = self.docker_state
        if state in (None, "unknown"):
            state = None
        state, label, cls, tip = ide_docker.presentation(
            self.docker_info, cts=getattr(self, "_docker_cts", None),
            state=state, compact=compact)
        self.docker_state = state
        context = btn.get_style_context()
        for old in ("docker-on", "docker-off", "docker-partial",
                    "docker-none", "docker-wait"):
            context.remove_class(old)
        context.add_class(cls)
        btn.set_label(label)
        btn.set_tooltip_text(tip)

    def _docker_refresh(self, button=None):
        """Encola refresh compose en hilo (ps ~200ms, no bloquea GTK)."""
        import threading
        info = self.docker_info or {}
        if not info.get("has_docker"):
            self.docker_state = "none"
            try:
                self._docker_paint(button)
            except Exception:
                pass
            return False
        if self._docker_op:
            return False
        self.docker_state = "wait"
        try:
            self._docker_paint(button)
        except Exception:
            pass
        threading.Thread(target=self._docker_refresh_bg,
                         args=(button,), daemon=True).start()
        return False

    def _docker_refresh_bg(self, button=None):
        info = self.docker_info or {}
        cts = ide_docker.containers(info)
        if self._docker_op:
            return
        if cts is None:
            self.docker_state = "unknown"
            self._docker_cts = None
        else:
            self.docker_state = ide_docker.state_of(cts)
            self._docker_cts = cts
        GLib.idle_add(self._docker_display, button)

    def _docker_display(self, button=None):
        try:
            self._docker_paint(button)
        except Exception:
            pass
        window = self.get_toplevel()
        if hasattr(window, "_hb_docker_sync"):
            window._hb_docker_sync()
        return False

    def on_docker_toggle(self, btn):
        import threading
        if self._docker_op:
            return
        info = self.docker_info or {}
        if not info.get("has_docker"):
            self._runner_info_dialog(
                "No docker",
                "%s has no compose file.\nAdd compose.yaml "
                "(or docker-compose.yml) at the project root."
                % os.path.basename(self.root))
            return
        if self.docker_state == "wait":
            return
        self._docker_op = True
        self.docker_state = "wait"
        self._docker_paint(btn)
        btn.set_sensitive(False)

        def done_ok(kind):
            self._docker_op = False
            btn.set_sensitive(True)
            if kind == "started":
                self.docker_state = "wait"
            else:
                self.docker_state = "unknown"
            GLib.idle_add(self._docker_refresh, btn)

        def job_toggle():
            try:
                cts = ide_docker.containers(info)
                if cts is None:
                    GLib.idle_add(self._runner_info_dialog, "Error",
                                  "Could not query compose for %s."
                                  % info.get("project"))
                    GLib.idle_add(done_ok, "error")
                    return
                running, _total = ide_docker.summarize(cts)
                if running > 0:
                    ok = ide_docker.stop(info)
                else:
                    ok = ide_docker.up(info)
                if not ok:
                    GLib.idle_add(self._runner_info_dialog, "Error",
                                  "Docker operation failed for %s."
                                  % info.get("project"))
                GLib.idle_add(done_ok, "started" if ok else "error")
            except Exception as ex:
                print("docker toggle:", ex)
                GLib.idle_add(done_ok, "error")

        threading.Thread(target=job_toggle, daemon=True).start()

    def _runner_info_dialog(self, text, secondary=""):
        win = self.get_toplevel()
        dlg = Gtk.MessageDialog(
            transient_for=win if isinstance(win, Gtk.Window) else None,
            modal=True, message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text=text)
        if secondary:
            dlg.format_secondary_text(secondary)
        dlg.run()
        dlg.destroy()

    def on_runner_toggle(self, btn):
        import threading
        if self._runner_op:
            return
        info = self.runner_info or {}
        if not info.get("has_runner"):
            self._runner_info_dialog(
                "No runner",
                "%s has no configured runner.\nRun ./config.sh from a "
                "~/actions-runners/<name> folder, then run `runners rescan`."
                % os.path.basename(self.root))
            return
        if self.runner_state == "wait":
            return
        self._runner_op = True
        self.runner_state = "wait"
        self._runner_paint(btn)
        btn.set_sensitive(False)

        def done_ok(kind):
            self._runner_op = False
            btn.set_sensitive(True)
            if kind == "started":
                self.runner_state = "wait"
                self._runner_paint(btn)
                threading.Thread(target=self._runner_await_up,
                                 args=(btn,), daemon=True).start()
            else:
                self.runner_state = "off"
                GLib.idle_add(self._runner_refresh, btn)

        def job_toggle():
            try:
                if not info.get("installed"):
                    if not ide_runners.ensure_installed(info):
                        GLib.idle_add(self._runner_info_dialog, "Error",
                                      "Could not install the unit for %s."
                                      % info.get("repo"))
                        GLib.idle_add(done_ok, "error")
                        return
                    info["installed"] = True
                ls = ide_runners.local_state(info["unit"])
                if ls == "active":
                    st = ide_runners.remote_state(
                        info["org"], info["repo"], info["agent"])
                    if st is not None and st[1]:
                        GLib.idle_add(self._runner_confirm_stop_busy, info,
                                      btn, done_ok)
                        return
                    ide_runners.stop_unit(info["unit"])
                    ide_runners.wait_inactive(info["unit"], timeout=40)
                    GLib.idle_add(done_ok, "stopped")
                else:
                    if ide_runners.start_unit(info["unit"]):
                        GLib.idle_add(done_ok, "started")
                    else:
                        GLib.idle_add(self._runner_info_dialog, "Error",
                                      "Could not start %s."
                                      % info.get("repo"))
                        GLib.idle_add(done_ok, "error")
            except Exception as ex:
                print("runner toggle:", ex)
                GLib.idle_add(done_ok, "error")

        threading.Thread(target=job_toggle, daemon=True).start()

    def _runner_await_up(self, button=None):
        """After starting, wait for local activation and one remote check."""
        info = self.runner_info or {}
        for _i in range(15):
            if ide_runners.local_state(info.get("unit", "")) == "active":
                break
            time.sleep(2)
        self._runner_refresh_remote()
        GLib.idle_add(self._runner_op_done_up, button)

    def _runner_op_done_up(self, button=None):
        self._runner_op = False
        btn = button if button is not None else self.runner_btn
        if btn is not None:
            btn.set_sensitive(True)
        if self.runner_state == "wait":
            self.runner_state = "unknown"
        self._runner_refresh(button)
        return False

    def _runner_confirm_stop_busy(self, info, btn, done_ok):
        win = self.get_toplevel()
        dlg = Gtk.MessageDialog(
            transient_for=win if isinstance(win, Gtk.Window) else None,
            modal=True, message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text="Runner “%s” has an active job" % info.get("repo"))
        dlg.format_secondary_text(
            "A job is running. Stop the runner anyway? This may fail the job.")
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Stop anyway", Gtk.ResponseType.YES)
        resp = dlg.run()
        dlg.destroy()
        import threading

        def job():
            if resp == Gtk.ResponseType.YES:
                ide_runners.stop_unit(info["unit"])
                ide_runners.wait_inactive(info["unit"], timeout=40)
            GLib.idle_add(done_ok, "stopped")

        threading.Thread(target=job, daemon=True).start()

    # ---------------- layout ----------------
    def set_layout(self, layout):
        old_tabbed = self._compact_tabbed
        self.layout = layout
        self._compact_needs_size = layout == "compact"
        self._compact_tabbed = False
        for ch in list(self.get_children()):
            self.remove(ch)
        if old_tabbed:
            try:
                page = self.ed_tabs.page_num(self.harness_term)
                if page >= 0:
                    self.ed_tabs.remove_page(page)
            except Exception:
                pass
            self.open_widgets.pop("__harness__", None)
        # detach shared widgets from their old containers
        for w in (self.harness_term, self.editor_pane, self.tree_box, self.tabs,
                  getattr(self, "top_h", None)):
            if w is None:
                continue
            p = w.get_parent()
            if p is not None and p is not self:
                p.remove(w)
        for attr in ("main_h", "right_v", "main_v", "bottom_h"):
            if hasattr(self, attr):
                w = getattr(self, attr)
                p = w.get_parent()
                if p is not None and p is not self:
                    p.remove(w)
        if layout == "compact":
            self.top_h = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            self.editor_pane.set_size_request(mt_ui.PANEL_EDITOR_MIN_PX, -1)
            self.top_h.pack1(self.editor_pane, True, False)
            self.top_h.pack2(self.harness_term, True, False)
            self.top_h.connect("size-allocate", self.on_top_alloc)
            self.bottom_h = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            self.bottom_h.pack1(self.tree_box, True, False)
            self.bottom_h.pack2(self.tabs, True, False)
            self.main_v = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
            self.main_v.pack1(self.top_h, True, False)
            self.main_v.pack2(self.bottom_h, True, False)
            self.main_v.connect("size-allocate", self.on_main_v_alloc)
            # Text labels preserve meaning while the shrinkable center slot
            # absorbs the squeeze first in two- and three-project columns.
            bar = Gtk.Box(spacing=4)
            bar.get_style_context().add_class("project-bar")
            controls = Gtk.Box(spacing=3)
            controls.set_hexpand(False)
            bar.pack_start(controls, False, False, 2)
            self.btn_tree = icon_button(
                "files", "Hide files", self.toggle_tree,
                False, "panel-toggle", label="Files")
            self.btn_tree.set_hexpand(False)
            controls.pack_start(self.btn_tree, False, False, 0)
            self.runner_btn = icon_button(
                None, "Runner status", self.on_runner_toggle,
                False, "runner-btn", "runner-compact", label="… WAIT")
            self.runner_btn.set_hexpand(False)
            self.runner_btn.connect("enter-notify-event",
                                    self.on_runner_hover)
            controls.pack_start(self.runner_btn, False, False, 0)
            self.docker_btn = icon_button(
                None, "Docker compose status", self.on_docker_toggle,
                False, "docker-btn", "docker-compact", label="… WAIT")
            self.docker_btn.set_hexpand(False)
            controls.pack_start(self.docker_btn, False, False, 0)
            self._runner_paint()
            self._docker_paint()
            GLib.idle_add(self._runner_refresh)
            GLib.idle_add(self._docker_refresh)
            self._move_terminal_toggle(controls)
            self.btn_collapse.set_hexpand(False)
            center = Gtk.Box(spacing=0)
            center.set_hexpand(True)
            center.set_halign(Gtk.Align.FILL)
            lbl = Gtk.Label(xalign=0.5)
            lbl.get_style_context().add_class("project-name")
            lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(os.path.basename(self.root)))
            lbl.set_justify(Gtk.Justification.CENTER)
            lbl.set_halign(Gtk.Align.CENTER)
            lbl.set_valign(Gtk.Align.CENTER)
            lbl.set_hexpand(False)
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            lbl.set_max_width_chars(mt_ui.title_max_chars(3))
            lbl.set_tooltip_text(self.root)
            self.title_lbl = lbl
            center.pack_start(lbl, True, True, 0)
            bar.pack_start(center, True, True, 2)
            if self.on_close:
                bx = icon_button(
                    "close", "Close project (stops its harness)",
                    lambda w: self.on_close(self))
                bx.set_hexpand(False)
                bar.pack_end(bx, False, False, 2)
            self.set_size_request(mt_ui.PANEL_MIN_PX, -1)
            self.pack_start(bar, False, False, 2)
            self.pack_start(self.main_v, True, True, 0)
            self.root_drop.set_visible(True)
            GLib.idle_add(self._compact_sizes)
        else:
            self.editor_pane.set_size_request(-1, -1)
            self.top_h = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            self.top_h.pack1(self.editor_pane, False, False)
            self.top_h.pack2(self.harness_term, True, False)
            self.top_h.connect("size-allocate", self.on_top_alloc)
            self.right_v = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
            self.right_v.pack1(self.top_h, True, False)
            self.right_v.pack2(self.tabs, True, False)
            self.right_v.set_position(520)
            self.main_h = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            self.main_h.pack1(self.tree_box, False, False)
            self.main_h.pack2(self.right_v, True, False)
            self.main_h.set_position(280)
            self.root_drop.set_visible(False)
            self._move_terminal_toggle(self.tab_actions)
            self.title_lbl = None
            self.set_size_request(-1, -1)
            self.pack_start(self.main_h, True, True, 0)
        GLib.idle_add(self._apply_tabs_state)
        GLib.idle_add(self._apply_tree_state)

    def _compact_sizes(self):
        self._apply_compact_sizes()
        return False

    def on_main_v_alloc(self, paned, alloc):
        if self.layout == "compact" and self._compact_needs_size:
            self._apply_compact_sizes()

    def _apply_compact_sizes(self):
        try:
            w = self.bottom_h.get_allocated_width()
            h = self.main_v.get_allocated_height()
            saved_position = (self._tree_positions["compact"]
                              if self._tree_positions["compact"] is not None
                              else self._tabs_positions["compact"])
            position = mt_ui.compact_bottom_position(
                w, self._tree_collapsed, self._tabs_collapsed,
                saved_position)
            if position is not None:
                self.bottom_h.set_position(position)
            if h > 50:
                pos = mt_ui.compact_main_position(
                    h, self._tree_collapsed, self._tabs_collapsed)
                if pos is not None:
                    self.main_v.set_position(pos)
            if w > 50 and h > 50:
                self._compact_needs_size = False
        except Exception:
            pass

    def _apply_compact_bottom_visibility(self):
        if self.layout != "compact":
            return
        if mt_ui.compact_bottom_visible(
                self._tree_collapsed, self._tabs_collapsed):
            self.bottom_h.show()
        else:
            self.bottom_h.hide()
        GLib.idle_add(self._apply_compact_sizes)

    # ---------------- editor/terminal visibility ----------------
    def _apply_editor_visibility(self):
        if self.ed_tabs.get_n_pages() == 0:
            self.editor_pane.hide()
        else:
            self.editor_pane.show()

    def _move_terminal_toggle(self, container):
        parent = self.btn_collapse.get_parent()
        if parent is container:
            try:
                self.btn_collapse.set_hexpand(False)
            except Exception:
                pass
            return
        if parent is not None:
            parent.remove(self.btn_collapse)
        self.btn_collapse.set_hexpand(False)
        container.pack_start(self.btn_collapse, False, False, 0)
        container.show_all()

    def _term_visible(self):
        if self.layout == "compact" and self._compact_tabbed:
            return self.harness_term.get_parent() is self.ed_tabs
        return self.harness_term.get_visible()

    def _mt_panel_width(self):
        try:
            self.top_h.set_position(self.top_h.get_allocated_width())
        except Exception:
            pass
        return False

    def update_compact(self):
        if self.layout != "compact":
            return
        n = len([w for w in self.open_widgets if w != "__harness__"])
        if n >= 2 and not self._compact_tabbed:
            self._compact_tabbed = True
            try:
                self.top_h.remove(self.harness_term)
            except Exception:
                pass
            if self.harness_term.get_parent() is None:
                self.harness_term.show()
                self.open_widgets["__harness__"] = self.harness_term
                self.ed_tabs.append_page(self.harness_term, Gtk.Label("Harness"))
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(self.harness_term))
            self.ed_tabs.show_all()
            self._apply_editor_visibility()
            GLib.idle_add(self._mt_panel_width)
        elif n < 2 and self._compact_tabbed:
            self._compact_tabbed = False
            try:
                page = self.ed_tabs.page_num(self.harness_term)
                if page >= 0:
                    self.ed_tabs.remove_page(page)
            except Exception:
                pass
            self.open_widgets.pop("__harness__", None)
            if self.harness_term.get_parent() is None:
                self.top_h.pack2(self.harness_term, True, False)
            self.top_h.show_all()
            self._apply_editor_visibility()
        if n == 0:
            GLib.idle_add(self._expand_harness)

    def _expand_harness(self):
        try:
            if self.layout == "compact" and not self.editor_pane.get_visible():
                self.top_h.set_position(0)
        except Exception:
            pass
        return False

    # ---------------- terminals ----------------
    def make_terminal(self):
        term = Vte.Terminal()
        term.set_font(Pango.FontDescription("Monospace 10"))
        try:
            fg = Gdk.RGBA(); fg.parse("#C7D0D5")
            bg = Gdk.RGBA(); bg.parse("#101517")
            term.set_color_foreground(fg)
            term.set_color_background(bg)
        except Exception:
            pass
        term.connect("selection-changed", self.on_term_selection)
        term.connect("key-press-event", self.on_term_key)
        term.connect("button-press-event", self.on_term_btn)
        return term

    def on_term_key(self, term, ev):
        if (ev.state & Gdk.ModifierType.CONTROL_MASK
                and Gdk.keyval_name(ev.keyval).lower() == 'v'):
            self.term_paste(term)
            return True
        return False

    def term_paste(self, term):
        term.paste_clipboard()

    def on_term_btn(self, term, ev):
        if ev.button != 3:
            return False
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label="Copy")
        item.connect("activate", lambda w: term.copy_clipboard())
        menu.append(item)
        item = Gtk.MenuItem(label="Paste")
        item.connect("activate", lambda w: self.term_paste(term))
        menu.append(item)
        if term is self.harness_term:
            sep = Gtk.SeparatorMenuItem()
            menu.append(sep)
            hint = Gtk.MenuItem(label="Select text: hold Shift")
            hint.set_sensitive(False)
            menu.append(hint)
        menu.show_all()
        try:
            menu.popup_at_pointer(ev)
        except Exception:
            pass
        return True

    def _spawn_async(self, term, wd, argv, on_pid=None):
        def on_spawn(t, pid, err, data=None):
            if on_pid:
                on_pid(int(pid) if pid else None)
            if err is not None:
                print("spawn error (%s):" % argv[0], err)

        try:
            term.spawn_async(Vte.PtyFlags.DEFAULT, wd, argv, None,
                             GLib.SpawnFlags.DEFAULT, None, None, 10000,
                             None, on_spawn, None)
        except Exception as ex:
            print("spawn error (%s):" % argv[0], ex)

    def spawn_harness(self):
        if (not HARNESS_CMD or not os.path.isfile(HARNESS_CMD)
                or not os.access(HARNESS_CMD, os.X_OK)):
            try:
                dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                        message_type=Gtk.MessageType.ERROR,
                                        buttons=Gtk.ButtonsType.OK,
                                        text="PanelIDE could not find its harness",
                                        secondary_text="Set PANELIDE_HARNESS to an executable "
                                                       "path. MINI_IDE_OMP remains supported.")
                dlg.run()
                dlg.destroy()
            except Exception:
                pass
            return
        self._spawn_async(self.harness_term, self.root, [HARNESS_CMD],
                          lambda pid: setattr(self, "harness_pid", pid))

    def on_term_selection(self, term):
        try:
            if not term.get_has_selection():
                return
            term.copy_clipboard()
        except Exception:
            pass

    def add_command_tab(self, btn=None):
        term = self.make_terminal()
        self._spawn_async(term, self.root, ["/bin/bash"])
        self.cmd_terms.append(term)
        lbl = Gtk.Label("T%d" % len(self.cmd_terms))
        close = icon_button("close", "Close terminal")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_focus_on_click(False)
        close.connect("clicked", self.close_tab, term)
        tab = Gtk.Box(spacing=8)
        tab.pack_start(lbl, False, False, 0)
        tab.pack_start(close, False, False, 0)
        tab.show_all()
        self.tabs.append_page(term, tab)
        self.tabs.show_all()
        self.tabs.set_current_page(self.tabs.page_num(term))
        return term

    def close_tab(self, btn, term):
        page = self.tabs.page_num(term)
        if page >= 0:
            self.tabs.remove_page(page)
            if term in self.cmd_terms:
                self.cmd_terms.remove(term)
                try:
                    term.kill_sync(Vte.TerminalKill.KILL_SHELL, None)
                except Exception:
                    pass
        for i, t in enumerate(self.cmd_terms):
            box = self.tabs.get_tab_label(t)
            if box:
                for child in box.get_children():
                    if isinstance(child, Gtk.Label):
                        child.set_text("T%d" % (i + 1))
                        break

    # ---------------- tree ----------------
    def _badge_data(self, column, cell, model, it, data):
        code = model.get_value(it, 6)
        cell.set_property("text", model.get_value(it, 4))
        colors = {
            ide_tree.UNTRACKED: "#F0C267",
            ide_tree.LOCAL: "#F0C267",
            ide_tree.MIXED: "#F0C267",
            ide_tree.IGNORED: "#91A0AA",
            ide_tree.EMPTY: "#81909A",
            ide_tree.NESTED: "#8CF3E3",
            ide_tree.UNKNOWN: "#C8D0D5",
        }
        color = colors.get(code)
        if color:
            cell.set_property("foreground", color)
            cell.set_property("foreground-set", True)
        else:
            cell.set_property("foreground-set", False)

    def on_tree_tooltip(self, tree, x, y, keyboard_mode, tooltip):
        info = tree.get_path_at_pos(int(x), int(y))
        if not info:
            return False
        it = self.store.get_iter(info[0])
        text = self.store.get_value(it, 5)
        if not text:
            return False
        tooltip.set_text(text)
        return True

    def _set_row_state(self, store, row, status):
        store.set(row, 4, status.label, 5, status.tooltip, 6, status.code)

    def _worktree_state_for(self, root, force=False):
        """Return cached Git classification, refreshing it in the background.

        ``git ls-files`` can take seconds on large repositories, so it must
        never run on the GTK thread. On a miss this returns the previous
        value (or ``None``) immediately and the caller repopulates once the
        worker applies the new state.
        """
        root = os.path.normpath(root)
        if not (self.git_info or {}).get("is_repo"):
            return None
        cached = self._state_cache.get(root)
        now = time.monotonic()
        if not force and cached and now - cached[1] < WORKTREE_TTL:
            return cached[0]
        self._request_worktree_state(root, force=force)
        return cached[0] if cached else None

    def _request_worktree_state(self, root, force=False):
        """Start one worker per root; coalesce repeated requests."""
        if getattr(self, "_shutdown", False):
            return
        root = os.path.normpath(root)
        if root in self._state_requests:
            if force:
                self._state_force.add(root)
            return
        self._state_requests.add(root)

        def worker():
            try:
                state = ide_git.worktree_state(root)
            except Exception:
                state = None
            GLib.idle_add(self._apply_worktree_state, root, state)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_worktree_state(self, root, state):
        """Install a worker result on the GTK thread and repopulate."""
        if root not in self._state_requests:
            return False
        self._state_requests.discard(root)
        if getattr(self, "_shutdown", False):
            return False
        self._state_cache[root] = (state, time.monotonic())
        project_root = os.path.normpath(self.root)
        if root == project_root:
            self._worktree_state = state
            self._worktree_state_at = time.monotonic()
            self._worktree_state_root = root
        force_again = root in self._state_force
        self._state_force.discard(root)
        if force_again:
            self._request_worktree_state(root, force=True)
        if not self._branch_op and (root == project_root
                                    or root in self._nested_roots):
            self._do_refresh()
            if root == project_root:
                self._branch_paint()
        return False

    def _state_owner(self, path):
        """Repository state that classifies *path* (project or nested)."""
        root = os.path.normpath(self.root)
        current = os.path.normpath(path)
        while current != root and current.startswith(root + os.sep):
            if current in self._nested_roots:
                return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return root

    def _state_covering(self, path):
        """Cached classification that currently covers *path*."""
        owner = self._state_owner(path)
        if owner == os.path.normpath(self.root):
            return self._worktree_state
        cached = self._state_cache.get(owner)
        return cached[0] if cached else None

    def _mark_state_dirty(self, path):
        """Force a fresh classification for the repository owning *path*.

        Forcing only the project root would leave a new file inside an
        expanded nested repository on its stale ``?`` badge until the
        nested cache expired and something else triggered a refresh.
        """
        self._force_state_roots.add(self._state_owner(path))

    def _state_for_path(self, path):
        """Use a nested repository's state when the tree enters one."""
        current = os.path.normpath(path)
        root = os.path.normpath(self.root)
        while current != root and current.startswith(root + os.sep):
            if current in self._nested_roots:
                return self._worktree_state_for(
                    current, force=current in self._force_state_roots)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return self._worktree_state

    def populate(self, parent_iter, path, store):
        listing = ide_tree.scan_directory(path)
        if parent_iter is not None and listing.nested:
            nested_path = os.path.normpath(path)
            self._nested_roots.add(nested_path)
            status = ide_tree.classify(path, True, self._worktree_state,
                                       nested=True)
            self._set_row_state(store, parent_iter, status)
        state = self._state_for_path(path)
        tracked = state.get("tracked", ()) if state else ()
        for e in listing.entries:
            kind = "folder" if e.is_dir else "file"
            empty = False
            nested = False
            entry_path = os.path.normpath(e.path)
            if state and e.is_dir and entry_path not in tracked:
                empty, nested = ide_tree.dir_metadata(e.path)
                if nested:
                    self._nested_roots.add(entry_path)
            if nested:
                status = ide_tree.classify(e.path, True, state, nested=True)
            else:
                status = ide_tree.classify(e.path, e.is_dir, state, empty=empty)
            row = store.append(parent_iter, [
                icon_for(e.name, e.is_dir), e.name, e.path, kind,
                status.label, status.tooltip, status.code])
            if e.is_dir:
                store.append(row, [None, None, None, None, None, None, None])

    def watch_path(self, path):
        if path in self.monitors:
            return
        try:
            mon = Gio.File.new_for_path(path).monitor_directory(Gio.FileMonitorFlags.NONE, None)
            if mon:
                self.monitors[path] = mon
                mon.connect("changed", self.on_fs_changed)
        except Exception:
            pass

    def on_fs_changed(self, mon, file, other, event):
        # Git rewrites many files while switching branches. Those events are
        # reconciled once in _branch_done; handling them here would raise a
        # conflict dialog for every intermediate write.
        if self._branch_op:
            return
        try:
            p = file.get_path()
        except Exception:
            p = None
        if p:
            self._handle_fs_event(p, event)
            structural = event not in (
                Gio.FileMonitorEvent.CHANGED,
                Gio.FileMonitorEvent.CHANGES_DONE_HINT,
                Gio.FileMonitorEvent.ATTRIBUTE_CHANGED)
            if ((self.git_info or {}).get("is_repo")
                    and (structural
                         or ide_tree.affects_classification(p)
                         or ide_tree.needs_reclassification(
                             self._state_covering(p), p))):
                # The cached classification predates this file/folder (or a
                # delete/rename changed the tree shape). Force a fresh Git
                # query for the repository that owns the path instead of
                # showing a stale "?" badge indefinitely.
                self._mark_state_dirty(p)
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
        self._refresh_id = GLib.timeout_add(350, self._do_refresh)

    def _handle_fs_event(self, path, event):
        if self._branch_op:
            return
        gone = event in (Gio.FileMonitorEvent.DELETED, Gio.FileMonitorEvent.MOVED_OUT)
        if path in self.monitors and gone:
            try:
                self.monitors.pop(path).cancel()
            except Exception:
                pass
            return
        if path not in self.open_widgets:
            return
        entry = self.ed_paths.get(path)
        if not entry:
            return
        buf = entry[0]
        doc = self.docs.get(buf)
        if doc is None:
            return
        disk = None
        try:
            st = os.stat(path)
            disk = (st.st_mtime_ns, st.st_size)
        except OSError:
            pass
        decision = doc.on_disk_event(disk)
        if decision == 'own':
            return
        if decision == 'reload':
            self.reload_buffer(buf, doc.path)
            return
        if decision == 'conflict':
            if not doc.conflict:
                doc.mark_conflict()
                self._update_tab_ui(buf)
                self._conflict_dialog(doc)
            return
        if decision == 'deleted':
            doc.external_delete()
            self._update_tab_ui(buf)

    def _conflict_dialog(self, doc):
        try:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="%s changed outside PanelIDE" % os.path.basename(doc.path),
                                    secondary_text="You have unsaved edits. Autosave is "
                                                   "suspended until you decide.")
            dlg.add_button("Reload from disk", Gtk.ResponseType.YES)
            dlg.add_button("Keep editor version", Gtk.ResponseType.NO)
            resp = dlg.run()
            dlg.destroy()
            if resp == Gtk.ResponseType.YES:
                return "reload" if self.reload_buffer(doc.buffer, doc.path) else None
            if resp == Gtk.ResponseType.NO:
                doc.resolve_keep_local()
                self._update_tab_ui(doc.buffer)
                return "keep"
        except Exception:
            pass
        return None

    def reload_buffer(self, buf, path):
        """Replace the buffer with disk content. Return success."""
        doc = self.docs.get(buf)
        strict = bool(doc and doc.strict_utf8)
        snap_before = ide_branch_sync.disk_snapshot(path)
        if snap_before is None:
            return False
        try:
            if strict:
                with open(path, 'r', encoding='utf-8') as f:
                    text = f.read()
            else:
                with open(path, 'r', errors='replace') as f:
                    text = f.read()
        except UnicodeDecodeError:
            try:
                with open(path, 'r', errors='replace') as f:
                    text = f.read()
            except OSError:
                return False
        except OSError:
            return False
        if ide_branch_sync.disk_snapshot(path) != snap_before:
            # The file changed while it was being read; do not install a
            # possibly mixed snapshot into the editor.
            return False
        self._reloading = True
        try:
            buf.set_text(text)
        finally:
            self._reloading = False
        if doc:
            doc.resolve_reload()
        self._update_tab_ui(buf)
        return True

    def _do_refresh(self):
        self._refresh_id = None
        if self._branch_op:
            # Git is rewriting the working tree; _refresh_after_branch will
            # repopulate once the operation (and reconciliation) is over.
            return False
        dirty_roots = tuple(self._force_state_roots)
        self._force_state_roots.clear()
        for state_root in dirty_roots:
            self._worktree_state_for(state_root, force=True)
        project_root = os.path.normpath(self.root)
        if project_root not in dirty_roots:
            self._worktree_state_for(self.root)
        self._nested_roots.clear()
        self._pending = None
        expanded = []
        it = self.store.get_iter_first()
        while it:
            self._collect_expanded(it, [], expanded)
            it = self.store.iter_next(it)
        sel_path = None
        sel = self.tree.get_selection().get_selected()
        if sel[1]:
            sel_path = self.store.get_value(sel[1], 2)
        self.store.clear()
        self.populate(None, self.root, self.store)
        for names in expanded:
            it2 = self.store.get_iter_first()
            ok = True
            for name in names:
                while it2 and self.store.get_value(it2, 1) != name:
                    it2 = self.store.iter_next(it2)
                if it2 is None:
                    ok = False
                    break
                if name != names[-1]:
                    it2 = self.store.iter_children(it2)
            if ok and it2:
                self.tree.expand_row(self.store.get_path(it2), False)
        if sel_path:
            sit = self.find_iter(self.store, None, sel_path)
            if sit:
                self.tree.get_selection().select_iter(sit)
        return False

    def _collect_expanded(self, it, chain, out):
        while it:
            kind = self.store.get_value(it, 3)
            if kind == "folder":
                name = self.store.get_value(it, 1)
                pth = self.store.get_path(it)
                if self.tree.row_expanded(pth):
                    out.append(chain + [name])
                    child = self.store.iter_children(it)
                    if child:
                        self._collect_expanded(child, chain + [name], out)
            it = self.store.iter_next(it)

    def refresh_tree(self):
        self._worktree_state_for(self.root, force=True)
        self._nested_roots.clear()
        self._pending = None
        self.store.clear()
        self.populate(None, self.root, self.store)

    def find_iter(self, store, parent, fpath):
        it = parent
        if parent is None:
            it = store.get_iter_first()
        while it:
            if store.get_value(it, 2) == fpath:
                return it
            child = store.iter_children(it)
            r = self.find_iter(store, child, fpath) if child else None
            if r:
                return r
            it = store.iter_next(it)
        return None

    def select_path(self, fpath):
        it = self.find_iter(self.store, None, fpath)
        if it:
            self.tree.get_selection().select_iter(it)

    def on_expand(self, tree, it, path):
        row = self.store.get_iter(path)
        self.store.set(row, 0, icon_for(self.store.get_value(row, 1), True, True))
        child = self.store.iter_children(row)
        if child and self.store.get_value(child, 3) is None:
            self.store.remove(child)
            sub = self.store.get_value(row, 2)
            self.populate(row, sub, self.store)
            self.watch_path(sub)

    def on_collapse(self, tree, it, path):
        row = self.store.get_iter(path)
        self.store.set(row, 0, icon_for(self.store.get_value(row, 1), True))

    def on_tree_btn(self, tree, ev):
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            info = tree.get_path_at_pos(int(ev.x), int(ev.y))
            if info:
                it = self.store.get_iter(info[0])
                fpath = self.store.get_value(it, 2)
                if fpath and os.path.isdir(fpath):
                    if tree.row_expanded(info[0]):
                        tree.collapse_row(info[0])
                    else:
                        tree.expand_row(info[0], False)
                elif fpath:
                    self.open_file(fpath)
                return True
        return False

    def on_enter(self, tree, path, col):
        it = self.store.get_iter(path)
        fpath = self.store.get_value(it, 2)
        if fpath and os.path.isdir(fpath):
            if tree.row_expanded(path):
                tree.collapse_row(path)
            else:
                tree.expand_row(path, False)
        elif fpath:
            self.open_file(fpath)

    def path_inside_root(self, target):
        return path_inside(self.root, target)

    def _name_error_dialog(self, name):
        try:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.ERROR,
                                    buttons=Gtk.ButtonsType.OK,
                                    text="Invalid name",
                                    secondary_text="Use a single file or folder name "
                                                   "(no paths, no '..', no '/'): '%s'" % name)
            dlg.run()
            dlg.destroy()
        except Exception:
            pass

    def _cancel_pending_creation(self):
        """Remove the inline placeholder row and forget its pending create."""
        self._edit_target = None
        if not self._pending:
            return False
        it = self._pending[0]
        self._pending = None
        try:
            if self.store.iter_is_valid(it):
                self.store.remove(it)
        except Exception:
            pass
        return True

    def on_name_edited(self, renderer, path_str, new_text):
        if self._branch_op:
            # A branch operation owns the working tree. Never materialize a
            # pending "New file" row into a file while Git is rewriting it.
            self._cancel_pending_creation()
            self._branch_busy_dialog()
            return
        target = self._edit_target
        self._edit_target = None
        if self._pending:
            it, kind, base = self._pending
            self._pending = None
            try:
                cur_path = self.store.get_path(it).to_string()
            except Exception:
                cur_path = None
            if cur_path == path_str:
                name = validate_child_name(new_text)
                if not name:
                    try:
                        if self.store.iter_is_valid(it):
                            self.store.remove(it)
                    except Exception:
                        pass
                    self._name_error_dialog(new_text)
                    return
                p = os.path.join(base, name)
                if not self.path_inside_root(p):
                    try:
                        if self.store.iter_is_valid(it):
                            self.store.remove(it)
                    except Exception:
                        pass
                    self._name_error_dialog(new_text)
                    return
                try:
                    if kind == "newfile":
                        create_new_file(p)
                    else:
                        create_new_dir(p)
                    self.refresh_tree()
                    self.select_path(p)
                    if kind == "newfile":
                        self.open_file(p)
                except FileExistsError:
                    try:
                        if self.store.iter_is_valid(it):
                            self.store.remove(it)
                    except Exception:
                        pass
                    dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                            message_type=Gtk.MessageType.ERROR,
                                            buttons=Gtk.ButtonsType.OK,
                                            text="Already exists",
                                            secondary_text="'%s' already exists and was not "
                                                           "modified." % name)
                    dlg.run()
                    dlg.destroy()
                except OSError as ex:
                    print("Error:", ex)
                return
        it = self.store.get_iter(path_str)
        if not it:
            return
        kind = self.store.get_value(it, 3)
        fpath = self.store.get_value(it, 2)
        if target is None or fpath != target:
            # The row was rebuilt (for example by a branch switch) and the
            # stale editing path now points somewhere else. Never rename a
            # different file than the one the user started editing.
            return
        name = validate_child_name(new_text)
        if not name or kind not in ("file", "folder"):
            if name is None:
                self._name_error_dialog(new_text)
            return
        newp = os.path.join(os.path.dirname(fpath), name)
        if newp != fpath and not os.path.exists(newp) and self.path_inside_root(newp):
            self.rename_path(fpath, newp)

    def rename_path(self, old, new):
        if self._branch_busy():
            return
        try:
            os.rename(old, new)
        except OSError as ex:
            print("Error:", ex)
            return
        for doc, new_path in doc_relocator(self.docs.values(), old, new).items():
            self._migrate_doc_path(doc, new_path)
            self._update_tab_ui(doc.buffer)
        self.refresh_tree()
        self.select_path(new)

    def on_editing_canceled(self, renderer, path_str):
        self._edit_target = None
        if self._pending:
            self._cancel_pending_creation()
            return
        it = self.store.get_iter(path_str)
        if it and self.store.get_value(it, 3) in ("newfile", "newfolder"):
            self.store.remove(it)

    def selected_base(self):
        sel = self.tree.get_selection().get_selected()
        if sel[1]:
            kind = self.store.get_value(sel[1], 3)
            p = self.store.get_value(sel[1], 2)
            if kind == "folder" and p:
                return p, sel[1]
            if kind == "file" and p:
                return os.path.dirname(p), None
            if kind in ("newfile", "newfolder") and p:
                return p, None
        return self.root, None

    def start_new(self, kind):
        if self._branch_busy():
            return
        self._cancel_pending_creation()
        base, parent_iter = self.selected_base()
        if parent_iter:
            self.tree.expand_row(self.store.get_path(parent_iter), False)
        icon = load_icon("file" if kind == "newfile" else "folder")
        row = self.store.append(parent_iter, [icon, "", base, kind, "", "", ""])
        self._pending = (row, kind, base)
        self._edit_target = base
        self.r_name.set_property("editable", True)
        col = self.tree.get_column(0)
        self.tree.set_cursor(self.store.get_path(row), col, True)
        GLib.idle_add(lambda: self.r_name.set_property("editable", False))

    def _copy_dest_safe(self, src, dst):
        return copy_dest_safe(src, dst)

    def _copy_error_dialog(self, name, reason="Cannot copy into itself or a descendant folder."):
        try:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.ERROR,
                                    buttons=Gtk.ButtonsType.OK,
                                    text="Copy refused",
                                    secondary_text="Cannot copy '%s': %s" % (name, reason))
            dlg.run()
            dlg.destroy()
        except Exception:
            pass

    def _copy_uris(self, uris, dest):
        """Copy dropped URIs into *dest*; return True when anything ran."""
        copied = False
        for uri in uris:
            try:
                src = GLib.filename_from_uri(uri)[0]
            except Exception:
                continue
            dst = os.path.join(dest, os.path.basename(src))
            if os.path.exists(dst) or not os.path.exists(src):
                continue
            if not path_inside(self.root, dst):
                self._copy_error_dialog(os.path.basename(src),
                                        "the destination is outside the project root.")
                continue
            if os.path.isdir(src) and not self._copy_dest_safe(src, dst):
                self._copy_error_dialog(os.path.basename(src))
                continue
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                copied = True
            except OSError as ex:
                print("Copy error:", ex)
        return copied

    def on_drop(self, tree, ctx, x, y, data, info, time):
        if self._branch_busy():
            ctx.finish(False, False, time)
            return
        if info == 81:
            src = os.fsdecode(bytes(data.get_data())) if data else None
            dest = self._tree_drop_destination(tree, x, y)
            if src and dest:
                self.move_path(src, dest)
            ctx.finish(True, False, time)
            return
        dest = self._tree_drop_destination(tree, x, y)
        if not dest:
            dest = self.root
        if data and data.get_uris() and self._copy_uris(data.get_uris(), dest):
            self._do_refresh()
        ctx.finish(True, False, time)

    def on_drag_data_get(self, tree, ctx, data, info, time):
        if info != 81:
            return
        sel = self.tree.get_selection().get_selected()
        if sel[1]:
            path = self.store.get_value(sel[1], 2)
            if path and self.path_inside_root(path):
                data.set(data.get_target(), 8, list(os.fsencode(path)))

    def _tree_drop_destination(self, tree, x, y):
        info = tree.get_path_at_pos(int(x), int(y))
        if not info:
            return self.root
        it = self.store.get_iter(info[0])
        kind = self.store.get_value(it, 3)
        path = self.store.get_value(it, 2)
        if kind == "folder" and path:
            return path
        if kind == "file" and path:
            return os.path.dirname(path)
        return self.root

    def move_path(self, src, dest):
        if self._branch_busy():
            return
        src = os.path.abspath(src)
        dest = os.path.abspath(dest)
        if not path_inside(self.root, src) or not path_inside(self.root, dest):
            self._copy_error_dialog(os.path.basename(src),
                                    "the source or destination is outside the project root.")
            return
        if not os.path.exists(src) or not os.path.isdir(dest):
            return
        target = os.path.join(dest, os.path.basename(src))
        if os.path.realpath(src) == os.path.realpath(target):
            return
        if os.path.exists(target):
            self._copy_error_dialog(os.path.basename(src), "a file with that name already exists.")
            return
        if os.path.isdir(src) and not self._copy_dest_safe(src, target):
            self._copy_error_dialog(os.path.basename(src))
            return
        try:
            os.rename(src, target)
        except OSError as ex:
            print("Move error:", ex)
            return
        for doc, new_path in doc_relocator(self.docs.values(), src, target).items():
            self._migrate_doc_path(doc, new_path)
            self._update_tab_ui(doc.buffer)
        self.watch_path(dest)
        self.refresh_tree()
        self.select_path(target)

    def on_root_drop(self, w, ctx, x, y, data, info, time):
        if self._branch_busy():
            ctx.finish(False, False, time)
            return
        if data and data.get_uris() and self._copy_uris(data.get_uris(),
                                                          self.root):
            self._do_refresh()
        ctx.finish(True, False, time)

    def delete_selected(self):
        if self._branch_busy():
            return
        sel = self.tree.get_selection().get_selected()
        if not sel[1]:
            return
        fpath = self.store.get_value(sel[1], 2)
        if not fpath or not os.path.exists(fpath):
            return
        kind = "folder" if os.path.isdir(fpath) else "file"
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.YES_NO,
                                text="Delete %s" % kind,
                                secondary_text="Delete %s '%s' permanently?"
                                               % (kind, os.path.basename(fpath)))
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.YES:
            return
        affected = []
        if kind == "folder":
            affected = docs_under(self.docs.values(), fpath)
        else:
            entry = self.ed_paths.get(fpath)
            if entry:
                doc = self.docs.get(entry[0])
                if doc is not None:
                    affected = [doc]
        for doc in affected:
            if self._try_close_doc(doc, doc.path) == 'abort':
                return
        try:
            if kind == "folder":
                shutil.rmtree(fpath)
            else:
                os.remove(fpath)
        except OSError as ex:
            print("Error:", ex)
            return
        for doc in affected:
            self.close_file_tab(None, doc.path, quiet=True)
        self.close_file_tab(None, fpath, quiet=True)
        self.refresh_tree()

    # ---------------- visores ----------------
    def open_file(self, fpath):
        if self._branch_busy():
            # Git may be rewriting this file right now. Reading the
            # intermediate bytes would show a half-checked-out document.
            return
        ext = fpath.rsplit(".", 1)[-1].lower() if "." in os.path.basename(fpath) else ""
        if ext in CSV_EXT:
            self.open_table(fpath); return
        if ext in IMG_EXT:
            self.open_image(fpath); return
        if ext == "pdf" and HAS_POPPLER:
            self.open_pdf(fpath); return
        if ext in AUD_EXT and HAS_GST:
            self.open_audio(fpath); return
        self.open_text(fpath)

    def make_tab(self, widget, fpath, content_widget):
        lbl = Gtk.Label(os.path.basename(fpath))
        close = icon_button("close", "Close file")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_focus_on_click(False)
        close.connect("clicked", self.close_file_tab, fpath)
        tab = Gtk.Box(spacing=8)
        tab.pack_start(lbl, False, False, 0)
        tab.pack_start(close, False, False, 0)
        tab.show_all()
        self.open_widgets[fpath] = content_widget
        self.tab_labels[content_widget] = lbl
        self.ed_tabs.append_page(widget, tab)
        self.ed_tabs.set_current_page(self.ed_tabs.page_num(widget))
        self.editor_pane.show()
        self._apply_editor_visibility()
        self.update_compact()

    def open_text(self, fpath):
        if fpath in self.ed_paths:
            buf, page = self.ed_paths[fpath]
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(page))
            self.editor_pane.show_all()
            return
        try:
            size = os.path.getsize(fpath)
        except OSError as ex:
            print("Could not open:", ex)
            return
        if size > MAX_LARGE:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="File too large to open in the editor",
                                    secondary_text="%.1f MB (%s). Open it externally?"
                                                   % (size / 1048576, os.path.basename(fpath)))
            dlg.add_button("Open externally", Gtk.ResponseType.YES)
            dlg.add_button("Cancel", Gtk.ResponseType.NO)
            resp = dlg.run()
            dlg.destroy()
            if resp == Gtk.ResponseType.YES:
                try:
                    subprocess.Popen(["xdg-open", fpath],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            return
        readonly = False
        if size > WARN_LARGE:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="Large file: %s" % os.path.basename(fpath),
                                    secondary_text="%.1f MB. Open read-only?"
                                                   % (size / 1048576))
            dlg.add_button("Open read-only", Gtk.ResponseType.YES)
            dlg.add_button("Cancel", Gtk.ResponseType.NO)
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.YES:
                return
            readonly = True
        try:
            with open(fpath, 'rb') as f:
                sample = f.read(8192)
        except OSError as ex:
            print("Could not open:", ex)
            return
        if b"\x00" in sample:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="Binary file: %s" % os.path.basename(fpath),
                                    secondary_text="This file cannot be edited as text "
                                                   "(it would corrupt the file). Open it externally?")
            dlg.add_button("Open externally", Gtk.ResponseType.YES)
            dlg.add_button("Cancel", Gtk.ResponseType.NO)
            resp = dlg.run()
            dlg.destroy()
            if resp == Gtk.ResponseType.YES:
                try:
                    subprocess.Popen(["xdg-open", fpath],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            return
        valid_utf8 = True
        try:
            sample.decode('utf-8')
        except UnicodeDecodeError:
            valid_utf8 = False
        if not valid_utf8:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="Encoding: %s" % os.path.basename(fpath),
                                    secondary_text="The file does not appear to be valid UTF-8. "
                                                   "It will be opened read-only to avoid "
                                                   "corrupting it.")
            dlg.add_button("Open read-only", Gtk.ResponseType.YES)
            dlg.add_button("Open externally", Gtk.ResponseType.NO)
            dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
            resp = dlg.run()
            dlg.destroy()
            if resp == Gtk.ResponseType.NO:
                try:
                    subprocess.Popen(["xdg-open", fpath],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                return
            if resp != Gtk.ResponseType.YES:
                return
            readonly = True
        try:
            if valid_utf8:
                with open(fpath, 'r', encoding='utf-8') as f:
                    text = f.read()
            else:
                with open(fpath, 'r', errors='replace') as f:
                    text = f.read()
        except OSError as ex:
            print("Could not open:", ex)
            return
        buffer = GtkSource.Buffer()
        buffer.set_text(text)
        buffer.set_language(self.lang_mgr.guess_language(fpath, None))
        if self.dark_scheme:
            buffer.set_style_scheme(self.dark_scheme)
        view = GtkSource.View.new_with_buffer(buffer)
        view.set_show_line_numbers(True)
        view.set_insert_spaces_instead_of_tabs(True)
        view.set_tab_width(4)
        view.set_highlight_current_line(True)
        view.modify_font(Pango.FontDescription("Monospace 10"))
        if readonly:
            view.set_editable(False)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        scroll.show_all()
        self.ed_paths[fpath] = (buffer, scroll)
        buffer.connect("changed", self.on_buffer_changed)
        self.make_tab(scroll, fpath, scroll)
        doc = DocumentState(fpath, buffer, GLib.timeout_add, GLib.source_remove,
                            self._autosave_buffer, strict_utf8=valid_utf8)
        doc.snapshot_from_disk()
        self.docs[buffer] = doc
        self._update_tab_ui(buffer)

    def open_table(self, fpath):
        if fpath in self.open_widgets:
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(self.open_widgets[fpath]))
            self.editor_pane.show_all()
            return
        try:
            size = os.path.getsize(fpath)
        except OSError as ex:
            print("Error:", ex)
            return
        if size > MAX_LARGE:
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.WARNING,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="CSV too large to open in the editor",
                                    secondary_text="%.1f MB (%s). Open it externally?"
                                                   % (size / 1048576, os.path.basename(fpath)))
            dlg.add_button("Open externally", Gtk.ResponseType.YES)
            dlg.add_button("Cancel", Gtk.ResponseType.NO)
            resp = dlg.run()
            dlg.destroy()
            if resp == Gtk.ResponseType.YES:
                try:
                    subprocess.Popen(["xdg-open", fpath],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            return
        try:
            csv.field_size_limit(4 * 1024 * 1024)
        except Exception:
            pass
        delim = '\t' if fpath.rsplit(".", 1)[-1].lower() == "tsv" else ','
        try:
            with open(fpath, newline='', errors='replace') as f:
                reader = csv.reader(f, delimiter=delim)
                rows = list(islice(reader, 20001))
        except csv.Error as ex:
            print("CSV error:", ex)
            dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                    message_type=Gtk.MessageType.ERROR,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="Malformed CSV: %s" % os.path.basename(fpath),
                                    secondary_text="The file could not be parsed as a table. "
                                                   "View it as text?")
            dlg.add_button("View as text", Gtk.ResponseType.YES)
            dlg.add_button("Cancel", Gtk.ResponseType.NO)
            resp = dlg.run()
            dlg.destroy()
            if resp == Gtk.ResponseType.YES:
                self.open_text(fpath)
            return
        except OSError as ex:
            print("Error:", ex)
            return
        if not rows:
            return self.open_text(fpath)
        truncated = len(rows) > 20000
        if truncated:
            rows = rows[:20000]
        ncols = min(max(len(r) for r in rows[:500]), 60)
        store = Gtk.ListStore.new([str] * ncols)
        for r in rows[:20000]:
            pad = list(r[:ncols]) + [""] * (ncols - len(r))
            store.append(pad)
        tv = Gtk.TreeView(model=store)
        tv.set_headers_visible(True)
        for i in range(ncols):
            ren = Gtk.CellRendererText()
            ren.set_property("background", CSV_COLORS[i % len(CSV_COLORS)])
            c = Gtk.TreeViewColumn(str(rows[0][i]) if i < len(rows[0]) else "", ren, text=i)
            tv.append_column(c)
        scroll = Gtk.ScrolledWindow()
        scroll.add(tv)
        scroll.show_all()
        btn_text = icon_button(
            "files", "View CSV as text",
            lambda w, p=fpath: self.text_from_table(p),
            label="Text")
        bar = Gtk.Box(spacing=4)
        bar.get_style_context().add_class("viewer-toolbar")
        bar.pack_start(btn_text, False, False, 4)
        if truncated:
            note = Gtk.Label(label="Showing first 20,000 rows", xalign=0)
            note.get_style_context().add_class("secondary-label")
            bar.pack_start(note, False, False, 4)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(bar, False, False, 2)
        vbox.pack_start(scroll, True, True, 0)
        vbox.show_all()
        self.make_tab(vbox, fpath, vbox)

    def text_from_table(self, fpath):
        self.close_file_tab(None, fpath, quiet=True)
        self.open_text(fpath)

    def open_image(self, fpath):
        if fpath in self.open_widgets:
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(self.open_widgets[fpath]))
            self.editor_pane.show_all()
            return
        try:
            info = GdkPixbuf.Pixbuf.get_file_info(fpath)
            w0 = info[1] if info else 0
            h0 = info[2] if info else 0
            if w0 and h0 and w0 * h0 > 100_000_000:
                dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                        message_type=Gtk.MessageType.WARNING,
                                        buttons=Gtk.ButtonsType.NONE,
                                        text="Image too large to display",
                                        secondary_text="%dx%d px (%s). Open it externally?"
                                                       % (w0, h0, os.path.basename(fpath)))
                dlg.add_button("Open externally", Gtk.ResponseType.YES)
                dlg.add_button("Cancel", Gtk.ResponseType.NO)
                resp = dlg.run()
                dlg.destroy()
                if resp == Gtk.ResponseType.YES:
                    try:
                        subprocess.Popen(["xdg-open", fpath],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except Exception:
                        pass
                return
            if w0 and h0 and max(w0, h0) > 2200:
                s = 2200 / max(w0, h0)
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(fpath, int(w0 * s),
                                                             int(h0 * s), True)
            else:
                pb = GdkPixbuf.Pixbuf.new_from_file(fpath)
        except Exception as ex:
            print("Image error:", ex)
            return self.open_text(fpath)
        img = Gtk.Image.new_from_pixbuf(pb)
        img.set_halign(Gtk.Align.CENTER)
        img.set_valign(Gtk.Align.CENTER)
        scroll = Gtk.ScrolledWindow()
        scroll.add_with_viewport(img)
        scroll.show_all()
        self.make_tab(scroll, fpath, scroll)

    def open_pdf(self, fpath):
        if fpath in self.open_widgets:
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(self.open_widgets[fpath]))
            self.editor_pane.show_all()
            return
        try:
            doc = Poppler.Document.new_from_file("file://" + fpath, None)
        except Exception as ex:
            print("PDF error:", ex)
            return self.open_text(fpath)
        if doc is None:
            return self.open_text(fpath)
        img = Gtk.Image()
        scroll = Gtk.ScrolledWindow()
        scroll.add(img)
        scroll.show_all()
        state = {"page": 0, "scale": 1.2, "doc": doc}
        lbl = Gtk.Label("")
        btn_prev = icon_button("previous", "Previous page")
        btn_next = icon_button("next", "Next page")
        btn_zin = icon_button("zoom-in", "Zoom in")
        btn_zout = icon_button("zoom-out", "Zoom out")

        def render():
            p = state["doc"].get_page(state["page"])
            w, h = p.get_size()
            scale = state["scale"]
            if w * h * scale * scale > MAX_PDF_PIXELS:
                scale = math.sqrt(MAX_PDF_PIXELS / (w * h))
            import cairo as _cairo
            surface = _cairo.ImageSurface(_cairo.FORMAT_ARGB32,
                                          max(1, int(w * scale)), max(1, int(h * scale)))
            ctx = _cairo.Context(surface)
            # Opaque paper background: PDFs without an explicit background
            # stay legible on the dark PanelIDE theme.
            ctx.set_source_rgb(1.0, 1.0, 1.0)
            ctx.paint()
            ctx.scale(scale, scale)
            p.render(ctx)
            pb = GdkPixbuf.Pixbuf.new_from_data(
                surface.get_data(), GdkPixbuf.Colorspace.RGB, True, 8,
                int(w * scale), int(h * scale), surface.get_stride())
            img.set_from_pixbuf(pb)
            lbl.set_text("Page %d/%d" % (state["page"] + 1, state["doc"].get_n_pages()))
            scroll.get_vadjustment().set_value(0)

        def prev(_):
            if state["page"] > 0:
                state["page"] -= 1
                render()

        def nxt(_):
            if state["page"] < state["doc"].get_n_pages() - 1:
                state["page"] += 1
                render()

        def zin(_):
            state["scale"] = min(state["scale"] * 1.25, 5)
            render()

        def zout(_):
            state["scale"] = max(state["scale"] / 1.25, 0.4)
            render()

        btn_prev.connect("clicked", prev)
        btn_next.connect("clicked", nxt)
        btn_zin.connect("clicked", zin)
        btn_zout.connect("clicked", zout)
        bar = Gtk.Box(spacing=4)
        bar.get_style_context().add_class("viewer-toolbar")
        for b in (btn_prev, btn_next, btn_zin, btn_zout):
            bar.pack_start(b, False, False, 2)
        bar.pack_start(lbl, False, False, 8)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(bar, False, False, 2)
        vbox.pack_start(scroll, True, True, 0)
        vbox.show_all()
        self.make_tab(vbox, fpath, vbox)
        render()

    def open_audio(self, fpath):
        if fpath in self.open_widgets:
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(self.open_widgets[fpath]))
            self.editor_pane.show_all()
            return
        player = Gst.ElementFactory.make("playbin", None)
        player.set_property("uri", "file://" + fpath)
        self.players.append(player)
        for p in self.players[:-1]:
            try:
                p.set_state(Gst.State.READY)
            except Exception:
                pass
        btn_play = icon_button("play", "Play audio", toggle=True)
        btn_stop = icon_button("stop", "Stop audio")
        btn_mute = icon_button("volume", "Mute audio", toggle=True)
        scale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, Gtk.Adjustment(0, 0, 1, 0.1, 1, 0))
        scale.set_draw_value(False)
        scale.set_size_request(320, 24)
        lbl_time = Gtk.Label("00:00 / 00:00")
        lbl_time.get_style_context().add_class("secondary-label")
        title_lbl = Gtk.Label(label=os.path.basename(fpath), xalign=0.5)
        title_lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)

        def on_play(b):
            if b.get_active():
                player.set_state(Gst.State.PLAYING)
            else:
                player.set_state(Gst.State.PAUSED)

        def on_stop(b):
            btn_play.set_active(False)
            player.set_state(Gst.State.READY)
            scale.set_value(0)
            lbl_time.set_text("00:00 / 00:00")

        def on_mute(b):
            muted = b.get_active()
            player.set_property("mute", muted)
            set_button_icon(b, "mute" if muted else "volume")
            b.set_tooltip_text("Unmute audio" if muted else "Mute audio")

        btn_play.connect("toggled", on_play)
        btn_stop.connect("clicked", on_stop)
        btn_mute.connect("toggled", on_mute)
        scale.connect("change-value", lambda s, t, v, p=player: (
            p.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH, int(v * Gst.SECOND)) or True))
        bus = player.get_bus()
        bus.add_signal_watch()

        def on_eos(bus, msg, btn=btn_play, lbl=lbl_time):
            if msg.type == Gst.MessageType.EOS:
                btn.set_active(False)
                player.set_state(Gst.State.READY)
                lbl.set_text("00:00 / 00:00")
        handler_id = bus.connect("message", on_eos)

        def update():
            okp, pos = player.query_position(Gst.Format.TIME)
            okd, dur = player.query_duration(Gst.Format.TIME)
            if okp and okd and dur > 0:
                scale.set_range(0, dur / Gst.SECOND)
                scale.set_value(pos / Gst.SECOND)
                lbl_time.set_text("%02d:%02d / %02d:%02d" % (
                    pos // Gst.SECOND // 60, pos // Gst.SECOND % 60,
                    dur // Gst.SECOND // 60, dur // Gst.SECOND % 60))
            elif okp:
                lbl_time.set_text("%02d:%02d" % (pos // Gst.SECOND // 60, pos // Gst.SECOND % 60))
            return True
        timer_id = GLib.timeout_add(400, update)
        transport = Gtk.Box(spacing=6)
        transport.set_halign(Gtk.Align.CENTER)
        transport.pack_start(btn_play, False, False, 2)
        transport.pack_start(btn_stop, False, False, 2)
        transport.pack_start(btn_mute, False, False, 2)
        seek = Gtk.Box(spacing=6)
        seek.set_halign(Gtk.Align.CENTER)
        seek.pack_start(scale, False, False, 4)
        seek.pack_start(lbl_time, False, False, 4)
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        center.set_halign(Gtk.Align.CENTER)
        center.set_valign(Gtk.Align.CENTER)
        center.set_hexpand(True)
        center.set_vexpand(True)
        center.pack_start(title_lbl, False, False, 0)
        center.pack_start(transport, False, False, 0)
        center.pack_start(seek, False, False, 0)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(center, True, True, 0)
        vbox.show_all()
        self.audio_state[vbox] = (player, timer_id, bus, handler_id)
        self.make_tab(vbox, fpath, vbox)

    def _cleanup_audio_widget(self, widget):
        astate = self.audio_state.pop(widget, None)
        if not astate:
            return
        player, timer_id, bus, handler_id = astate
        if timer_id:
            GLib.source_remove(timer_id)
        try:
            bus.remove_signal_watch()
            bus.disconnect(handler_id)
            player.set_state(Gst.State.NULL)
        except Exception:
            pass
        if player in self.players:
            self.players.remove(player)

    def close_file_tab(self, btn, fpath, quiet=False):
        if not quiet and self._branch_busy():
            return
        entry = self.ed_paths.get(fpath)
        doc = self.docs.get(entry[0]) if entry else None
        if doc is not None:
            if not quiet and self._try_close_doc(doc, fpath) == 'abort':
                return
            fpath = doc.path
        widget = self.open_widgets.pop(fpath, None)
        if widget:
            self.ed_tabs.remove_page(self.ed_tabs.page_num(widget))
        entry = self.ed_paths.pop(fpath, None)
        if entry:
            self.docs.pop(entry[0], None)
        if widget:
            self.tab_labels.pop(widget, None)
            self._cleanup_audio_widget(widget)
        self._apply_editor_visibility()
        self.update_compact()

    def on_top_alloc(self, paned, alloc):
        if self.layout == "compact":
            if not self._compact_tabbed and alloc.width > 50:
                # One file open: keep both panes above a fixed minimum so a
                # narrow column stays readable instead of collapsing one side.
                minimum = min(mt_ui.PANEL_TOP_MIN_PX, alloc.width // 3)
                editor = max(minimum, min(alloc.width - minimum,
                                         int(alloc.width * 0.62)))
                if abs(paned.get_position() - editor) > 30:
                    paned.set_position(editor)
            return
        if self.editor_pane.get_visible() and self._term_visible():
            half = alloc.width // 2
            if abs(paned.get_position() - half) > 30:
                paned.set_position(half)
        elif paned.get_position() > 0:
            paned.set_position(0)

    # ---------------- barra de herramientas ----------------
    def copy_path(self, btn=None):
        try:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.root, -1)
        except Exception:
            pass

    def open_in_fm(self, btn=None):
        try:
            subprocess.Popen(["xdg-open", self.root],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # ---------------- git branch switcher ----------------
    def _make_branch_button(self):
        btn = Gtk.Button()
        context = btn.get_style_context()
        context.add_class("chrome")
        context.add_class("icon-btn")
        context.add_class("branch-btn")
        inner = Gtk.Box(spacing=5)
        icon = Gtk.Image()
        path = os.path.join(UI_ICON_DIR, "neutral", "git-branch.svg")
        try:
            icon.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(
                path, 16, 16, True))
        except Exception:
            pass
        arrow = Gtk.Image()
        arrow_path = os.path.join(UI_ICON_DIR, "neutral", "chevron-down.svg")
        try:
            arrow.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(
                arrow_path, 10, 10, True))
        except Exception:
            pass
        lbl = Gtk.Label(xalign=0)
        lbl.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        lbl.set_max_width_chars(18)
        inner.pack_start(icon, False, False, 0)
        inner.pack_start(lbl, True, True, 0)
        inner.pack_end(arrow, False, False, 0)
        btn.add(inner)
        btn.set_tooltip_text("Git branch")
        btn.connect("clicked", self.on_branch_click)
        return btn, lbl

    def _branch_paint(self):
        btn = getattr(self, "branch_btn", None)
        if btn is None:
            return
        info = self.git_info or {}
        legend = getattr(self, "local_legend", None)
        if not info.get("is_repo"):
            btn.set_no_show_all(True)
            btn.hide()
            if legend is not None:
                legend.set_no_show_all(True)
                legend.hide()
            return
        base_name = ide_git.label(info)
        name = base_name
        if info.get("unborn"):
            # The label must not imply that the branch has a commit: on an
            # unborn HEAD the name is not a ref yet and cannot be switched
            # back to until the first commit exists.
            name = "%s · no commits" % base_name
        self.branch_lbl.set_text(name)
        self.branch_lbl.set_tooltip_text(name)
        context = btn.get_style_context()
        context.remove_class("branch-detached")
        if info.get("detached"):
            context.add_class("branch-detached")
        tip = ["Git branch: %s" % base_name]
        if info.get("unborn"):
            tip.append("No commits yet on this branch.")
        if info.get("detached"):
            tip.append("Detached HEAD: not on a branch.")
        if info.get("dirty"):
            tip.append("Tracked files have uncommitted changes.")
        summary = ide_tree.local_summary(self._worktree_state)
        if summary:
            tip.append(summary)
        tip.append("Open editors are re-checked after switching; unsaved "
                   "edits are never discarded without asking.")
        tip.append("Click to switch branch.")
        btn.set_tooltip_text("\n".join(tip))
        btn.set_no_show_all(False)
        btn.show_all()
        if legend is not None:
            legend.set_no_show_all(False)
            legend.show()

    def _branch_refresh(self, *args, reconcile=True):
        """Fetch branch information off the GTK thread.

        ``git status`` walks the working tree and can take seconds on a
        large repository. The worker keeps the window responsive; the
        result is applied in one idle callback.
        """
        if getattr(self, "_shutdown", False) or self._branch_op:
            return False
        if self._branch_info_busy:
            # A refresh requested while one is in flight must still run,
            # otherwise a switch that finished after the snapshot would
            # leave the old branch label on screen.
            self._branch_info_pending = True
            if not reconcile:
                self._branch_info_reconcile = False
            return False
        self._branch_info_busy = True
        self._branch_info_pending = False
        self._branch_info_reconcile = reconcile
        self._branch_info_gen += 1
        generation = self._branch_info_gen

        def worker():
            try:
                info = ide_git.snapshot(self.root)
                names = (ide_git.branches(self.root)
                         if info.get("is_repo") else [])
            except Exception:
                info = {"is_repo": False}
                names = []
            GLib.idle_add(self._apply_branch_info, generation, info,
                          names, reconcile)

        import threading
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _invalidate_branch_info(self):
        """Discard an in-flight branch snapshot after Git changed HEAD."""
        self._branch_info_gen += 1
        self._branch_info_busy = False
        self._branch_info_pending = False

    def _apply_branch_info(self, generation, info, names, reconcile):
        if generation != self._branch_info_gen:
            # A newer request is authoritative; this result is stale.
            return False
        self._branch_info_busy = False
        if getattr(self, "_shutdown", False):
            return False
        if self._branch_op:
            # The snapshot may describe a half-finished checkout. The
            # post-operation refresh will request a fresh one.
            self._branch_info_pending = True
            return False
        self._branch_names = names
        self._apply_branch_snapshot(info, reconcile)
        if self._branch_info_pending:
            pending_reconcile = self._branch_info_reconcile
            self._branch_info_pending = False
            self._branch_refresh(reconcile=pending_reconcile)
        return False

    def _apply_branch_snapshot(self, info, reconcile=True):
        previous = self.git_info or {}
        self.git_info = info
        if info.get("is_repo"):
            branch_changed = (not previous.get("is_repo")
                              or previous.get("branch") != info.get("branch")
                              or previous.get("head") != info.get("head")
                              or previous.get("unborn") != info.get("unborn"))
            if branch_changed or self._worktree_state_root != self.root:
                self._worktree_state_for(self.root, force=True)
            else:
                # Refresh through the TTL cache on focus: an external
                # `git add`/ignore-rule edit may have changed badges even
                # though HEAD did not move.
                self._worktree_state_for(self.root)
            if not self._tree_git_ready or branch_changed:
                if (branch_changed and self._tree_git_ready and reconcile
                        and self.docs):
                    self._reconcile_open_docs_external()
                self._do_refresh()
                self._tree_git_ready = True
        else:
            had_state = self._worktree_state is not None
            self._tree_git_ready = False
            self._worktree_state = None
            self._worktree_state_root = None
            self._state_cache.pop(os.path.normpath(self.root), None)
            if had_state:
                self._do_refresh()
        self._branch_paint()
        return False

    def on_branch_click(self, btn):
        if self._branch_op:
            return
        # Only HEAD information and ref names are needed to build the menu.
        # Skipping the dirty-status scan keeps this synchronous path cheap
        # even on a huge working tree.
        try:
            info = ide_git.snapshot(self.root, check_dirty=False)
        except Exception:
            info = self.git_info or {}
        if not info.get("is_repo"):
            return
        try:
            names = ide_git.branches(self.root)
        except Exception:
            names = []
        self._branch_names = names
        self._show_branch_menu(info)
        # Refresh the full snapshot (including dirty state) in the
        # background; if HEAD changed externally, this also reconciles
        # open editors and rebuilds the tree.
        self._branch_refresh()

    def _show_branch_menu(self, info):
        current = info.get("branch") if not info.get("detached") else None
        self._branch_menu_current = current
        names = list(self._branch_names)
        if current and current not in names:
            names.insert(0, current)
        elif current in names:
            names.remove(current)
            names.insert(0, current)
        menu = Gtk.Menu()
        summary = ide_tree.local_summary(self._worktree_state, compact=True)
        if summary:
            item = Gtk.MenuItem(label=summary + " stay on disk")
            item.set_sensitive(False)
            menu.append(item)
            menu.append(Gtk.SeparatorMenuItem())
        if info.get("unborn"):
            item = Gtk.MenuItem(
                label="No commits yet: make the first commit or create a branch")
            item.set_sensitive(False)
            item.set_tooltip_text(
                "The current name is not a Git ref until the first commit. "
                "Creating a branch replaces this name; it cannot be "
                "switched back to until it has a commit.")
            menu.append(item)
            menu.append(Gtk.SeparatorMenuItem())
        for name in names:
            item = Gtk.CheckMenuItem(label=name)
            item.set_draw_as_radio(True)
            item.set_active(name == current)
            item.connect("activate", self._on_branch_selected, name)
            menu.append(item)
        if not names:
            item = Gtk.MenuItem(label="No local branches yet")
            item.set_sensitive(False)
            menu.append(item)
        menu.append(Gtk.SeparatorMenuItem())
        item = Gtk.MenuItem(label="New branch…")
        item.connect("activate", lambda w: self._new_branch_dialog(info))
        menu.append(item)
        item = Gtk.MenuItem(label="Refresh")
        item.connect("activate", lambda w: self._branch_refresh())
        menu.append(item)
        menu.show_all()
        menu.popup_at_widget(self.branch_btn, Gdk.Gravity.SOUTH_WEST,
                             Gdk.Gravity.NORTH_WEST, None)

    def _on_branch_selected(self, item, name):
        current = getattr(self, "_branch_menu_current", None)
        if current is None:
            current = (self.git_info or {}).get("branch")
        if name == current:
            return
        self._switch_branch(name)

    def _pause_docs_for_branch(self):
        """Cancel autosave before Git runs; return ``(doc, path)`` pairs.

        Digests are computed in the branch worker, not here: hashing every
        open buffer on the GTK thread would freeze the window on large
        files. Dirty buffers stay dirty: if the branch changes their file,
        the user gets a conflict decision instead of an implicit overwrite.
        """
        paused = []
        for doc in list(self.docs.values()):
            doc.cancel_autosave()
            paused.append((doc, doc.path))
        return paused

    def _snapshot_docs_after_branch(self, prepared):
        """Worker-side disk snapshots/digests after Git finishes."""
        if getattr(self, "_shutdown", False):
            # Shutdown is waiting for this thread; do not spend time hashing
            # large buffers when the result can no longer be applied.
            return prepared
        observed = []
        for doc, path, before in prepared:
            disk = ide_branch_sync.disk_snapshot(path)
            after = (ide_branch_sync.file_digest(path)
                     if disk is not None and before is not None else None)
            observed.append((doc, path, before, disk, after))
        return observed

    def _resume_docs_after_branch(self, prepared, safe=None):
        """Re-arm autosave only for documents explicitly verified safe.

        ``safe`` is the set of buffer identities returned by
        :meth:`_reconcile_docs_after_branch`. Anything else stays paused,
        even if the reconciliation loop failed halfway through.
        """
        for item in prepared:
            doc = item[0]
            if self.docs.get(doc.buffer) is not doc:
                continue
            try:
                if safe is not None and doc.buffer not in safe:
                    self._update_tab_ui(doc.buffer)
                    continue
                doc.resume_autosave()
                self._update_tab_ui(doc.buffer)
            except Exception as ex:
                # If re-arming itself fails, fail closed rather than leave
                # a half-configured document able to write.
                try:
                    doc.mark_unsafe("could not re-arm autosave: %s" % ex)
                    self._update_tab_ui(doc.buffer)
                except Exception:
                    pass

    def _disk_text_for_doc(self, doc):
        try:
            if doc.strict_utf8:
                with open(doc.path, 'r', encoding='utf-8') as f:
                    return f.read()
            with open(doc.path, 'r', errors='replace') as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return None

    def _reconcile_failure_dialog(self, problems):
        """Offer explicit resolutions when disk state could not be verified."""
        unique = []
        seen = set()
        for doc, reason in problems:
            if self.docs.get(doc.buffer) is not doc:
                continue
            if doc.buffer in seen:
                continue
            seen.add(doc.buffer)
            unique.append((doc, reason))
        if not unique:
            return set()
        names = [os.path.basename(doc.path) for doc, _ in unique]
        shown = "\n".join(names[:6])
        if len(names) > 6:
            shown += "\n… and %d more" % (len(names) - 6)
        try:
            dlg = Gtk.MessageDialog(
                transient_for=self.get_toplevel(), modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text="Autosave paused for %d open file(s)" % len(unique),
                secondary_text=(
                    "Git finished, but PanelIDE could not verify the disk "
                    "state of:\n%s\n\nAutosave stays off so an editor "
                    "buffer cannot overwrite newer disk content. Reloading "
                    "discards the editor version; keeping it will overwrite "
                    "the file on the next save." % shown))
            dlg.add_button("Keep autosave paused", Gtk.ResponseType.CANCEL)
            dlg.add_button("Reload from disk", Gtk.ResponseType.YES)
            keep_btn = dlg.add_button("Keep editor version",
                                      Gtk.ResponseType.NO)
            keep_btn.get_style_context().add_class("destructive-action")
            dlg.set_default_response(Gtk.ResponseType.CANCEL)
            resp = dlg.run()
            dlg.destroy()
        except Exception:
            return set()
        explicit = set()
        for doc, _reason in unique:
            if self.docs.get(doc.buffer) is not doc:
                continue
            try:
                if resp == Gtk.ResponseType.YES:
                    if not self.reload_buffer(doc.buffer, doc.path):
                        doc.mark_unsafe("the file could not be read from disk")
                        self._update_tab_ui(doc.buffer)
                elif resp == Gtk.ResponseType.NO:
                    # Explicit, destructive decision by the user. A clean
                    # buffer has no divergent editor version to keep, so do
                    # not let this choice trigger an immediate overwrite.
                    if doc.dirty:
                        doc.resolve_keep_local()
                        self._update_tab_ui(doc.buffer)
                        explicit.add(doc.buffer)
            except Exception as ex:
                try:
                    doc.mark_unsafe("resolution failed: %s" % ex)
                    self._update_tab_ui(doc.buffer)
                except Exception:
                    pass
        return explicit

    def _reconcile_open_docs_external(self):
        prepared = [(doc, doc.path, None) for doc in list(self.docs.values())]
        safe = self._reconcile_docs_after_branch(prepared)
        self._resume_docs_after_branch(prepared, safe)

    def _reconcile_docs_after_branch(self, prepared, strict=False):
        """Reconcile open buffers after Git (or an external branch change).

        Returns the set of buffer identities that were verified and may
        safely re-arm autosave. Any exception or unverifiable read leaves
        the document conflicted/unsafe, keeps its buffer intact, and does
        not add it to the safe set.

        ``strict`` is used after PanelIDE's own switch/create: a dirty
        document with no pre-operation digest is not resumed automatically,
        because there is no trustworthy baseline to detect an external
        rewrite that happened during the operation.
        """
        safe = set()
        conflicts = []
        problems = []
        for item in prepared:
            doc = item[0]
            path = item[1]
            before = item[2]
            try:
                if self.docs.get(doc.buffer) is not doc:
                    continue
                doc.cancel_autosave()
                if doc.path != path:
                    reason = "the document path changed during the operation"
                    doc.mark_unsafe(reason)
                    self._update_tab_ui(doc.buffer)
                    problems.append((doc, reason))
                    continue

                precomputed = len(item) >= 5
                if precomputed:
                    disk_after_op, after = item[3], item[4]
                else:
                    disk_after_op, after = None, None

                # Re-stat at decision time. The worker snapshot may be
                # older than the moment autosave would be re-armed; if the
                # file changed in between, its digest cannot be trusted.
                disk = ide_branch_sync.disk_snapshot(path)
                if precomputed and disk != disk_after_op:
                    after = None
                    action = ide_branch_sync.reconcile_action(
                        doc.dirty, doc.conflict, doc.deleted,
                        disk is not None, before_digest=None,
                        after_digest=None, snapshot_changed=True)
                else:
                    if not precomputed:
                        after = (ide_branch_sync.file_digest(path)
                                 if disk is not None and before is not None
                                 else None)
                    snapshot_changed = (disk is not None
                                        and doc.saved_snap != disk)
                    action = ide_branch_sync.reconcile_action(
                        doc.dirty, doc.conflict, doc.deleted,
                        disk is not None, before_digest=before,
                        after_digest=after,
                        snapshot_changed=snapshot_changed)

                if (before is None and not doc.dirty and not doc.conflict
                        and action in (ide_branch_sync.UNCHANGED,
                                       ide_branch_sync.RELOAD)
                        and disk is not None and disk[1] <= WARN_LARGE):
                    # External switches have no pre-switch digest. Compare
                    # text as a second guard against same-size/same-mtime
                    # rewrites, and avoid a needless reload when Git only
                    # touched the file. The size cap keeps this bounded.
                    disk_text = self._disk_text_for_doc(doc)
                    if disk_text is not None:
                        action = (ide_branch_sync.UNCHANGED
                                  if disk_text == self._doc_text(doc)
                                  else ide_branch_sync.RELOAD)

                if action == ide_branch_sync.UNCHANGED:
                    if not doc.dirty and doc.saved_snap != disk:
                        # A clean buffer whose editor baseline differs from
                        # disk is stale even when the pre/post digests agree
                        # (the external change predates the baseline).
                        # Reload instead of blessing it with a new snapshot.
                        action = ide_branch_sync.RELOAD
                if action == ide_branch_sync.UNCHANGED:
                    if doc.dirty:
                        if before is None and strict:
                            reason = ("no pre-operation content digest was "
                                      "available for automatic verification")
                            doc.mark_unsafe(reason)
                            self._update_tab_ui(doc.buffer)
                            problems.append((doc, reason))
                            continue
                        if doc.saved_snap != disk:
                            # The file was already different from the
                            # editor's last sync before the digest baseline
                            # was taken. Digests alone would call this
                            # "unchanged"; do not autosave over it.
                            was_conflict = doc.conflict
                            doc.mark_conflict()
                            self._update_tab_ui(doc.buffer)
                            if not was_conflict:
                                conflicts.append(doc)
                            continue
                        if before is not None:
                            current = ide_branch_sync.file_digest(path)
                            if current is None:
                                reason = ("the file could not be read for "
                                          "autosave verification")
                                doc.mark_unsafe(reason)
                                self._update_tab_ui(doc.buffer)
                                problems.append((doc, reason))
                                continue
                            if current != before:
                                reason = ("the file changed after the branch "
                                          "operation; autosave was not resumed")
                                doc.mark_unsafe(reason)
                                self._update_tab_ui(doc.buffer)
                                problems.append((doc, reason))
                                continue
                    doc.saved_snap = disk
                    safe.add(doc.buffer)
                    self._update_tab_ui(doc.buffer)
                elif action == ide_branch_sync.DELETED:
                    if not doc.deleted:
                        doc.external_delete()
                    self._update_tab_ui(doc.buffer)
                elif action in (ide_branch_sync.REAPPEARED_RELOAD,
                                ide_branch_sync.REAPPEARED_CONFLICT):
                    doc.deleted = False
                    if action == ide_branch_sync.REAPPEARED_CONFLICT:
                        was_conflict = doc.conflict
                        doc.mark_conflict()
                        self._update_tab_ui(doc.buffer)
                        if not was_conflict:
                            conflicts.append(doc)
                    elif not self.reload_buffer(doc.buffer, doc.path):
                        reason = ("the reappeared file could not be read "
                                  "from disk")
                        doc.mark_unsafe(reason)
                        self._update_tab_ui(doc.buffer)
                        problems.append((doc, reason))
                    else:
                        safe.add(doc.buffer)
                elif action == ide_branch_sync.CONFLICT:
                    was_conflict = doc.conflict
                    doc.mark_conflict()
                    self._update_tab_ui(doc.buffer)
                    if not was_conflict:
                        conflicts.append(doc)
                elif action == ide_branch_sync.RELOAD:
                    if not self.reload_buffer(doc.buffer, doc.path):
                        reason = "the file could not be read from disk"
                        doc.mark_unsafe(reason)
                        self._update_tab_ui(doc.buffer)
                        problems.append((doc, reason))
                    else:
                        safe.add(doc.buffer)
            except Exception as ex:
                reason = "reconciliation failed: %s" % ex
                safe.discard(doc.buffer)
                try:
                    doc.cancel_autosave()
                    doc.mark_unsafe(reason)
                    self._update_tab_ui(doc.buffer)
                except Exception:
                    pass
                problems.append((doc, reason))
        for doc in conflicts:
            if self._conflict_dialog(doc) == "keep":
                # The user explicitly chose the editor version. The timer
                # scheduled by resolve_keep_local may be cancelled while the
                # branch operation is still marked active, so include it in
                # the safe set for the post-operation resume.
                safe.add(doc.buffer)
        if problems:
            safe.update(self._reconcile_failure_dialog(problems) or ())
        return safe

    def _switch_branch(self, name):
        import threading
        if self._branch_op:
            return
        self._cancel_pending_creation()
        self._branch_op = True
        paused = self._pause_docs_for_branch()
        self.branch_lbl.set_text("Switching…")
        self.branch_btn.set_sensitive(False)

        def job():
            prepared = [(doc, path, ide_branch_sync.file_digest(path))
                        for doc, path in paused]
            try:
                ok, message = ide_git.switch_branch(self.root, name)
            except Exception as ex:
                ok, message = False, str(ex)
            try:
                prepared = self._snapshot_docs_after_branch(prepared)
            except Exception:
                # Keep the pre-switch tuples; reconciliation will stat the
                # files on the GTK thread as a fallback.
                pass
            GLib.idle_add(self._branch_done, ok, message, name, "switch",
                          prepared)

        self._branch_thread = threading.Thread(target=job, daemon=True)
        self._branch_thread.start()

    def _create_branch(self, name):
        import threading
        if self._branch_op:
            return
        self._cancel_pending_creation()
        self._branch_op = True
        paused = self._pause_docs_for_branch()
        self.branch_lbl.set_text("Creating…")
        self.branch_btn.set_sensitive(False)

        def job():
            prepared = [(doc, path, ide_branch_sync.file_digest(path))
                        for doc, path in paused]
            try:
                ok, message = ide_git.create_branch(self.root, name)
            except Exception as ex:
                ok, message = False, str(ex)
            try:
                prepared = self._snapshot_docs_after_branch(prepared)
            except Exception:
                # Keep the pre-operation tuples; reconciliation will stat
                # the files again as a fallback.
                pass
            GLib.idle_add(self._branch_done, ok, message, name, "create",
                          prepared)

        self._branch_thread = threading.Thread(target=job, daemon=True)
        self._branch_thread.start()

    def _branch_done(self, ok, message, name, action, prepared=None):
        if getattr(self, "_shutdown", False):
            self._branch_op = False
            return False
        prepared = list(prepared or [])
        # A document can be opened (and edited) while Git is running. It is
        # not in the pre-operation digest list, but it still needs its
        # autosave suspended until it can be reconciled too.
        known = {id(item[0]) for item in prepared}
        for doc in list(self.docs.values()):
            if id(doc) not in known:
                doc.cancel_autosave()
                prepared.append((doc, doc.path, None))
        safe = set()
        try:
            if prepared:
                # Reconcile switch and create alike: monitor events are
                # ignored while either operation runs, so both can hide an
                # external write or a post-checkout hook changing files.
                safe = self._reconcile_docs_after_branch(prepared,
                                                         strict=True)
        except Exception as ex:
            # Fail closed. Nothing from this batch is allowed to re-arm
            # autosave; keep every open buffer exactly as the user left it.
            reason = "branch reconciliation failed: %s" % ex
            print(reason)
            for item in prepared:
                doc = item[0]
                if self.docs.get(doc.buffer) is not doc:
                    continue
                try:
                    doc.cancel_autosave()
                    doc.mark_unsafe(reason)
                    self._update_tab_ui(doc.buffer)
                except Exception:
                    pass
            try:
                safe.update(self._reconcile_failure_dialog(
                    [(item[0], reason) for item in prepared]) or ())
            except Exception:
                pass
        finally:
            self._branch_op = False
        self._invalidate_branch_info()
        # Only verified documents are re-armed. Failed/conflicted docs keep
        # autosave suspended until the user resolves them explicitly.
        self._resume_docs_after_branch(prepared, safe)
        self.branch_btn.set_sensitive(True)
        # Refresh after switch and create alike: either can move HEAD, run
        # checkout hooks, or leave a partial working tree after a failure.
        self._refresh_after_branch()
        if not ok:
            self._branch_error_dialog(name, message, action)
        return False

    def _refresh_after_branch(self):
        """Resync tree, branch label and local-content state immediately."""
        if self._refresh_id:
            try:
                GLib.source_remove(self._refresh_id)
            except Exception:
                pass
            self._refresh_id = None
        # Git may have replaced files or folders anywhere in the work tree
        # while monitor events were ignored. Do not trust any cached
        # classification, including nested repositories.
        self._state_cache.clear()
        self._worktree_state = None
        self._worktree_state_at = 0.0
        self._worktree_state_root = None
        self._worktree_state_for(self.root, force=True)
        self._do_refresh()
        self._tree_git_ready = bool((self.git_info or {}).get("is_repo"))
        self._branch_paint()
        # The HEAD snapshot (and its status scan) runs in the background.
        # Passing reconcile=False avoids asking twice about the same switch.
        self._branch_refresh(reconcile=False)

    def _branch_error_dialog(self, name, message, action):
        if action == "create":
            text = "Could not create branch “%s”" % name
        else:
            text = "Could not switch to “%s”" % name
        secondary = message or "Git returned an error without details."
        low = (message or "").lower()
        if ("would be overwritten" in low
                or "untracked working tree files" in low
                or "would lose untracked files" in low):
            secondary += ("\n\nGit stopped before overwriting local files. "
                          "Nothing was overwritten; move, commit, or stash "
                          "those files and try again.")
        elif action == "switch":
            secondary += ("\n\nPanelIDE does not delete untracked or ignored "
                          "files; the working tree is left as Git returned "
                          "it. Git can still replace an empty folder when "
                          "the target branch has a file at the same path.")
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.CLOSE,
                                text=text)
        dlg.get_style_context().add_class("branch-dialog")
        dlg.format_secondary_text(secondary)
        dlg.run()
        dlg.destroy()

    def _new_branch_dialog(self, info=None):
        info = info or (self.git_info or {})
        if not info.get("is_repo"):
            return
        dlg = Gtk.Dialog(title="New branch",
                         transient_for=self.get_toplevel(), modal=True)
        dlg.get_style_context().add_class("branch-dialog")
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Create branch", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        dlg.set_default_size(380, -1)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        base = ide_git.label(info)
        lbl = Gtk.Label(xalign=0)
        if info.get("unborn"):
            lbl.set_markup(
                "Create a branch from <b>%s</b> (no commits yet)"
                % GLib.markup_escape_text(base))
        else:
            lbl.set_markup("Create a branch from <b>%s</b>"
                           % GLib.markup_escape_text(base))
        box.pack_start(lbl, False, False, 0)
        if info.get("unborn"):
            note = Gtk.Label(xalign=0)
            note.set_line_wrap(True)
            note.get_style_context().add_class("secondary-label")
            note.set_text(
                "This repository has no commit yet. The current name is "
                "not a Git ref, so it will not remain available after the "
                "new branch is created.")
            box.pack_start(note, False, False, 0)
        entry = Gtk.Entry()
        entry.set_placeholder_text("feature/my-change")
        entry.set_activates_default(True)
        box.pack_start(entry, False, False, 0)
        dlg.show_all()
        entry.grab_focus()
        response = dlg.run()
        name = entry.get_text().strip()
        dlg.destroy()
        if response != Gtk.ResponseType.OK or not name:
            return
        ok, message = ide_git.validate_branch_name(self.root, name)
        if not ok:
            self._branch_error_dialog(name, message, "create")
            return
        self._create_branch(name)

    def _remember_compact_bottom_position(self, pane):
        if self._tree_collapsed or self._tabs_collapsed:
            return
        position = pane.get_position()
        width = pane.get_allocated_width()
        if 0 < position < width:
            self._tree_positions["compact"] = position
            self._tabs_positions["compact"] = position

    def toggle_tree(self, btn=None):
        pane = self.bottom_h if self.layout == "compact" else self.main_h
        if self.layout == "compact":
            self._remember_compact_bottom_position(pane)
        elif not self._tree_collapsed:
            position = pane.get_position()
            if position > 0:
                self._tree_positions[self.layout] = position
        self._tree_collapsed = not self._tree_collapsed
        self._apply_tree_state()

    def _apply_tree_state(self):
        try:
            pane = self.bottom_h if self.layout == "compact" else self.main_h
            action = "Show files" if self._tree_collapsed else "Hide files"
            if self._tree_collapsed:
                self.tree_box.hide()
                self.tree_box.set_no_show_all(True)
                GLib.idle_add(lambda: self._collapse_tree(pane))
            else:
                self.tree_box.set_no_show_all(False)
                self.tree_box.show_all()
                if self.layout == "compact":
                    self.root_drop.show_all()
                else:
                    self.root_drop.hide()
                GLib.idle_add(lambda: self._restore_tree(pane))
            if hasattr(self, "btn_tree"):
                set_button_icon(
                    self.btn_tree,
                    "files-hidden" if self._tree_collapsed else "files")
                self.btn_tree.set_label(
                    "Files" if self.layout == "compact" else action)
                self.btn_tree.set_tooltip_text(action)
        except Exception:
            pass
        if self.layout == "compact":
            self._apply_compact_bottom_visibility()
        return False

    def _collapse_tree(self, pane):
        try:
            pane.set_position(0)
        except Exception:
            pass
        return False

    def _restore_tree(self, pane):
        try:
            position = self._tree_positions.get(self.layout)
            if position is None:
                position = 280 if self.layout == "full" else pane.get_allocated_width() // 2
            pane.set_position(position)
        except Exception:
            pass
        return False

    def toggle_tabs(self, btn=None):
        pane = self.bottom_h if self.layout == "compact" else self.right_v
        if self.layout == "compact":
            self._remember_compact_bottom_position(pane)
        elif not self._tabs_collapsed:
            position = pane.get_position()
            if position > 0:
                self._tabs_positions[self.layout] = position
        self._tabs_collapsed = not self._tabs_collapsed
        self._apply_tabs_state()

    def _apply_tabs_state(self):
        if self._tabs_collapsed:
            icon = "terminal"
            action = "Show terminal"
            GLib.idle_add(self._collapse_tabs)
        else:
            icon = "panel-bottom"
            action = "Hide terminal"
            GLib.idle_add(self._restore_tabs)
        set_button_icon(self.btn_collapse, icon)
        self.btn_collapse.set_label(
            "Terminal" if self.layout == "compact" else action)
        self.btn_collapse.set_tooltip_text(action)
        if self.layout == "compact":
            self._apply_compact_bottom_visibility()

    def _collapse_tabs(self):
        try:
            if self.layout == "compact":
                self.tabs.set_no_show_all(True)
                self.tabs.hide()
                w = self.bottom_h.get_allocated_width()
                self.bottom_h.set_position(max(0, w))
            else:
                self.tabs.show_all()
                h = self.right_v.get_allocated_height()
                self.right_v.set_position(max(0, h - 30))
        except Exception:
            pass
        return False

    def _restore_tabs(self):
        try:
            if self.layout == "compact":
                self.tabs.set_no_show_all(False)
                self.tabs.show_all()
                position = self._tabs_positions.get(self.layout)
                if position is None:
                    position = self.bottom_h.get_allocated_width() // 2
                self.bottom_h.set_position(position)
            else:
                self.tabs.show_all()
                position = self._tabs_positions.get(self.layout)
                if position is None:
                    position = 520
                self.right_v.set_position(position)
        except Exception:
            pass
        return False

    # ---------------- document close lifecycle ----------------
    def _doc_text(self, doc):
        return doc.buffer.get_text(doc.buffer.get_start_iter(),
                                   doc.buffer.get_end_iter(), False)

    def _try_close_doc(self, doc, fpath):
        """Central close state machine (RA-001/RA-002).

        Returns 'close' when it is safe to remove the tab, 'abort' when
        the user cancelled (the tab must stay open).
        """
        if doc.deleted:
            if not doc.dirty:
                return 'close'
            resp = self._deleted_dialog(doc)
            if resp == Gtk.ResponseType.YES:
                result = self._recreate_deleted_doc(doc)
                if result == 'ok':
                    return 'close'
                if result == 'exists':
                    resolution = self._resolve_reappeared_deleted(doc)
                    return ('close' if resolution in ('saved', 'reloaded')
                            else 'abort')
                return 'abort'
            if resp == Gtk.ResponseType.NO:
                return 'close' if self._save_as_doc(doc) else 'abort'
            if resp == Gtk.ResponseType.APPLY:
                return 'close'
            return 'abort'
        if doc.conflict:
            resp = self._conflict_close_dialog(doc)
            if resp == Gtk.ResponseType.YES:
                # Explicit consent: acknowledge the current disk state, then
                # let the ordinary save re-check it immediately before write.
                doc.resolve_keep_local()
                self._update_tab_ui(doc.buffer)
                if not self.save_buffer(doc.buffer):
                    return 'abort'
            elif resp == Gtk.ResponseType.NO:
                if not self.reload_buffer(doc.buffer, doc.path):
                    return 'abort'
            else:
                return 'abort'
            return 'close'
        if doc.dirty:
            if not self._save_with_conflict_resolution(doc.buffer):
                if doc.conflict or doc.unsafe or doc.deleted:
                    return 'abort'
                if doc.dirty:
                    resp = self._save_failed_dialog(os.path.basename(doc.path))
                    if resp == Gtk.ResponseType.YES:
                        if not self.save_buffer(doc.buffer):
                            return 'abort'
                    elif resp == Gtk.ResponseType.NO:
                        return 'close'
                    else:
                        return 'abort'
                else:
                    return 'close'
        return 'close'

    def _deleted_dialog(self, doc):
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE,
                                text="%s was deleted externally" % os.path.basename(doc.path),
                                secondary_text="You have unsaved edits that would be lost.")
        dlg.add_button("Recreate file", Gtk.ResponseType.YES)
        dlg.add_button("Save As…", Gtk.ResponseType.NO)
        dlg.add_button("Discard", Gtk.ResponseType.APPLY)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        resp = dlg.run()
        dlg.destroy()
        return resp

    def _recreate_deleted_doc(self, doc):
        """Recreate a deleted file exclusively; never overwrite a reappearance.

        Returns 'ok', 'exists' (the path reappeared; nothing was written),
        or 'error'.
        """
        try:
            atomic_create(doc.path, self._doc_text(doc))
        except FileExistsError:
            return 'exists'
        except OSError as ex:
            print("Could not recreate:", ex)
            return 'error'
        doc.recreate()
        self.refresh_tree()
        self._update_tab_ui(doc.buffer)
        return 'ok'

    def _resolve_reappeared_deleted(self, doc):
        """Offer explicit choices after a deleted path reappears."""
        try:
            dlg = Gtk.MessageDialog(
                transient_for=self.get_toplevel(), modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text="%s reappeared on disk" % os.path.basename(doc.path),
                secondary_text="PanelIDE did not overwrite it. The editor "
                               "buffer is still intact. Save it to another "
                               "path, reload the disk version, or cancel.")
            dlg.add_button("Save As…", Gtk.ResponseType.YES)
            dlg.add_button("Reload from disk", Gtk.ResponseType.NO)
            dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dlg.set_default_response(Gtk.ResponseType.CANCEL)
            resp = dlg.run()
            dlg.destroy()
        except Exception:
            return 'cancel'
        if resp == Gtk.ResponseType.YES:
            return 'saved' if self._save_as_doc(doc) else 'cancel'
        if resp == Gtk.ResponseType.NO:
            if self.reload_buffer(doc.buffer, doc.path):
                return 'reloaded'
            doc.mark_unsafe("the reappeared file could not be read from disk")
            self._update_tab_ui(doc.buffer)
        return 'cancel'

    def _deleted_save_recovery(self, doc):
        """Ctrl+S recovery for a deleted file; keeps the tab open."""
        try:
            dlg = Gtk.MessageDialog(
                transient_for=self.get_toplevel(), modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text="%s was deleted externally" % os.path.basename(doc.path),
                secondary_text="The editor buffer is still intact. Recreate "
                               "the file without overwriting anything that "
                               "reappeared, save it elsewhere, or cancel.")
            dlg.add_button("Recreate file", Gtk.ResponseType.YES)
            dlg.add_button("Save As…", Gtk.ResponseType.NO)
            dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dlg.set_default_response(Gtk.ResponseType.CANCEL)
            resp = dlg.run()
            dlg.destroy()
        except Exception:
            return False
        if resp == Gtk.ResponseType.YES:
            result = self._recreate_deleted_doc(doc)
            if result == 'exists':
                self._resolve_reappeared_deleted(doc)
            return result == 'ok'
        if resp == Gtk.ResponseType.NO:
            return self._save_as_doc(doc)
        return False

    def _conflict_close_dialog(self, doc):
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE,
                                text="%s has an unresolved conflict" % os.path.basename(doc.path),
                                secondary_text="The file changed externally while you have "
                                               "unsaved edits. Decide before closing.")
        dlg.add_button("Save local version", Gtk.ResponseType.YES)
        dlg.add_button("Reload from disk", Gtk.ResponseType.NO)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        resp = dlg.run()
        dlg.destroy()
        return resp

    def _save_failed_dialog(self, name):
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.NONE,
                                text="Could not save %s" % name,
                                secondary_text="Your changes are still in the editor.")
        dlg.add_button("Retry", Gtk.ResponseType.YES)
        dlg.add_button("Close anyway (discard)", Gtk.ResponseType.NO)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        resp = dlg.run()
        dlg.destroy()
        return resp

    def _save_as_race_dialog(self, path, changed):
        try:
            dlg = Gtk.MessageDialog(
                transient_for=self.get_toplevel(), modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.CLOSE,
                text=("File changed while saving"
                      if changed else "File appeared while saving"),
                secondary_text=(
                    "'%s' %s. PanelIDE did not overwrite it; the editor "
                    "buffer is unchanged. Choose another path with Save As."
                    % (os.path.basename(path),
                       "changed after you confirmed the overwrite"
                       if changed else "was created by another process")))
            dlg.run()
            dlg.destroy()
        except Exception:
            pass

    def _save_as_doc(self, doc):
        dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self.get_toplevel(),
                                    action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Save", Gtk.ResponseType.OK)
        dlg.set_do_overwrite_confirmation(True)
        overwrite_states = {}

        def remember_overwrite_state(chooser):
            # Capture the target state when GTK asks for overwrite
            # confirmation, not after the dialog closes: the file can change
            # while that confirmation is on screen.
            try:
                selected = chooser.get_filename()
                overwrite_states[selected] = file_state(selected)
            except Exception:
                pass
            return Gtk.FileChooserConfirmation.CONFIRM

        try:
            dlg.connect("confirm-overwrite", remember_overwrite_state)
        except Exception:
            # Older GTK/the test stub may not expose this signal; the
            # post-dialog state below remains a best-effort fallback.
            pass
        dlg.set_current_name(os.path.basename(doc.path))
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return False
        new = dlg.get_filename()
        dlg.destroy()
        if not new:
            return False
        text = self._doc_text(doc)
        # Prefer the state captured at confirmation time. If GTK did not
        # emit the signal, fall back to the post-dialog state.
        if new in overwrite_states:
            expected = overwrite_states[new]
        else:
            expected = file_state(new)
        try:
            if expected is None:
                atomic_create(new, text)
            else:
                atomic_write_checked(new, text, expected)
        except FileExistsError:
            self._save_as_race_dialog(new, changed=False)
            return False
        except FileChangedError:
            self._save_as_race_dialog(new, changed=True)
            return False
        except OSError as ex:
            print("Could not save as:", ex)
            return False
        self._migrate_doc_path(doc, new)
        doc.save_as(new)
        self._update_tab_ui(doc.buffer)
        self.refresh_tree()
        return True

    def _migrate_doc_path(self, doc, new_path):
        old = doc.path
        if old in self.open_widgets:
            self.open_widgets[new_path] = self.open_widgets.pop(old)
        if old in self.ed_paths:
            self.ed_paths[new_path] = self.ed_paths.pop(old)
        doc.path = new_path

    def request_close(self):
        """Resolve every open document; False aborts the close."""
        if self._branch_op:
            self._branch_busy_dialog()
            return False
        for doc in list(self.docs.values()):
            if self._try_close_doc(doc, doc.path) == 'abort':
                return False
        return True

    # ---------------- saving ----------------
    def on_buffer_changed(self, buf):
        if self._reloading:
            return
        doc = self.docs.get(buf)
        if doc is None:
            return
        doc.mark_edited()
        if self._branch_op:
            # Never let a debounce timer write into a tree Git is
            # currently switching. The reconciliation step re-arms it.
            doc.cancel_autosave()
        self._update_tab_ui(buf)

    def _autosave_buffer(self, buf):
        doc = self.docs.get(buf)
        if doc is None:
            return
        if self._branch_op:
            doc.cancel_autosave()
            return
        if not (doc.dirty and not doc.conflict and not doc.deleted
                and not doc.unsafe):
            # The timer callback must never save a clean, conflicted,
            # deleted, or unverified buffer. Only a normal dirty document
            # reaches the write below.
            return
        # Final guard: the disk may have changed after reconciliation and
        # before the 0.8 s autosave timer. Never let an automatic write
        # replace newer content.
        disk = ide_branch_sync.disk_snapshot(doc.path)
        if disk is None or disk != doc.saved_snap:
            doc.mark_conflict()
            self._update_tab_ui(buf)
            self._conflict_dialog(doc)
            return
        self.save_buffer(buf)

    def save_buffer(self, buf):
        """Ordinary save: fail closed on unresolved or external changes.

        This is the only low-level write used by autosave, Ctrl+S, close and
        shutdown. Explicit overwrite decisions must first call
        ``resolve_keep_local()`` and then come back here, so the disk
        snapshot is acknowledged and re-checked.
        """
        doc = self.docs.get(buf)
        if doc is None or doc.deleted:
            return False
        if self._branch_op:
            return False
        if doc.conflict or doc.unsafe:
            return False
        disk = ide_branch_sync.disk_snapshot(doc.path)
        if disk is None or disk != doc.saved_snap:
            doc.mark_conflict()
            self._update_tab_ui(buf)
            return False
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        try:
            atomic_write(doc.path, text)
        except OSError as ex:
            print("Could not save:", ex)
            doc.dirty = True
            doc.cancel_autosave()
            self._update_tab_ui(buf)
            return False
        doc.mark_saved()
        self._update_tab_ui(buf)
        return True

    def _confirm_save_conflict(self, doc):
        """Ask before an explicit overwrite; returns True only on consent."""
        reason = doc.unsafe_reason or (
            "The file changed on disk after the editor last read it.")
        try:
            dlg = Gtk.MessageDialog(
                transient_for=self.get_toplevel(), modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.NONE,
                text="%s has unresolved changes" % os.path.basename(doc.path),
                secondary_text=(
                    "%s\n\nPanelIDE will not overwrite newer disk content "
                    "automatically. Save the editor version only if you "
                    "really want to replace the file." % reason))
            dlg.add_button("Save local version", Gtk.ResponseType.YES)
            dlg.add_button("Reload from disk", Gtk.ResponseType.NO)
            dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
            dlg.set_default_response(Gtk.ResponseType.CANCEL)
            resp = dlg.run()
            dlg.destroy()
        except Exception:
            return False
        if resp == Gtk.ResponseType.YES:
            # Explicit consent. Acknowledge the current disk state first;
            # save_buffer still re-checks it immediately before writing.
            doc.resolve_keep_local()
            self._update_tab_ui(doc.buffer)
            return True
        if resp == Gtk.ResponseType.NO:
            if not self.reload_buffer(doc.buffer, doc.path):
                doc.mark_unsafe("the file could not be read from disk")
                self._update_tab_ui(doc.buffer)
        return False

    def _save_with_conflict_resolution(self, buf):
        """Ordinary save, with at most one explicit conflict retry."""
        doc = self.docs.get(buf)
        if doc is None or doc.deleted:
            return False
        if doc.conflict or doc.unsafe:
            if not self._confirm_save_conflict(doc):
                return False
        if self.save_buffer(buf):
            return True
        if doc.conflict and self._confirm_save_conflict(doc):
            return self.save_buffer(buf)
        return False

    def save_file(self, btn=None):
        if self._branch_op:
            self._branch_busy_dialog()
            return
        page = self.ed_tabs.get_current_page()
        if page < 0:
            return
        widget = self.ed_tabs.get_nth_page(page)
        for path, (buf, w) in self.ed_paths.items():
            if w is widget:
                doc = self.docs.get(buf)
                if doc is not None and doc.deleted:
                    self._deleted_save_recovery(doc)
                    return
                self._save_with_conflict_resolution(buf)
                break

    def _branch_busy_dialog(self):
        try:
            dlg = Gtk.MessageDialog(
                transient_for=self.get_toplevel(), modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.CLOSE,
                text="Branch operation in progress",
                secondary_text="Wait for Git to finish before saving, "
                               "closing, or changing files. Your editor "
                               "contents are kept.")
            dlg.run()
            dlg.destroy()
        except Exception:
            pass

    def _branch_busy(self):
        """True while Git is switching; shows the busy dialog once."""
        if not self._branch_op:
            return False
        self._branch_busy_dialog()
        return True

    def _update_tab_ui(self, buf):
        doc = self.docs.get(buf)
        if doc is None:
            return
        entry = self.ed_paths.get(doc.path)
        if not entry:
            return
        lbl = self.tab_labels.get(entry[1])
        if not lbl:
            return
        name = os.path.basename(doc.path)
        if doc.deleted and doc.dirty:
            lbl.set_text(name + " ⚠")
            lbl.set_tooltip_text("Deleted externally — you have unsaved changes")
        elif doc.deleted:
            lbl.set_text(name + " ⚠")
            lbl.set_tooltip_text("Deleted externally")
        elif doc.unsafe:
            lbl.set_text(name + " ⚠")
            lbl.set_tooltip_text("Autosave paused — %s" % doc.unsafe_reason)
        elif doc.conflict:
            lbl.set_text(name + " ⚠")
            lbl.set_tooltip_text("Changed externally while you have unsaved edits")
        elif doc.dirty:
            lbl.set_text(name + " ●")
            lbl.set_tooltip_text("Modified — autosave pending")
        else:
            lbl.set_text(name)
            lbl.set_tooltip_text("")

    def on_key(self, w, ev):
        k = Gdk.keyval_name(ev.keyval)
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            if k == 's':
                self.save_file(); return True
            if k == 't':
                self.add_command_tab(); return True
        if k == 'F2':
            sel = self.tree.get_selection().get_selected()
            if sel[1]:
                self._edit_target = self.store.get_value(sel[1], 2)
                self.r_name.set_property("editable", True)
                col = self.tree.get_column(0)
                self.tree.set_cursor(self.store.get_path(sel[1]), col, True)
                GLib.idle_add(lambda: self.r_name.set_property("editable", False))
            return True
        if k == 'Delete':
            self.delete_selected()
            return True
        return False

    def shutdown(self):
        """Stop the harness, command terminals, and audio in this panel."""
        if self._shutdown:
            return
        self._shutdown = True
        # A finished worker may still have its reconciliation callback queued
        # on the GTK loop. If _branch_op is true here, that reconciliation
        # has not run, so writing dirty buffers could overwrite files Git
        # just changed. Fail closed instead.
        branch_unreconciled = self._branch_op
        thread = getattr(self, "_branch_thread", None)
        branch_still_running = False
        if thread is not None and thread.is_alive():
            # A switch is allowed to run for SWITCH_TIMEOUT. Waiting only a
            # few seconds would release autosave while Git is still
            # rewriting files, so wait for the same budget Git has (plus a
            # margin for the thread to notice the result).
            try:
                thread.join(timeout=ide_git.SWITCH_TIMEOUT + 5.0)
            except Exception:
                pass
            branch_still_running = thread.is_alive()
        self._branch_op = False
        if not branch_still_running and not branch_unreconciled:
            for doc in list(self.docs.values()):
                if (doc.dirty and not doc.deleted and not doc.conflict
                        and not doc.unsafe):
                    try:
                        self.save_buffer(doc.buffer)
                    except Exception:
                        pass
        elif branch_still_running:
            print("Branch operation still running during shutdown; "
                  "unsaved buffers were not written.")
        else:
            print("Branch operation finished but was not reconciled before "
                  "shutdown; unsaved buffers were not written.")
        for widget in list(self.audio_state):
            self._cleanup_audio_widget(widget)
        for mon in self.monitors.values():
            try:
                mon.cancel()
            except Exception:
                pass
        self.monitors.clear()
        for p in self.players:
            try:
                p.set_state(Gst.State.NULL)
            except Exception:
                pass
        self.players.clear()
        if self.harness_pid:
            try:
                os.kill(self.harness_pid, 15)
            except Exception:
                pass
        for t in self.cmd_terms:
            try:
                t.kill_sync(Vte.TerminalKill.KILL_SHELL, None)
            except Exception:
                pass
        try:
            self.harness_term.kill_sync(Vte.TerminalKill.KILL_SHELL, None)
        except Exception:
            pass


def load_recents():
    try:
        with open(RECENT_FILE) as f:
            data = json.load(f)
        return [p for p in data if os.path.isdir(p)][:10]
    except Exception:
        return []

def save_recents(folder):
    try:
        os.makedirs(os.path.dirname(RECENT_FILE), exist_ok=True)
    except Exception:
        pass
    rec = load_recents()
    if folder in rec:
        rec.remove(folder)
    rec.insert(0, folder)
    rec = rec[:10]
    try:
        with open(RECENT_FILE, 'w') as f:
            json.dump(rec, f, indent=1)
    except Exception:
        pass


def load_session():
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"enabled": True, "mode": "normal", "projects": []}
        projects = []
        for item in data.get("projects", []):
            if not isinstance(item, dict):
                continue
            root = os.path.abspath(item.get("root", ""))
            if not os.path.isdir(root):
                continue
            files = [os.path.abspath(p) for p in item.get("files", [])
                     if isinstance(p, str) and os.path.isfile(p)]
            projects.append({"root": root, "files": files,
                             "terminals": max(1, int(item.get("terminals", 1))),
                             "tree_hidden": bool(item.get("tree_hidden", False)),
                             "terminals_hidden": bool(item.get("terminals_hidden", False))})
        mode = "multitask" if data.get("mode") == "multitask" else "normal"
        return {"enabled": bool(data.get("enabled", True)), "mode": mode,
                "projects": projects}
    except (OSError, TypeError, ValueError):
        return {"enabled": True, "mode": "normal", "projects": []}


def save_session(window):
    projects = []
    for panel in window.panels:
        files = [p for p in panel.ed_paths
                 if p != "__harness__" and os.path.isfile(p)]
        projects.append({"root": panel.root, "files": files,
                         "terminals": max(1, len(panel.cmd_terms)),
                         "tree_hidden": panel._tree_collapsed,
                         "terminals_hidden": panel._tabs_collapsed})
    data = {"enabled": window.session_enabled, "mode": window.mode, "projects": projects}
    try:
        os.makedirs(os.path.dirname(SESSION_FILE) or ".", exist_ok=True)
        atomic_write(SESSION_FILE, json.dumps(data, indent=1))
    except OSError as ex:
        print("Could not save session:", ex)


class PanelIDE(Gtk.Window):
    def __init__(self, root):
        super().__init__()
        if os.path.isfile(APP_ICON):
            try:
                self.set_icon_from_file(APP_ICON)
            except Exception:
                pass
        self.set_title("PanelIDE — %s" % os.path.basename(root))
        self.set_default_size(1360, 820)
        self.root = os.path.abspath(root)
        self.recents = load_recents()
        self.session = load_session()
        self.session_enabled = self.session["enabled"]
        self._restore_session_enabled = len(sys.argv) <= 1 or sys.argv[1] == "--last"
        self.panels = []
        self._panel_views = {}
        self.mode = "normal"

        provider = Gtk.CssProvider()
        provider.load_from_path(CSS_FILE)
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._css_provider = provider

        self.main_panel = ProjectPanel(self.root, "full")
        self.panels.append(self.main_panel)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.pack_start(self.main_panel, True, True, 0)

        self.btn_openfolder = icon_button(
            "folder-open", "Open a folder in a new window",
            self.open_folder_new_instance, label="Open folder")
        self.btn_add = icon_button(
            "plus", "Add a project to multitask", self.on_add_click,
            label="Add project")
        self.btn_add.set_no_show_all(True)
        self.btn_add.hide()
        self.btn_multitask = icon_button(
            "multitask", "Switch to multitask view",
            self.on_multitask_click, label="Multitask")
        self.btn_multitask.set_no_show_all(True)
        self.btn_multitask.set_visible(True)
        self.btn_session = icon_button(
            "session", "Restore projects and files on startup", toggle=True,
            label="Session: ON" if self.session_enabled else "Session: OFF")
        self.btn_session.get_style_context().add_class("session-toggle")
        self.btn_session.set_active(self.session_enabled)
        set_button_icon(
            self.btn_session,
            "session-on" if self.session_enabled else "session",
            semantic=self.session_enabled)
        self.btn_session.set_tooltip_text(
            "Session restore is %s" % ("on" if self.session_enabled else "off"))
        self.btn_session.connect("toggled", self.on_session_toggle)
        self.btn_tree = icon_button(
            "files", "Hide files", self.on_global_tree_toggle,
            False, "panel-toggle", label="Hide files")
        self.hb = Gtk.HeaderBar()
        self.hb.set_show_close_button(True)
        self.hb.set_title("PanelIDE — %s" % os.path.basename(self.root))
        self.hb.pack_start(self.btn_openfolder)
        self.hb.pack_start(self.btn_add)
        self.hb.pack_start(self.btn_multitask)
        self.hb.pack_start(self.btn_session)
        self.hb.pack_start(self.btn_tree)
        self.set_titlebar(self.hb)
        self.runner_btn_hb = icon_button(
            None, "Runner status", self.on_hb_runner_toggle,
            False, "runner-btn", label="… RUNNER …")
        self.runner_btn_hb.connect("enter-notify-event",
                                   self.on_hb_runner_hover)
        self.runner_btn_hb.set_no_show_all(True)
        self.hb.pack_end(self.runner_btn_hb)
        self.docker_btn_hb = icon_button(
            None, "Docker compose status", self.on_hb_docker_toggle,
            False, "docker-btn", label="… DOCKER …")
        self.docker_btn_hb.set_no_show_all(True)
        self.hb.pack_end(self.docker_btn_hb)
        self.add(self.content)
        self.connect("key-press-event", self.on_win_key)
        self.connect("focus-in-event", self.on_window_focus)
        save_recents(self.root)
        self._runner_tick_id = GLib.timeout_add_seconds(
            20, self._runner_tick)
        self._hb_runner_sync()
        self._hb_docker_sync()
        if self._restore_session_enabled and self.session_enabled and self.session["projects"]:
            GLib.idle_add(self.restore_session)

    def on_window_focus(self, win, event):
        # Keep branch labels truthful after external `git switch` calls
        # made in a terminal or another window.
        for panel in getattr(self, "panels", []):
            panel._branch_refresh()
        return False

    def on_session_toggle(self, btn):
        self.session_enabled = btn.get_active()
        set_button_icon(
            btn, "session-on" if self.session_enabled else "session",
            semantic=self.session_enabled)
        btn.set_label(
            "Session: ON" if self.session_enabled else "Session: OFF")
        btn.set_tooltip_text(
            "Session restore is %s" % ("on" if self.session_enabled else "off"))
        if self.session_enabled:
            save_session(self)

    def on_global_tree_toggle(self, btn):
        target = self.main_panel
        if self.mode == "multitask" and target is not None:
            states = [p._tree_collapsed for p in self.panels]
            # next action: collapse only when all are visible; otherwise
            # expand everything so the label always predicts the outcome.
            make_collapsed = bool(states) and all(not c for c in states)
            for panel in self.panels:
                if panel._tree_collapsed != make_collapsed:
                    panel.toggle_tree()
        elif target is not None:
            target.toggle_tree()
        self._sync_global_tree_button()

    def _sync_global_tree_button(self):
        if self.main_panel is None:
            return
        if self.mode == "multitask":
            action = mt_ui.global_files_action(
                [p._tree_collapsed for p in self.panels])
            icon = ("files" if action == "Hide all files"
                    else "files-hidden")
        elif self.main_panel._tree_collapsed:
            icon, action = "files-hidden", "Show files"
        else:
            icon, action = "files", "Hide files"
        set_button_icon(self.btn_tree, icon)
        self.btn_tree.set_label(action)
        self.btn_tree.set_tooltip_text(
            action + (" (all projects)" if self.mode == "multitask" else ""))
    def restore_session(self):
        if not self._restore_session_enabled or not self.session_enabled:
            return False
        saved = self.session["projects"]
        if not saved:
            return False
        if self.session.get("mode") == "multitask" or len(saved) > 1:
            self.enter_multitask()
        first = saved[0]
        if os.path.abspath(first["root"]) != self.main_panel.root:
            self.main_panel.shutdown()
            self.content.remove(self.main_panel)
            self.panels = []
            self.main_panel = ProjectPanel(first["root"],
                                           "compact" if self.mode == "multitask" else "full")
            self.panels.append(self.main_panel)
        for item in saved[1:]:
            self.open_project(item["root"])
        for panel, item in zip(self.panels, saved):
            for fpath in item["files"]:
                if os.path.isfile(fpath) and path_inside(panel.root, fpath):
                    panel.open_file(fpath)
            for _ in range(max(0, item["terminals"] - len(panel.cmd_terms))):
                panel.add_command_tab()
            panel._tree_collapsed = bool(item.get("tree_hidden", False))
            panel._tabs_collapsed = bool(item.get("terminals_hidden", False))
            panel._apply_tree_state()
            panel._apply_tabs_state()
        self.rebuild_layout()
        return False

    def on_destroy(self, *args):
        save_session(self)
        if getattr(self, "_runner_tick_id", None):
            try:
                GLib.source_remove(self._runner_tick_id)
            except Exception:
                pass
            self._runner_tick_id = None
        for panel in list(self.panels):
            panel.shutdown()
        Gtk.main_quit()

    def on_delete_event(self, w, ev):
        for panel in list(self.panels):
            if getattr(panel, "_branch_op", False):
                panel._branch_busy_dialog()
                return True
            if not panel.request_close():
                return True
        if not self._runner_gate(list(self.panels), "Close PanelIDE"):
            return True
        save_session(self)
        return False

    # ---------------- runners self-hosted (manual) ----------------
    def _runner_tick(self):
        try:
            for panel in list(self.panels):
                panel._runner_refresh()
            self._hb_runner_sync()
        except Exception:
            pass
        try:
            self._docker_tick()
        except Exception:
            pass
        return True

    def _docker_tick(self):
        """Refresca compose por panel en hilos (no bloquea el tick)."""
        import threading
        for panel in list(self.panels):
            try:
                threading.Thread(target=panel._docker_refresh_bg,
                                 args=(None,), daemon=True).start()
            except Exception:
                pass
        try:
            self._hb_docker_sync()
        except Exception:
            pass

    def on_hb_runner_toggle(self, btn):
        if self.main_panel is None or self.mode == "multitask":
            return
        self.main_panel.on_runner_toggle(btn)

    def on_hb_runner_hover(self, btn, ev):
        if self.main_panel is None or self.mode == "multitask":
            return False
        return self.main_panel.on_runner_hover(btn, ev)

    def _hb_runner_sync(self):
        btn = getattr(self, "runner_btn_hb", None)
        if btn is None:
            return
        # The global badge only represents main_panel; in multitask every
        # project already shows its own compact runner, so hide the global
        # badge instead of implying an aggregate state.
        if self.main_panel is None or self.mode == "multitask":
            btn.hide()
            btn.set_no_show_all(True)
            return
        btn.set_no_show_all(False)
        btn.show()
        self.main_panel._runner_paint(btn, compact=False)

    def on_hb_docker_toggle(self, btn):
        if self.main_panel is None or self.mode == "multitask":
            return
        self.main_panel.on_docker_toggle(btn)

    def _hb_docker_sync(self):
        btn = getattr(self, "docker_btn_hb", None)
        if btn is None:
            return
        if self.main_panel is None or self.mode == "multitask":
            btn.hide()
            btn.set_no_show_all(True)
            return
        btn.set_no_show_all(False)
        btn.show()
        self.main_panel._docker_paint(btn, compact=False)

    def _runner_gate(self, panels, title):
        """Gate de cierre para runners activos. Misma rutina en todos
        los cierres: apaga los no-busy (con espera) y pregunta por los
        busy. Devuelve True si se puede cerrar."""
        import threading
        targets = []
        for p in panels:
            info = getattr(p, "runner_info", None)
            if not info or not info.get("has_runner"):
                continue
            if not info.get("installed"):
                continue
            if ide_runners.local_state(info["unit"]) == "active":
                targets.append((p, info))
        if not targets:
            return True

        dlg = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dlg.set_default_size(480, 240)
        box = dlg.get_content_area()
        log_lbl = Gtk.Label(xalign=0)
        log_lbl.set_line_wrap(True)
        log_lbl.set_markup("<b>Checking runners…</b>")
        box.pack_start(log_lbl, True, True, 8)
        spin = Gtk.Spinner()
        box.pack_start(spin, False, False, 4)
        spin.start()
        btn_cancel = dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        box.show_all()

        lines = []
        cancel = threading.Event()
        result = {"ok": False}
        state = {"done": False, "choice": False}
        choice = {"pending": []}
        btns = {}
        loop = GLib.MainLoop()

        def log(text):
            lines.append(text)
            try:
                log_lbl.set_markup("\n".join(lines[-8:]))
            except Exception:
                pass

        def log_async(text):
            GLib.idle_add(log, text)

        def finish(ok, resp):
            if state["done"]:
                return
            state["done"] = True
            result["ok"] = bool(ok)
            try:
                dlg.response(resp)
            except Exception:
                pass
            try:
                loop.quit()
            except Exception:
                pass

        def stop_one(info):
            ide_runners.stop_unit(info["unit"])
            return ide_runners.wait_inactive(
                info["unit"], timeout=40,
                cancelled=cancel.is_set)

        def on_resp(d, resp):
            if state["done"]:
                return
            if resp == Gtk.ResponseType.APPLY and state["choice"]:
                for b in (btns.get("wait"), btns.get("keep"), btn_cancel):
                    if b is None:
                        continue
                    try:
                        b.set_sensitive(False)
                    except Exception:
                        pass
                spin.show()
                spin.start()
                threading.Thread(target=wait_then_stop,
                                 daemon=True).start()
            elif resp == Gtk.ResponseType.YES and state["choice"]:
                finish(True, Gtk.ResponseType.OK)
            elif resp == Gtk.ResponseType.CANCEL:
                cancel.set()
                finish(False, Gtk.ResponseType.CANCEL)
            elif resp == Gtk.ResponseType.OK:
                finish(result["ok"], Gtk.ResponseType.OK)
            # otros: ignorar

        def worker():
            try:
                pending_busy = []
                for _p, info in targets:
                    if cancel.is_set() or state["done"]:
                        return
                    name = info.get("repo", "?")
                    log_async("Checking <b>%s</b>…" % name)
                    st = ide_runners.remote_state(
                        info["org"], info["repo"], info["agent"])
                    if cancel.is_set() or state["done"]:
                        return
                    if st is not None and not st[1]:
                        log_async("Stopping runner <b>%s</b>…" % name)
                        if stop_one(info):
                            log_async(
                                "Runner <b>%s</b> stopped." % name)
                        else:
                            log_async(
                                "Runner <b>%s</b> could not be stopped "
                                "(still active)." % name)
                            pending_busy.append(info)
                    else:
                        pending_busy.append(info)
                if cancel.is_set() or state["done"]:
                    return
                if not pending_busy:
                    result["ok"] = True
                    GLib.idle_add(finish, True, Gtk.ResponseType.OK)
                    return
                names = ", ".join(i.get("repo", "?") for i in pending_busy)
                log_async(
                    "Runner(s) with active jobs or unverified status: "
                    "<b>%s</b>.\nChoose how to continue." % names)
                GLib.idle_add(show_busy_choices, pending_busy)
            except Exception as ex:
                print("runner gate:", ex)
                GLib.idle_add(finish, False, Gtk.ResponseType.CANCEL)

        def show_busy_choices(pending_busy):
            if state["done"]:
                return False
            state["choice"] = True
            choice["pending"] = list(pending_busy)
            spin.stop()
            spin.hide()
            btns["wait"] = dlg.add_button("Wait for jobs to finish",
                                          Gtk.ResponseType.APPLY)
            btns["keep"] = dlg.add_button("Close and leave them running",
                                          Gtk.ResponseType.YES)
            btns["wait"].grab_default()
            box.show_all()
            return False

        def wait_then_stop():
            try:
                for info in list(choice["pending"]):
                    if cancel.is_set() or state["done"]:
                        return
                    name = info.get("repo", "?")
                    log_async("Waiting for <b>%s</b>…" % name)
                    ok = ide_runners.wait_not_busy(
                        info["org"], info["repo"], info["agent"],
                        cancelled=cancel.is_set)
                    if cancel.is_set() or state["done"]:
                        return
                    if ok:
                        log_async("Stopping runner <b>%s</b>…" % name)
                        stop_one(info)
                    else:
                        log_async(
                            "Runner <b>%s</b>: leaving it running." % name)
                result["ok"] = True
                GLib.idle_add(finish, True, Gtk.ResponseType.OK)
            except Exception as ex:
                print("runner gate wait:", ex)
                GLib.idle_add(finish, False, Gtk.ResponseType.CANCEL)

        # NOTE: on_resp usa b_wait/b_keep via action_area (ver arriba).
        dlg.connect("response", on_resp)
        threading.Thread(target=worker, daemon=True).start()
        loop.run()
        try:
            self._runner_tick()
        except Exception:
            pass
        dlg.destroy()
        return bool(result["ok"])

    # ---------------- multitasking ----------------
    def on_multitask_click(self, btn):
        if self.mode == "normal":
            self.enter_multitask()
        else:
            self.exit_multitask()

    def on_add_click(self, btn):
        menu = Gtk.Menu()
        if self.recents:
            for folder in self.recents[:6]:
                item = Gtk.MenuItem(label=os.path.basename(folder))
                item.connect("activate", lambda w, f=folder: self.open_project(f))
                menu.append(item)
            menu.append(Gtk.SeparatorMenuItem())
        item = Gtk.MenuItem(label="Choose folder…")
        item.connect("activate", self.browse_project)
        menu.append(item)
        menu.show_all()
        menu.popup_at_widget(btn, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def enter_multitask(self):
        self.mode = "multitask"
        self.main_panel.on_close = self.close_panel
        self.main_panel.set_layout("compact")
        set_button_icon(self.btn_multitask, "grid")
        self.btn_multitask.set_label("Exit multitask")
        self.btn_multitask.set_tooltip_text("Exit multitask")
        self.btn_add.set_visible(True)
        self.rebuild_layout()
        self._hb_runner_sync()

    def exit_multitask(self):
        if not self.panels or self.main_panel is None:
            return
        extra = self.panels[1:]
        if extra:
            names = ", ".join(os.path.basename(p.root) for p in extra)
            dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                    message_type=Gtk.MessageType.QUESTION,
                                    buttons=Gtk.ButtonsType.NONE,
                                    text="Exit multitask")
            dlg.format_secondary_text(
                "Close %s and their harnesses?" % names)
            dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
            exit_btn = dlg.add_button(
                "Exit multitask", Gtk.ResponseType.ACCEPT)
            exit_btn.get_style_context().add_class("destructive-action")
            dlg.set_default_response(Gtk.ResponseType.CANCEL)
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.ACCEPT:
                return
            for p in extra:
                if getattr(p, "_branch_op", False):
                    p._branch_busy_dialog()
                    return
                if not p.request_close():
                    return
            if not self._runner_gate(extra, "Exit multitask"):
                return
            for p in extra:
                p.shutdown()
            self.panels = [self.main_panel]
        self.mode = "normal"
        self.main_panel.set_layout("full")
        self.main_panel.on_close = None
        set_button_icon(self.btn_multitask, "multitask")
        self.btn_multitask.set_label("Multitask")
        self.btn_multitask.set_tooltip_text("Switch to multitask view")
        self.btn_add.set_visible(False)
        self.btn_tree.set_visible(True)
        self._sync_global_tree_button()
        self.set_title("PanelIDE — %s" % os.path.basename(self.main_panel.root))
        self.hb.set_title("PanelIDE — %s" % os.path.basename(self.main_panel.root))
        for ch in list(self.content.get_children()):
            self.content.remove(ch)
        parent = self.main_panel.get_parent()
        if parent is not None:
            parent.remove(self.main_panel)
        self.content.pack_start(self.main_panel, True, True, 0)
        self.content.show_all()
        self.main_panel._apply_editor_visibility()
        self._hb_runner_sync()

    def make_empty_slot(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>Add a project</b>")
        box.pack_start(lbl, False, False, 8)
        if self.recents:
            lbl2 = Gtk.Label("Recent:", xalign=0)
            box.pack_start(lbl2, False, False, 2)
            for folder in self.recents[:6]:
                b = Gtk.Button()
                inner = Gtk.Box(spacing=6)
                inner.pack_start(Gtk.Image.new_from_pixbuf(icon_for(os.path.basename(folder), True)), False, False, 0)
                inner.pack_start(Gtk.Label(os.path.basename(folder), xalign=0), True, True, 0)
                b.add(inner)
                b.connect("clicked", lambda w, f=folder: self.open_project(f))
                box.pack_start(b, False, False, 0)
        btn = Gtk.Button(label="Choose folder…")
        btn.connect("clicked", self.browse_project)
        box.pack_start(btn, False, False, 4)
        return box

    def open_project(self, folder):
        if self.mode != "multitask":
            self.enter_multitask()
        if folder in [p.root for p in self.panels]:
            return
        panel = ProjectPanel(folder, "compact", on_close=self.close_panel)
        self.panels.append(panel)
        if self.main_panel is None:
            self.main_panel = panel
        save_recents(folder)
        self.rebuild_layout()

    def browse_project(self, btn=None):
        dlg = Gtk.FileChooserDialog(title="Open project in multitask", transient_for=self,
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Open project", Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self.open_project(dlg.get_filename())
        dlg.destroy()

    def _confirm_panel_close(self, panel):
        view = self._panel_views.get(panel)
        if view is None:
            return self._confirm_window_close(panel)

        backdrop = Gtk.EventBox()
        backdrop.get_style_context().add_class("project-modal-backdrop")
        backdrop.set_hexpand(True)
        backdrop.set_vexpand(True)
        backdrop.set_above_child(True)

        confirm = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        confirm.get_style_context().add_class("project-confirm")
        confirm.set_halign(Gtk.Align.CENTER)
        confirm.set_valign(Gtk.Align.CENTER)

        title = Gtk.Label()
        title.set_markup("<b>Close project</b>")
        title.set_justify(Gtk.Justification.CENTER)
        confirm.pack_start(title, False, False, 0)
        detail = Gtk.Label("'%s' and its harness will be closed." % os.path.basename(panel.root))
        detail.set_line_wrap(True)
        detail.set_justify(Gtk.Justification.CENTER)
        confirm.pack_start(detail, False, False, 0)

        actions = Gtk.Box(spacing=6)
        actions.set_halign(Gtk.Align.CENTER)
        cancel_btn = Gtk.Button(label="Cancel")
        close_btn = Gtk.Button(label="Close project")
        close_btn.get_style_context().add_class("destructive-action")
        actions.pack_start(cancel_btn, True, True, 0)
        actions.pack_start(close_btn, True, True, 0)
        confirm.pack_start(actions, False, False, 0)

        response = {"close": False}
        loop = GLib.MainLoop()

        def finish(close):
            response["close"] = close
            view.remove(confirm)
            view.remove(backdrop)
            loop.quit()

        cancel_btn.connect("clicked", lambda w: finish(False))
        close_btn.connect("clicked", lambda w: finish(True))
        view.add_overlay(backdrop)
        view.add_overlay(confirm)
        backdrop.show()
        confirm.show_all()
        loop.run()
        return response["close"]

    def _confirm_window_close(self, panel):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.NONE,
                                text="Close project",
                                secondary_text="'%s' and its harness will be closed."
                                               % os.path.basename(panel.root))
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        close_btn = dlg.add_button("Close project", Gtk.ResponseType.ACCEPT)
        close_btn.get_style_context().add_class("destructive-action")
        dlg.set_default_response(Gtk.ResponseType.CANCEL)
        resp = dlg.run()
        dlg.destroy()
        return resp == Gtk.ResponseType.ACCEPT

    def close_panel(self, panel):
        if panel not in self.panels:
            return
        if getattr(panel, "_branch_op", False):
            panel._branch_busy_dialog()
            return
        if not self._confirm_panel_close(panel):
            return
        if not panel.request_close():
            return
        if not self._runner_gate([panel], "Close project"):
            return
        panel.shutdown()
        self.panels.remove(panel)
        if self.main_panel is panel:
            self.main_panel = self.panels[0] if self.panels else None
        self.rebuild_layout()

    def rebuild_layout(self):
        for ch in list(self.content.get_children()):
            self.content.remove(ch)
        for p in self.panels:
            parent = p.get_parent()
            if parent is not None:
                parent.remove(p)
        self.btn_multitask.set_visible(bool(self.panels))
        if not self.panels:
            self._panel_views = {}
            self.set_title("PanelIDE — Add a project")
            self.hb.set_title("PanelIDE — Add a project")
            box = self.make_empty_slot()
            self.content.pack_start(box, True, True, 0)
            self.content.show_all()
            return
        self._mt_panes = []
        self._panel_views = {}
        container = self._build_panes(list(self.panels))
        self._mt_container = container
        self.content.pack_start(container, True, True, 0)
        self.content.show_all()

        title_chars = mt_ui.title_max_chars(len(self.panels))
        for panel in self.panels:
            if panel.title_lbl is not None:
                panel.title_lbl.set_max_width_chars(title_chars)
        for p in self.panels:
            p._apply_editor_visibility()
        if self.mode == "multitask":
            title = "PanelIDE — Multitask — %d project%s" % (
                len(self.panels), "s" if len(self.panels) > 1 else "")
        else:
            title = "PanelIDE — %s" % os.path.basename(self.main_panel.root)
        self.set_title(title)
        self.hb.set_title(title)
        self._sync_global_tree_button()
        GLib.idle_add(self._mt_sizes)
        GLib.timeout_add(250, self._mt_sizes)

    def _build_panes(self, widgets):
        if len(widgets) == 1:
            panel = widgets[0]
            if self.mode != "multitask":
                return panel
            view = Gtk.Overlay()
            view.set_hexpand(True)
            view.set_vexpand(True)
            view.add(panel)
            self._panel_views[panel] = view
            return view
        mid = len(widgets) // 2
        pane = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self._mt_panes.append((pane, mid, len(widgets)))
        pane.pack1(self._build_panes(widgets[:mid]), True, False)
        pane.pack2(self._build_panes(widgets[mid:]), True, False)
        return pane

    def _mt_sizes(self):
        try:
            n = len(self.panels)
            for panel in self.panels:
                if panel.layout == "compact":
                    panel._apply_compact_sizes()
                # Keep title ellipsis in sync with column count so long
                # names truncate instead of squeezing buttons.
                try:
                    if getattr(panel, "title_lbl", None) is not None:
                        panel.title_lbl.set_max_width_chars(
                            mt_ui.title_max_chars(n))
                except Exception:
                    pass
            for pane, left, total in self._mt_panes:
                w = pane.get_allocated_width()
                pos = mt_ui.split_position(w, left, total)
                if pos is not None:
                    pane.set_position(pos)
        except Exception:
            pass
        return False

    # ---------------- window ----------------
    def open_folder_new_instance(self, btn=None):
        dlg = Gtk.FileChooserDialog(title="Open folder", transient_for=self,
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Open", Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            folder = dlg.get_filename()
            save_recents(folder)
            subprocess.Popen([sys.executable, SCRIPT, folder],
                             start_new_session=True,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        dlg.destroy()

    def _panel_for(self, widget):
        p = widget
        while p is not None:
            if isinstance(p, ProjectPanel):
                return p
            p = p.get_parent()
        return None

    def on_win_key(self, w, ev):
        if ev.state & Gdk.ModifierType.CONTROL_MASK:
            k = Gdk.keyval_name(ev.keyval)
            if k.lower() == 'v':
                focused = self.get_focus()
                if focused is None or isinstance(focused, (Vte.Terminal,
                                                           GtkSource.View,
                                                           Gtk.TextView,
                                                           Gtk.Entry)):
                    return False
                panel = self._panel_for(focused) or self.main_panel
                if panel is not None:
                    panel.term_paste(panel.harness_term)
                    return True
                return False
            if self.mode == "multitask" and k in tuple("123456789"):
                idx = int(k) - 1
                if idx < len(self.panels):
                    self.panels[idx].tree.grab_focus()
                return True
        return False

if __name__ == "__main__":
    folder = FOLDER
    if len(sys.argv) <= 1 or folder == "--last":
        session = load_session()
        if session["enabled"] and session["projects"]:
            folder = session["projects"][0]["root"]
        else:
            try:
                rec = json.load(open(RECENT_FILE))
                folder = rec[0] if rec else None
            except Exception:
                folder = None
    if not folder:
        dlg = Gtk.FileChooserDialog(title="Select a project",
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL,
                        "Open", Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            folder = dlg.get_filename()
        dlg.destroy()
    if not folder:
        sys.exit(0)
    win = PanelIDE(folder)
    win.connect("delete-event", win.on_delete_event)
    win.connect("destroy", win.on_destroy)
    win.show_all()
    if win.main_panel.ed_tabs.get_n_pages() == 0:
        win.main_panel.editor_pane.hide()
    Gtk.main()
