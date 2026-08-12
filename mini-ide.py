#!/usr/bin/env python3
# mini-ide v9: modo multitasking dinámico (agrega/cierra proyectos libremente).
import sys, os, shutil, csv, json, subprocess, math
from itertools import islice
from mini_ide.settings import WARN_LARGE, MAX_LARGE, MAX_PDF_PIXELS
from mini_ide.file_ops import (atomic_write, validate_child_name,
                               create_new_file, create_new_dir, path_inside,
                               copy_dest_safe)
from mini_ide.document import DocumentState, doc_relocator, docs_under
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
OPENCODE = (os.environ.get("MINI_IDE_OPENCODE")
            or shutil.which("opencode")
            or os.path.expanduser("~/.opencode/bin/opencode"))
ICONS = os.path.expanduser("~/.vscode/extensions/pkief.material-icon-theme-5.37.0/icons")
SCRIPT = os.path.abspath(__file__)
RECENT_FILE = os.environ.get("MINI_IDE_RECENTS") or os.path.expanduser("~/.config/mini-ide/recent.json")

IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "tiff", "svg", "avif"}
AUD_EXT = {"mp3", "ogg", "oga", "wav", "flac", "m4a", "opus", "wma", "aac", "mid", "midi"}
CSV_EXT = {"csv", "tsv"}
CSV_COLORS = ["#2E5E3E", "#1F4E6E", "#5E5E1F", "#6E3E1F", "#4A2E6E"]

VSC_CSS = b"""
window { background-color: #121314; }
box, paned, scrolledwindow, notebook { background-color: #121314; }
box.titlebar { background-color: transparent; background-image: none; }
headerbar box { background-color: transparent; background-image: none; }
box.titlebar button {
    background-color: transparent;
    background-image: none;
    border: none;
    border-radius: 4px;
    color: #D4D4D4;
    min-width: 30px;
    min-height: 24px;
    padding: 0px 6px;
}
box.titlebar button:hover { background-color: rgba(255,255,255,0.12); }
box.titlebar button:active { background-color: rgba(100,150,255,0.18); }
box.titlebar label.title, box.titlebar label.subtitle { background-color: transparent; background-image: none; color: #BFBFBF; }
headerbar { background-color: #191A1B; background-image: none; min-height: 0px; padding: 2px 4px; }
headerbar:backdrop { background-color: #191A1B; background-image: none; }
headerbar button {
    background-color: #242526;
    background-image: none;
    color: #D4D4D4;
    border: 1px solid #2A2B2C;
    border-radius: 4px;
    min-height: 22px;
    min-width: 24px;
    padding: 2px 8px;
}
headerbar button:hover { background-color: rgba(255,255,255,0.12); border-color: #3A3B3C; }
headerbar button:active { background-color: rgba(100,150,255,0.18); border-color: #3994BC; }
headerbar button:backdrop { background-color: #191A1B; color: #8C8C8C; }
headerbar label, headerbar .title, headerbar .subtitle, headerbar button label { color: #BFBFBF; font-size: 13px; text-shadow: none; }
headerbar .title { background-color: transparent; background-image: none; }
headerbar button.titlebutton, headerbar button.titlebutton label { color: #D4D4D4; }
headerbar button.titlebutton { background-color: transparent; background-image: none; border: none; border-radius: 4px; margin: 1px; min-width: 30px; min-height: 24px; }
headerbar button.titlebutton:hover { background-color: rgba(255,255,255,0.12); }
treeview { background-color: #191A1B; color: #BFBFBF; }
treeview:hover { background-color: rgba(255,255,255,0.06); }
treeview:selected { background-color: #094771; color: #EDEDED; }
treeview:selected:backdrop { background-color: #2C2D2E; color: #BFBFBF; }
treeview.view { border-color: #191A1B; }
paned > separator { background-color: #3A3B3C; min-width: 2px; min-height: 2px; }
button {
    color: #BFBFBF;
    background-color: #191A1B;
    background-image: none;
    border: 1px solid #2A2B2C;
    border-radius: 4px;
    min-height: 22px;
    padding: 2px 8px;
}
button:hover { background-color: rgba(255,255,255,0.08); border-color: #3A3B3C; }
button:active { background-color: rgba(100,150,255,0.15); }
entry { background-color: #191A1B; color: #BFBFBF; border-color: #333536; }
scale trough { background-color: #2A2B2C; }
.dim-label { color: #8C8C8C; }
label { color: #BFBFBF; }
notebook { background-color: #191A1B; }
notebook header { background-color: #191A1B; background-image: none; border-color: #2A2B2C; border-bottom: 1px solid #2A2B2C; min-height: 34px; }
notebook tab {
    background-color: #191A1B;
    min-height: 34px;
    padding: 4px 12px;
    border-radius: 4px 4px 0 0;
    margin: 1px 1px 0 1px;
}
notebook tab label { color: #8C8C8C; }
notebook tab:active, notebook tab:checked {
    background-color: #121314;
    border-bottom: 3px solid #3994BC;
}
notebook tab:active label, notebook tab:checked label { color: #EDEDED; }
notebook tab button { min-width: 20px; min-height: 20px; padding: 0px; border-radius: 4px; }
notebook tab button:hover { background-color: rgba(255,255,255,0.15); }
.icon-btn { min-width: 28px; min-height: 28px; padding: 4px; }
label, button, headerbar, notebook, treeview { text-shadow: none; -gtk-icon-shadow: none; }
.root-drop { border: 2px dashed #3994BC; background-color: #191A1B; padding: 14px 12px; border-radius: 6px; margin: 3px 4px; }
.root-drop:hover { background-color: rgba(57,148,188,0.2); }
"""

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
    """A complete project: opencode + editor + tree + terminals.
    layout 'full' (normal mode) or 'compact' (multitasking)."""

    def __init__(self, root, layout="full", on_close=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.root = os.path.abspath(root)
        self.layout = layout
        self.on_close = on_close
        self._refresh_id = None
        self._pending = None
        self.monitors = {}
        self.open_widgets = {}
        self.ed_paths = {}
        self.players = []
        self.opencode_pid = None
        self._compact_tabbed = False
        self._shutdown = False
        self._reloading = False
        self.docs = {}
        self.tab_labels = {}
        self.audio_state = {}

        self.lang_mgr = GtkSource.LanguageManager.get_default()
        self.style_mgr = GtkSource.StyleSchemeManager.get_default()
        self.dark_scheme = self.style_mgr.get_scheme("vs-dark") or self.style_mgr.get_scheme("oblivion")

        # editor with tabs
        self.ed_tabs = Gtk.Notebook()
        self.ed_tabs.set_scrollable(True)
        self.ed_tabs.set_tab_pos(Gtk.PositionType.TOP)
        self.editor_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.editor_pane.pack_start(self.ed_tabs, True, True, 0)
        self.editor_pane.hide()

        # opencode
        self.opencode_term = self.make_terminal()
        self.spawn_opencode()

        # command terminals
        self.tabs = Gtk.Notebook()
        self.tabs.set_scrollable(True)
        self.tabs.set_tab_pos(Gtk.PositionType.TOP)
        self.cmd_terms = []
        plus_btn = Gtk.Button(label="+")
        plus_btn.set_tooltip_text("New terminal (Ctrl+T)")
        plus_btn.connect("clicked", lambda w: self.add_command_tab())
        self.tabs.set_action_widget(plus_btn, Gtk.PackType.END)
        plus_btn.show_all()
        self.btn_collapse = Gtk.Button(label="▾")
        self.btn_collapse.set_tooltip_text("Hide terminal")
        self.btn_collapse.connect("clicked", self.toggle_tabs)
        self.tabs.set_action_widget(self.btn_collapse, Gtk.PackType.END)
        self.btn_collapse.show_all()
        self._tabs_collapsed = False
        self.add_command_tab()

        # tree
        self.store = Gtk.TreeStore(GdkPixbuf.Pixbuf, str, str, str)
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
        self.tree.set_headers_visible(False)
        self.tree.connect("row-activated", self.on_enter)
        self.tree.connect("button-press-event", self.on_tree_btn)
        self.tree.connect("row-expanded", self.on_expand)
        self.tree.connect("row-collapsed", self.on_collapse)
        self.tree.drag_dest_set(Gtk.DestDefaults.ALL,
                                [Gtk.TargetEntry.new("text/uri-list", 0, 80)],
                                Gdk.DragAction.COPY)
        self.tree.connect("drag-data-received", self.on_drop)
        self.scroll_tree = Gtk.ScrolledWindow()
        self.scroll_tree.add(self.tree)

        btn_newfile = Gtk.Button(label="+ File")
        btn_newfile.set_tooltip_text("New file")
        btn_newfile.connect("clicked", lambda w: self.start_new("newfile"))
        btn_newfolder = Gtk.Button(label="+ Folder")
        btn_newfolder.set_tooltip_text("New folder")
        btn_newfolder.connect("clicked", lambda w: self.start_new("newfolder"))

        self.path_lbl = Gtk.Label(xalign=0)
        self.path_lbl.set_markup("<span size='small' color='#888888'>%s</span>"
                                 % GLib.markup_escape_text(self.root))
        btn_copy = Gtk.Button()
        _copy_img = Gtk.Image.new_from_icon_name("edit-copy", Gtk.IconSize.LARGE_TOOLBAR)
        _copy_img.set_pixel_size(24)
        btn_copy.set_image(_copy_img)
        btn_copy.set_tooltip_text("Copy folder path")
        btn_copy.get_style_context().add_class("icon-btn")
        btn_copy.connect("clicked", self.copy_path)
        btn_open = Gtk.Button()
        _open_img = Gtk.Image.new_from_icon_name("folder-open", Gtk.IconSize.LARGE_TOOLBAR)
        _open_img.set_pixel_size(24)
        btn_open.set_image(_open_img)
        btn_open.set_tooltip_text("Open folder in file manager")
        btn_open.get_style_context().add_class("icon-btn")
        btn_open.connect("clicked", self.open_in_fm)

        self.row_path = Gtk.Box(spacing=4)
        self.row_path.pack_start(self.path_lbl, True, True, 6)
        self.row_path.pack_end(btn_open, False, False, 0)
        self.row_path.pack_end(btn_copy, False, False, 0)
        self.row_new = Gtk.Box(spacing=4)
        self.row_new.pack_start(btn_newfile, False, False, 0)
        self.row_new.pack_start(btn_newfolder, False, False, 0)
        self.tree_bar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.tree_bar.pack_start(self.row_path, False, False, 0)
        self.tree_bar.pack_start(self.row_new, False, False, 0)

        self.root_drop = Gtk.Box(spacing=6)
        self.root_drop.get_style_context().add_class("root-drop")
        ico = load_icon("folder") or load_icon("folder-open")
        if ico:
            self.root_drop.pack_start(Gtk.Image.new_from_pixbuf(ico), False, False, 0)
        drop_lbl = Gtk.Label(xalign=0)
        drop_lbl.set_markup("<b>Drop here to copy to root</b>")
        self.root_drop.pack_start(drop_lbl, False, False, 0)
        self.root_drop.drag_dest_set(Gtk.DestDefaults.ALL,
                                     [Gtk.TargetEntry.new("text/uri-list", 0, 80)],
                                     Gdk.DragAction.COPY)
        self.root_drop.connect("drag-data-received", self.on_root_drop)
        self.root_drop.set_no_show_all(True)
        self.root_drop.set_visible(False)

        self.tree_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tree_box.pack_start(self.tree_bar, False, False, 3)
        self.tree_box.pack_start(self.root_drop, False, False, 0)
        self.tree_box.pack_start(self.scroll_tree, True, True, 0)

        self.connect("key-press-event", self.on_key)
        self.set_layout(layout)
        self.populate(None, self.root, self.store)
        self.watch_path(self.root)

    # ---------------- layout ----------------
    def set_layout(self, layout):
        self.layout = layout
        self._compact_tabbed = False
        for ch in list(self.get_children()):
            self.remove(ch)
        # detach shared widgets from their old containers
        for w in (self.opencode_term, self.editor_pane, self.tree_box, self.tabs,
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
            self.top_h.pack1(self.editor_pane, False, False)
            self.top_h.pack2(self.opencode_term, True, False)
            self.top_h.connect("size-allocate", self.on_top_alloc)
            self.bottom_h = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            self.bottom_h.pack1(self.tree_box, True, False)
            self.bottom_h.pack2(self.tabs, True, False)
            self.main_v = Gtk.Paned.new(Gtk.Orientation.VERTICAL)
            self.main_v.pack1(self.top_h, True, False)
            self.main_v.pack2(self.bottom_h, True, False)
            bar = Gtk.Box(spacing=4)
            lbl = Gtk.Label(xalign=0)
            lbl.set_markup("<b>%s</b>" % GLib.markup_escape_text(os.path.basename(self.root)))
            bar.pack_start(lbl, True, True, 4)
            if self.on_close:
                bx = Gtk.Button(label="✕")
                bx.set_tooltip_text("Close project (kills its opencode)")
                bx.connect("clicked", lambda w: self.on_close(self))
                bar.pack_start(bx, False, False, 2)
            self.pack_start(bar, False, False, 2)
            self.pack_start(self.main_v, True, True, 0)
            self.root_drop.set_visible(True)
            GLib.idle_add(self._compact_sizes)
        else:
            self.top_h = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            self.top_h.pack1(self.editor_pane, False, False)
            self.top_h.pack2(self.opencode_term, True, False)
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
            self.pack_start(self.main_h, True, True, 0)
        GLib.idle_add(self._apply_tabs_state)

    def _compact_sizes(self):
        try:
            w = self.get_allocated_width()
            h = self.get_allocated_height()
            if w > 50:
                self.bottom_h.set_position(w // 2)
            if h > 50:
                self.main_v.set_position(int(h * 0.58))
        except Exception:
            pass
        return False

    # ---------------- editor/terminal visibility ----------------
    def _apply_editor_visibility(self):
        if self.ed_tabs.get_n_pages() == 0:
            self.editor_pane.hide()
        else:
            self.editor_pane.show()

    def _term_visible(self):
        if self.layout == "compact" and self._compact_tabbed:
            return self.opencode_term.get_parent() is self.ed_tabs
        return self.opencode_term.get_visible()

    def _mt_panel_width(self):
        try:
            self.top_h.set_position(self.top_h.get_allocated_width())
        except Exception:
            pass
        return False

    def update_compact(self):
        if self.layout != "compact":
            return
        n = len(self.open_widgets)
        if n >= 2 and not self._compact_tabbed:
            self._compact_tabbed = True
            self.top_h.remove(self.opencode_term)
            if self.opencode_term.get_parent() is None:
                self.opencode_term.show()
                self.ed_tabs.append_page(self.opencode_term, Gtk.Label("OpenCode"))
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(self.opencode_term))
            self.ed_tabs.show_all()
            GLib.idle_add(self._mt_panel_width)
        elif n < 2 and self._compact_tabbed:
            self._compact_tabbed = False
            self.ed_tabs.remove_page(self.ed_tabs.page_num(self.opencode_term))
            self.top_h.pack2(self.opencode_term, True, False)
            self.top_h.show_all()
            self._apply_editor_visibility()

    # ---------------- terminals ----------------
    def make_terminal(self):
        term = Vte.Terminal()
        term.set_font(Pango.FontDescription("Monospace 10"))
        try:
            fg = Gdk.RGBA(); fg.parse("#BBBEBF")
            bg = Gdk.RGBA(); bg.parse("#191A1B")
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
        if term is self.opencode_term:
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

    def spawn_opencode(self):
        if not OPENCODE or not os.path.isfile(OPENCODE) or not os.access(OPENCODE, os.X_OK):
            try:
                dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                        message_type=Gtk.MessageType.ERROR,
                                        buttons=Gtk.ButtonsType.OK,
                                        text="opencode not found",
                                        secondary_text="Set MINI_IDE_OPENCODE to a valid path "
                                                       "or install opencode in PATH.")
                dlg.run()
                dlg.destroy()
            except Exception:
                pass
            return
        self._spawn_async(self.opencode_term, self.root, [OPENCODE],
                          lambda pid: setattr(self, "opencode_pid", pid))

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
        close = Gtk.Button(label="✕")
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
    def populate(self, parent_iter, path, store):
        try:
            entries = sorted(os.scandir(path), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return
        for e in entries:
            if e.name.startswith('.'):
                continue
            kind = "folder" if e.is_dir() else "file"
            row = store.append(parent_iter, [icon_for(e.name, e.is_dir()), e.name, e.path, kind])
            if e.is_dir():
                store.append(row, [None, None, None, None])

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
        try:
            p = file.get_path()
        except Exception:
            p = None
        if p:
            self._handle_fs_event(p, event)
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
        self._refresh_id = GLib.timeout_add(350, self._do_refresh)

    def _handle_fs_event(self, path, event):
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
                doc.conflict = True
                doc.cancel_autosave()
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
                                    text="%s changed outside Mini-IDE" % os.path.basename(doc.path),
                                    secondary_text="You have unsaved edits. Autosave is "
                                                   "suspended until you decide.")
            dlg.add_button("Reload from disk", Gtk.ResponseType.YES)
            dlg.add_button("Keep editor version", Gtk.ResponseType.NO)
            resp = dlg.run()
            dlg.destroy()
            if resp == Gtk.ResponseType.YES:
                self.reload_buffer(doc.buffer, doc.path)
            elif resp == Gtk.ResponseType.NO:
                doc.resolve_keep_local()
                self._update_tab_ui(doc.buffer)
        except Exception:
            pass

    def reload_buffer(self, buf, path):
        doc = self.docs.get(buf)
        strict = bool(doc and doc.strict_utf8)
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
                return
        except OSError:
            return
        self._reloading = True
        try:
            buf.set_text(text)
        finally:
            self._reloading = False
        if doc:
            doc.resolve_reload()
        self._update_tab_ui(buf)

    def _do_refresh(self):
        self._refresh_id = None
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

    def on_name_edited(self, renderer, path_str, new_text):
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
        name = validate_child_name(new_text)
        if not name or kind not in ("file", "folder"):
            if name is None:
                self._name_error_dialog(new_text)
            return
        newp = os.path.join(os.path.dirname(fpath), name)
        if newp != fpath and not os.path.exists(newp) and self.path_inside_root(newp):
            self.rename_path(fpath, newp)

    def rename_path(self, old, new):
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
        if self._pending:
            it = self._pending[0]
            self._pending = None
            try:
                if self.store.iter_is_valid(it):
                    self.store.remove(it)
            except Exception:
                pass
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
        if self._pending:
            it = self._pending[0]
            self._pending = None
            try:
                if self.store.iter_is_valid(it):
                    self.store.remove(it)
            except Exception:
                pass
        base, parent_iter = self.selected_base()
        if parent_iter:
            self.tree.expand_row(self.store.get_path(parent_iter), False)
        icon = load_icon("file" if kind == "newfile" else "folder")
        row = self.store.append(parent_iter, [icon, "", base, kind])
        self._pending = (row, kind, base)
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

    def on_drop(self, tree, ctx, x, y, data, info, time):
        dest = self.root
        info2 = tree.get_path_at_pos(int(x), int(y))
        if info2:
            it = self.store.get_iter(info2[0])
            kind = self.store.get_value(it, 3)
            p = self.store.get_value(it, 2)
            if kind == "folder" and p:
                dest = p
            elif kind == "file" and p:
                dest = os.path.dirname(p)
        if data and data.get_uris():
            for uri in data.get_uris():
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
                except OSError as ex:
                    print("Copy error:", ex)
            self._do_refresh()
        ctx.finish(True, False, time)

    def on_root_drop(self, w, ctx, x, y, data, info, time):
        if data and data.get_uris():
            for uri in data.get_uris():
                try:
                    src = GLib.filename_from_uri(uri)[0]
                except Exception:
                    continue
                dst = os.path.join(self.root, os.path.basename(src))
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
                except OSError as ex:
                    print("Copy error:", ex)
            self._do_refresh()
        ctx.finish(True, False, time)

    def delete_selected(self):
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
        close = Gtk.Button(label="✕")
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
        btn_text = Gtk.Button(label="View text")
        btn_text.connect("clicked", lambda w, p=fpath: self.text_from_table(p))
        bar = Gtk.Box(spacing=4)
        bar.pack_start(btn_text, False, False, 4)
        if truncated:
            note = Gtk.Label(xalign=0)
            note.set_markup("<span size='small' color='#888888'>Showing first 20,000 rows</span>")
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
            w0 = info[0] if info else 0
            h0 = info[1] if info else 0
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
        scroll = Gtk.ScrolledWindow()
        scroll.add(img)
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
        btn_prev = Gtk.Button(label="◀")
        btn_next = Gtk.Button(label="▶")
        btn_zin = Gtk.Button(label="+")
        btn_zout = Gtk.Button(label="−")

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
        btn_play = Gtk.ToggleButton(label="Play")
        btn_stop = Gtk.Button(label="Stop")
        btn_mute = Gtk.ToggleButton(label="Mute")
        scale = Gtk.Scale.new(Gtk.Orientation.HORIZONTAL, Gtk.Adjustment(0, 0, 1, 0.1, 1, 0))
        scale.set_size_request(-1, 24)
        lbl_time = Gtk.Label("00:00 / 00:00")

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
            player.set_property("mute", b.get_active())

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
        bar = Gtk.Box(spacing=6)
        bar.pack_start(btn_play, False, False, 2)
        bar.pack_start(btn_stop, False, False, 2)
        bar.pack_start(btn_mute, False, False, 2)
        bar.pack_start(scale, True, True, 4)
        bar.pack_start(lbl_time, False, False, 4)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(bar, False, False, 8)
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
        if self.layout == "compact" and self._compact_tabbed:
            return
        if self.editor_pane.get_visible() and self._term_visible():
            half = alloc.width // 2
            if abs(paned.get_position() - half) > 30:
                paned.set_position(half)
        elif paned.get_position() < alloc.width - 50:
            paned.set_position(alloc.width)

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

    def toggle_tabs(self, btn=None):
        self._tabs_collapsed = not self._tabs_collapsed
        self._apply_tabs_state()

    def _apply_tabs_state(self):
        if self._tabs_collapsed:
            self.btn_collapse.set_label("▴")
            self.btn_collapse.set_tooltip_text("Show terminal")
            GLib.idle_add(self._collapse_tabs)
        else:
            self.btn_collapse.set_label("▾")
            self.btn_collapse.set_tooltip_text("Hide terminal")
            GLib.idle_add(self._restore_tabs)

    def _collapse_tabs(self):
        try:
            if self.layout == "compact":
                h = self.bottom_h.get_allocated_height()
                self.bottom_h.set_position(max(0, h - 30))
            else:
                h = self.right_v.get_allocated_height()
                self.right_v.set_position(max(0, h - 30))
        except Exception:
            pass
        return False

    def _restore_tabs(self):
        try:
            if self.layout == "compact":
                self.bottom_h.set_position(self.bottom_h.get_allocated_height() // 2)
            else:
                self.right_v.set_position(520)
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
                try:
                    atomic_write(doc.path, self._doc_text(doc))
                except OSError as ex:
                    print("Could not recreate:", ex)
                    return 'abort'
                doc.recreate()
                self.refresh_tree()
                return 'close'
            if resp == Gtk.ResponseType.NO:
                return 'close' if self._save_as_doc(doc) else 'abort'
            if resp == Gtk.ResponseType.APPLY:
                return 'close'
            return 'abort'
        if doc.conflict:
            resp = self._conflict_close_dialog(doc)
            if resp == Gtk.ResponseType.YES:
                if not self.save_buffer(doc.buffer):
                    return 'abort'
            elif resp == Gtk.ResponseType.NO:
                self.reload_buffer(doc.buffer, doc.path)
            else:
                return 'abort'
            return 'close'
        if doc.dirty:
            if not self.save_buffer(doc.buffer):
                resp = self._save_failed_dialog(os.path.basename(doc.path))
                if resp == Gtk.ResponseType.YES:
                    if not self.save_buffer(doc.buffer):
                        return 'abort'
                elif resp == Gtk.ResponseType.NO:
                    return 'close'
                else:
                    return 'abort'
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

    def _save_as_doc(self, doc):
        dlg = Gtk.FileChooserDialog(title="Save As", transient_for=self.get_toplevel(),
                                    action=Gtk.FileChooserAction.SAVE)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dlg.set_current_name(os.path.basename(doc.path))
        if dlg.run() != Gtk.ResponseType.OK:
            dlg.destroy()
            return False
        new = dlg.get_filename()
        dlg.destroy()
        if not new:
            return False
        try:
            atomic_write(new, self._doc_text(doc))
        except OSError as ex:
            print("Could not save as:", ex)
            return False
        self._migrate_doc_path(doc, new)
        doc.save_as(new)
        self._update_tab_ui(doc.buffer)
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
        self._update_tab_ui(buf)

    def _autosave_buffer(self, buf):
        self.save_buffer(buf)

    def save_buffer(self, buf):
        doc = self.docs.get(buf)
        if doc is None or doc.deleted:
            return False
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        try:
            atomic_write(doc.path, text)
        except OSError as ex:
            print("Could not save:", ex)
            doc.dirty = True
            self._update_tab_ui(buf)
            return False
        doc.mark_saved()
        self._update_tab_ui(buf)
        return True

    def save_file(self, btn=None):
        page = self.ed_tabs.get_current_page()
        if page < 0:
            return
        widget = self.ed_tabs.get_nth_page(page)
        for path, (buf, w) in self.ed_paths.items():
            if w is widget:
                self.save_buffer(buf)
                break

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
        """Mata opencode, terminales y audio del panel."""
        if self._shutdown:
            return
        self._shutdown = True
        for doc in list(self.docs.values()):
            if doc.dirty and not doc.deleted and not doc.conflict:
                try:
                    self.save_buffer(doc.buffer)
                except Exception:
                    pass
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
        if self.opencode_pid:
            try:
                os.kill(self.opencode_pid, 15)
            except Exception:
                pass
        for t in self.cmd_terms:
            try:
                t.kill_sync(Vte.TerminalKill.KILL_SHELL, None)
            except Exception:
                pass
        try:
            self.opencode_term.kill_sync(Vte.TerminalKill.KILL_SHELL, None)
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


class MiniIDE(Gtk.Window):
    def __init__(self, root):
        super().__init__()
        self.set_title(os.path.basename(root))
        self.set_default_size(1360, 820)
        self.root = os.path.abspath(root)
        self.recents = load_recents()
        self.panels = []
        self.mode = "normal"

        provider = Gtk.CssProvider()
        provider.load_from_data(VSC_CSS)
        Gtk.StyleContext.add_provider_for_screen(self.get_screen(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.main_panel = ProjectPanel(self.root, "full")
        self.panels.append(self.main_panel)

        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content.pack_start(self.main_panel, True, True, 0)

        btn_openfolder = Gtk.Button(label="Open folder")
        btn_openfolder.connect("clicked", self.open_folder_new_instance)
        self.btn_add = Gtk.Button(label="+ Add project")
        self.btn_add.set_tooltip_text("Add a project to the multitask view")
        self.btn_add.connect("clicked", self.on_add_click)
        self.btn_add.set_no_show_all(True)
        self.btn_add.hide()
        self.btn_multitask = Gtk.Button(label="Multitask")
        self.btn_multitask.set_tooltip_text("Toggle multitask view")
        self.btn_multitask.connect("clicked", self.on_multitask_click)
        self.btn_multitask.set_no_show_all(True)
        self.btn_multitask.set_visible(True)
        self.hb = Gtk.HeaderBar()
        self.hb.set_show_close_button(True)
        self.hb.set_title(os.path.basename(self.root))
        self.hb.pack_start(btn_openfolder)
        self.hb.pack_start(self.btn_add)
        self.hb.pack_start(self.btn_multitask)
        self.set_titlebar(self.hb)

        self.add(self.content)
        self.connect("key-press-event", self.on_win_key)
        save_recents(self.root)

    def on_destroy(self, *args):
        for panel in list(self.panels):
            panel.shutdown()
        Gtk.main_quit()

    def on_delete_event(self, w, ev):
        for panel in list(self.panels):
            if not panel.request_close():
                return True
        return False

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
        self.btn_multitask.set_label("Exit multitask")
        self.btn_add.set_visible(True)
        self.rebuild_layout()

    def exit_multitask(self):
        if not self.panels or self.main_panel is None:
            return
        extra = self.panels[1:]
        if extra:
            names = ", ".join(os.path.basename(p.root) for p in extra)
            dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                    message_type=Gtk.MessageType.QUESTION,
                                    buttons=Gtk.ButtonsType.YES_NO,
                                    text="Exit multitask",
                                    secondary_text="Will close: %s (and their opencode). Continue?" % names)
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.YES:
                return
            for p in extra:
                if not p.request_close():
                    return
            for p in extra:
                p.shutdown()
            self.panels = [self.main_panel]
        self.mode = "normal"
        self.main_panel.set_layout("full")
        self.main_panel.on_close = None
        self.btn_multitask.set_label("Multitask")
        self.btn_add.set_visible(False)
        self.set_title(os.path.basename(self.main_panel.root))
        for ch in list(self.content.get_children()):
            self.content.remove(ch)
        parent = self.main_panel.get_parent()
        if parent is not None:
            parent.remove(self.main_panel)
        self.content.pack_start(self.main_panel, True, True, 0)
        self.content.show_all()
        self.main_panel._apply_editor_visibility()

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
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self.open_project(dlg.get_filename())
        dlg.destroy()

    def close_panel(self, panel):
        if panel not in self.panels:
            return
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.YES_NO,
                                text="Close project",
                                secondary_text="'%s' and its opencode will be closed." % os.path.basename(panel.root))
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.YES:
            return
        if not panel.request_close():
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
            self.set_title("Mini-IDE — add a project")
            box = self.make_empty_slot()
            self.content.pack_start(box, True, True, 0)
            self.content.show_all()
            return
        self._mt_panes = []
        container = self._build_panes(list(self.panels))
        self._mt_container = container
        self.content.pack_start(container, True, True, 0)
        self.content.show_all()
        for p in self.panels:
            p._apply_editor_visibility()
        self.set_title("Multitask — %d project%s" % (len(self.panels),
                                                     "s" if len(self.panels) > 1 else ""))
        GLib.idle_add(self._mt_sizes)

    def _build_panes(self, widgets):
        if len(widgets) == 1:
            return widgets[0]
        mid = len(widgets) // 2
        pane = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
        self._mt_panes.append((pane, mid, len(widgets)))
        pane.pack1(self._build_panes(widgets[:mid]), True, False)
        pane.pack2(self._build_panes(widgets[mid:]), True, False)
        return pane

    def _mt_sizes(self):
        try:
            for pane, left, total in self._mt_panes:
                w = pane.get_allocated_width()
                if w > 50:
                    pane.set_position(int(w * left / total))
        except Exception:
            pass
        return False

    # ---------------- window ----------------
    def open_folder_new_instance(self, btn=None):
        dlg = Gtk.FileChooserDialog(title="Abrir carpeta", transient_for=self,
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
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
                    panel.term_paste(panel.opencode_term)
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
        try:
            rec = json.load(open(RECENT_FILE))
            folder = rec[0] if rec else None
        except Exception:
            folder = None
    if not folder:
        dlg = Gtk.FileChooserDialog(title="Select a project",
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            folder = dlg.get_filename()
        dlg.destroy()
    if not folder:
        sys.exit(0)
    win = MiniIDE(folder)
    win.connect("delete-event", win.on_delete_event)
    win.connect("destroy", win.on_destroy)
    win.show_all()
    if win.main_panel.ed_tabs.get_n_pages() == 0:
        win.main_panel.editor_pane.hide()
    Gtk.main()
