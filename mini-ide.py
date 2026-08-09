#!/usr/bin/env python3
# mini-ide v8: modo multitasking (hasta 3 proyectos en columnas) + modo normal.
import sys, os, shutil, csv, json, subprocess, warnings
warnings.filterwarnings("ignore")
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
OPENCODE = os.environ.get("OPENCODE") or shutil.which("opencode") or os.path.expanduser("~/.opencode/bin/opencode")
ICONS = os.path.expanduser("~/.vscode/extensions/pkief.material-icon-theme-5.37.0/icons")
SCRIPT = os.path.abspath(__file__)
RECENT_FILE = os.path.expanduser("~/.config/mini-ide/recent.json")
MAX_PROJECTS = 3

IMG_EXT = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "tiff", "svg", "avif"}
AUD_EXT = {"mp3", "ogg", "oga", "wav", "flac", "m4a", "opus", "wma", "aac", "mid", "midi"}
CSV_EXT = {"csv", "tsv"}
CSV_COLORS = ["#2E5E3E", "#1F4E6E", "#5E5E1F", "#6E3E1F", "#4A2E6E"]

VSC_CSS = b"""
window { background-color: #1F1F1F; }
box, paned, scrolledwindow, notebook { background-color: #1F1F1F; }
headerbar { background-color: #3C3C3C; min-height: 0px; padding: 1px 3px; }
headerbar button { background-color: #3C3C3C; color: #CCCCCC; border-color: #505050; min-height: 16px; min-width: 22px; padding: 0px 4px; }
headerbar button:hover { background-color: #505050; }
headerbar label { color: #CCCCCC; font-size: 13px; }
treeview { background-color: #252526; color: #CCCCCC; }
treeview:selected { background-color: #094771; color: #FFFFFF; }
treeview:selected:backdrop { background-color: #37373D; }
treeview.view { border-color: #252526; }
paned > separator { background-color: #333333; }
button { color: #CCCCCC; background-color: #3C3C3C; }
button:hover { background-color: #505050; }
entry { background-color: #3C3C3C; color: #CCCCCC; }
scale trough { background-color: #3C3C3C; }
.dim-label { color: #969696; }
label { color: #CCCCCC; }
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
    """Un proyecto completo: opencode + editor + arbol + terminales.
    layout 'full' (modo normal) o 'compact' (multitarea)."""

    def __init__(self, root, layout="full", on_close=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.root = os.path.abspath(root)
        self.layout = layout
        self.on_close = on_close
        self._save_id = None
        self._refresh_id = None
        self._pending = None
        self.monitors = {}
        self.open_widgets = {}
        self.ed_paths = {}
        self.buf_path = {}
        self.players = []
        self.opencode_pid = None

        self.lang_mgr = GtkSource.LanguageManager.get_default()
        self.style_mgr = GtkSource.StyleSchemeManager.get_default()
        self.dark_scheme = self.style_mgr.get_scheme("vs-dark") or self.style_mgr.get_scheme("oblivion")

        # editor con pestanas
        self.ed_tabs = Gtk.Notebook()
        self.ed_tabs.set_scrollable(True)
        self.ed_tabs.set_tab_pos(Gtk.PositionType.TOP)
        self.editor_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.editor_pane.pack_start(self.ed_tabs, True, True, 0)
        self.editor_pane.hide()

        # opencode
        self.opencode_term = self.make_terminal()
        self.spawn_opencode()

        # terminales de comandos
        self.tabs = Gtk.Notebook()
        self.tabs.set_scrollable(True)
        self.tabs.set_tab_pos(Gtk.PositionType.TOP)
        self.cmd_terms = []
        plus_btn = Gtk.Button(label="+")
        plus_btn.set_tooltip_text("Nueva terminal (Ctrl+T)")
        plus_btn.connect("clicked", lambda w: self.add_command_tab())
        self.tabs.set_action_widget(plus_btn, Gtk.PackType.END)
        plus_btn.show_all()
        self.add_command_tab()

        # arbol
        self.store = Gtk.TreeStore(GdkPixbuf.Pixbuf, str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        r_icon = Gtk.CellRendererPixbuf()
        r_name = Gtk.CellRendererText()
        r_name.set_property("editable", False)
        r_name.connect("edited", self.on_name_edited)
        r_name.connect("editing-canceled", self.on_editing_canceled)
        self.r_name = r_name
        col = Gtk.TreeViewColumn("Archivos")
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

        btn_newfile = Gtk.Button()
        btn_newfile.set_image(Gtk.Image.new_from_pixbuf(load_icon("file")))
        btn_newfile.set_tooltip_text("Nuevo archivo")
        btn_newfile.connect("clicked", lambda w: self.start_new("newfile"))
        btn_newfolder = Gtk.Button()
        btn_newfolder.set_image(Gtk.Image.new_from_pixbuf(load_icon("folder")))
        btn_newfolder.set_tooltip_text("Nueva carpeta")
        btn_newfolder.connect("clicked", lambda w: self.start_new("newfolder"))

        self.path_lbl = Gtk.Label(xalign=0)
        self.path_lbl.set_markup("<span size='small' color='#888888'>%s</span>" % self.root)
        self.tree_bar = Gtk.Box(spacing=4)
        self.tree_bar.pack_start(self.path_lbl, True, True, 6)
        self.tree_bar.pack_end(btn_newfolder, False, False, 0)
        self.tree_bar.pack_end(btn_newfile, False, False, 0)
        self.tree_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tree_box.pack_start(self.tree_bar, False, False, 3)
        self.tree_box.pack_start(self.scroll_tree, True, True, 0)

        self.connect("key-press-event", self.on_key)
        self.set_layout(layout)
        self.populate(None, self.root, self.store)
        self.watch_path(self.root)

    # ---------------- layout ----------------
    def set_layout(self, layout):
        self.layout = layout
        for ch in list(self.get_children()):
            self.remove(ch)
        # despegar widgets compartidos de sus contenedores viejos
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
            lbl.set_markup("<b>%s</b>" % os.path.basename(self.root))
            bar.pack_start(lbl, True, True, 4)
            if self.on_close:
                bx = Gtk.Button(label="✕")
                bx.set_tooltip_text("Cerrar proyecto (mata su opencode)")
                bx.connect("clicked", lambda w: self.on_close(self))
                bar.pack_start(bx, False, False, 2)
            self.pack_start(bar, False, False, 2)
            self.pack_start(self.main_v, True, True, 0)
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
            self.pack_start(self.main_h, True, True, 0)

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

    # ---------------- terminales ----------------
    def make_terminal(self):
        term = Vte.Terminal()
        term.set_font(Pango.FontDescription("Monospace 10"))
        try:
            fg = Gdk.RGBA(); fg.parse("#CCCCCC")
            bg = Gdk.RGBA(); bg.parse("#1E1E1E")
            term.set_color_foreground(fg)
            term.set_color_background(bg)
        except Exception:
            pass
        term.connect("selection-changed", self.on_term_selection)
        return term

    def spawn_opencode(self):
        try:
            ok, pid = self.opencode_term.spawn_sync(Vte.PtyFlags.DEFAULT, self.root,
                                                    [OPENCODE], [], GLib.SpawnFlags.DEFAULT,
                                                    None, None, None)
            self.opencode_pid = pid if ok else None
        except Exception:
            self.opencode_pid = None

    def on_term_selection(self, term):
        if not term.has_selection():
            return
        try:
            res = term.get_text(None, None, True)
            txt = res[0] if isinstance(res, tuple) else res
        except Exception:
            try:
                txt = term.get_text()
            except Exception:
                return
        if txt:
            try:
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(txt, -1)
            except Exception:
                pass

    def add_command_tab(self, btn=None):
        term = self.make_terminal()
        term.spawn_sync(Vte.PtyFlags.DEFAULT, self.root,
                        ["/bin/bash"], [], GLib.SpawnFlags.DEFAULT,
                        None, None, None)
        self.cmd_terms.append(term)
        lbl = Gtk.Label("T%d" % len(self.cmd_terms))
        close = Gtk.Button(label="✕")
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_focus_on_click(False)
        close.connect("clicked", self.close_tab, term)
        tab = Gtk.Box(spacing=4)
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

    # ---------------- arbol ----------------
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
        if self._refresh_id:
            GLib.source_remove(self._refresh_id)
        self._refresh_id = GLib.timeout_add(350, self._do_refresh)

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

    def on_name_edited(self, renderer, path_str, new_text):
        if self._pending:
            it, kind, base = self._pending
            self._pending = None
            try:
                cur_path = self.store.get_path(it).to_string()
            except Exception:
                cur_path = None
            if cur_path == path_str:
                name = new_text.strip()
                if not name:
                    try:
                        if self.store.iter_is_valid(it):
                            self.store.remove(it)
                    except Exception:
                        pass
                    return
                p = os.path.join(base, name)
                try:
                    if kind == "newfile":
                        with open(p, 'w') as f:
                            f.write("")
                    else:
                        os.makedirs(p, exist_ok=True)
                    self.refresh_tree()
                    self.select_path(p)
                    if kind == "newfile":
                        self.open_file(p)
                except OSError as ex:
                    print("Error:", ex)
                return
        it = self.store.get_iter(path_str)
        if not it:
            return
        kind = self.store.get_value(it, 3)
        fpath = self.store.get_value(it, 2)
        name = new_text.strip()
        if not name or kind not in ("file", "folder"):
            return
        newp = os.path.join(os.path.dirname(fpath), name)
        if newp != fpath and not os.path.exists(newp):
            try:
                os.rename(fpath, newp)
                self.refresh_tree()
                self.select_path(newp)
            except OSError as ex:
                print("Error:", ex)

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
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                except OSError as ex:
                    print("Error copiando:", ex)
            self._do_refresh()
        ctx.finish(True, False, time)

    def delete_selected(self):
        sel = self.tree.get_selection().get_selected()
        if not sel[1]:
            return
        fpath = self.store.get_value(sel[1], 2)
        if not fpath or not os.path.exists(fpath):
            return
        kind = "carpeta" if os.path.isdir(fpath) else "archivo"
        dlg = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.YES_NO,
                                text="Eliminar %s" % kind,
                                secondary_text="¿Eliminar %s '%s' definitivamente?"
                                               % (kind, os.path.basename(fpath)))
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.YES:
            try:
                if os.path.isdir(fpath):
                    shutil.rmtree(fpath)
                else:
                    os.remove(fpath)
                self.refresh_tree()
            except OSError as ex:
                print("Error:", ex)

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
        tab = Gtk.Box(spacing=4)
        tab.pack_start(lbl, False, False, 0)
        tab.pack_start(close, False, False, 0)
        tab.show_all()
        self.open_widgets[fpath] = content_widget
        self.ed_tabs.append_page(widget, tab)
        self.ed_tabs.set_current_page(self.ed_tabs.page_num(widget))
        self.editor_pane.show_all()

    def open_text(self, fpath):
        if fpath in self.ed_paths:
            buf, page = self.ed_paths[fpath]
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(page))
            self.editor_pane.show_all()
            return
        try:
            with open(fpath, 'r', errors='replace') as f:
                text = f.read()
        except OSError as ex:
            print("No se pudo abrir:", ex)
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
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        scroll.show_all()
        self.ed_paths[fpath] = (buffer, scroll)
        self.buf_path[buffer] = fpath
        buffer.connect("changed", self.on_buffer_changed)
        self.make_tab(scroll, fpath, scroll)

    def open_table(self, fpath):
        if fpath in self.open_widgets:
            self.ed_tabs.set_current_page(self.ed_tabs.page_num(self.open_widgets[fpath]))
            self.editor_pane.show_all()
            return
        delim = '\t' if fpath.rsplit(".", 1)[-1].lower() == "tsv" else ','
        try:
            with open(fpath, newline='', errors='replace') as f:
                rows = list(csv.reader(f, delimiter=delim))
        except OSError as ex:
            print("Error:", ex)
            return
        if not rows:
            return self.open_text(fpath)
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
        btn_text = Gtk.Button(label="Ver texto")
        btn_text.connect("clicked", lambda w, p=fpath: self.text_from_table(p))
        bar = Gtk.Box(spacing=4)
        bar.pack_start(btn_text, False, False, 4)
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
            pb = GdkPixbuf.Pixbuf.new_from_file(fpath)
        except Exception as ex:
            print("Error imagen:", ex)
            return self.open_text(fpath)
        w, h = pb.get_width(), pb.get_height()
        if max(w, h) > 2200:
            s = 2200 / max(w, h)
            pb = pb.scale_simple(int(w * s), int(h * s), GdkPixbuf.InterpType.BILINEAR)
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
            print("Error PDF:", ex)
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
            s = state["scale"]
            import cairo as _cairo
            surface = _cairo.ImageSurface(_cairo.FORMAT_ARGB32, int(w * s), int(h * s))
            ctx = _cairo.Context(surface)
            p.render(ctx)
            pb = GdkPixbuf.Pixbuf.new_from_data(
                surface.get_data(), GdkPixbuf.Colorspace.RGB, True, 8,
                int(w * s), int(h * s), surface.get_stride())
            img.set_from_pixbuf(pb)
            lbl.set_text("Página %d/%d" % (state["page"] + 1, state["doc"].get_n_pages()))
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
        bus.connect("message", on_eos)

        def update():
            pos, okp = player.query_position(Gst.Format.TIME)
            dur, okd = player.query_duration(Gst.Format.TIME)
            if okp and okd and dur > 0:
                scale.set_range(0, dur / Gst.SECOND)
                scale.set_value(pos / Gst.SECOND)
                lbl_time.set_text("%02d:%02d / %02d:%02d" % (
                    pos // Gst.SECOND // 60, pos // Gst.SECOND % 60,
                    dur // Gst.SECOND // 60, dur // Gst.SECOND % 60))
            elif okp:
                lbl_time.set_text("%02d:%02d" % (pos // Gst.SECOND // 60, pos // Gst.SECOND % 60))
            return True
        GLib.timeout_add(400, update)
        bar = Gtk.Box(spacing=6)
        bar.pack_start(btn_play, False, False, 2)
        bar.pack_start(btn_stop, False, False, 2)
        bar.pack_start(btn_mute, False, False, 2)
        bar.pack_start(scale, True, True, 4)
        bar.pack_start(lbl_time, False, False, 4)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(bar, False, False, 8)
        vbox.show_all()
        self.make_tab(vbox, fpath, vbox)

    def close_file_tab(self, btn, fpath, quiet=False):
        widget = self.open_widgets.pop(fpath, None)
        if widget:
            self.ed_tabs.remove_page(self.ed_tabs.page_num(widget))
        entry = self.ed_paths.pop(fpath, None)
        if entry:
            self.buf_path.pop(entry[0], None)
        if self.ed_tabs.get_n_pages() == 0:
            self.editor_pane.hide()

    def on_top_alloc(self, paned, alloc):
        if self.editor_pane.get_visible():
            half = alloc.width // 2
            if abs(paned.get_position() - half) > 30:
                paned.set_position(half)
        elif paned.get_position() < alloc.width - 50:
            paned.set_position(alloc.width)

    # ---------------- guardado ----------------
    def on_buffer_changed(self, buf):
        if not self.buf_path.get(buf):
            return
        if self._save_id:
            GLib.source_remove(self._save_id)
        self._save_id = GLib.timeout_add(800, self._autosave)

    def _autosave(self):
        self._save_id = None
        self.save_file()
        return False

    def save_file(self, btn=None):
        page = self.ed_tabs.get_current_page()
        if page < 0:
            return
        widget = self.ed_tabs.get_nth_page(page)
        for path, (buf, w) in self.ed_paths.items():
            if w is widget:
                try:
                    with open(path, 'w') as f:
                        f.write(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))
                except OSError as ex:
                    print("No se pudo guardar:", ex)
                break

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
        for p in self.players:
            try:
                p.set_state(Gst.State.NULL)
            except Exception:
                pass
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

        btn_openfolder = Gtk.Button(label="Abrir carpeta")
        btn_openfolder.connect("clicked", self.open_folder_new_instance)
        self.btn_multitask = Gtk.Button(label="Multitarea")
        self.btn_multitask.connect("clicked", self.toggle_multitask)
        self.hb = Gtk.HeaderBar()
        self.hb.set_show_close_button(True)
        self.hb.set_title(os.path.basename(self.root))
        self.hb.pack_start(btn_openfolder)
        self.hb.pack_start(self.btn_multitask)
        self.set_titlebar(self.hb)

        self.add(self.content)
        self.connect("key-press-event", self.on_win_key)
        save_recents(self.root)

    # ---------------- multitarea ----------------
    def toggle_multitask(self, btn=None):
        if self.mode == "normal":
            self.enter_multitask()
        else:
            self.exit_multitask()

    def enter_multitask(self):
        self.mode = "multitask"
        self.main_panel.set_layout("compact")
        self.btn_multitask.set_label("Salir multitarea")
        self.set_title("Multitarea — %d proyecto" % len(self.panels))
        self.rebuild_layout()

    def exit_multitask(self):
        extra = self.panels[1:]
        if extra:
            names = ", ".join(os.path.basename(p.root) for p in extra)
            dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                    message_type=Gtk.MessageType.QUESTION,
                                    buttons=Gtk.ButtonsType.YES_NO,
                                    text="Salir de multitarea",
                                    secondary_text="Se cerrarán: %s (y sus opencode). ¿Continuar?" % names)
            resp = dlg.run()
            dlg.destroy()
            if resp != Gtk.ResponseType.YES:
                return
            for p in extra:
                p.shutdown()
            self.panels = [self.main_panel]
        self.mode = "normal"
        self.main_panel.set_layout("full")
        self.btn_multitask.set_label("Multitarea")
        self.set_title(os.path.basename(self.root))
        for ch in list(self.content.get_children()):
            self.content.remove(ch)
        parent = self.main_panel.get_parent()
        if parent is not None:
            parent.remove(self.main_panel)
        self.content.pack_start(self.main_panel, True, True, 0)
        self.content.show_all()

    def make_empty_slot(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup("<b>Proyecto nuevo</b>")
        box.pack_start(lbl, False, False, 8)
        if self.recents:
            lbl2 = Gtk.Label("Recientes:", xalign=0)
            box.pack_start(lbl2, False, False, 2)
            for folder in self.recents[:6]:
                b = Gtk.Button()
                inner = Gtk.Box(spacing=6)
                inner.pack_start(Gtk.Image.new_from_pixbuf(icon_for(os.path.basename(folder), True)), False, False, 0)
                inner.pack_start(Gtk.Label(os.path.basename(folder), xalign=0), True, True, 0)
                b.add(inner)
                b.connect("clicked", lambda w, f=folder: self.open_project(f))
                box.pack_start(b, False, False, 0)
        btn = Gtk.Button(label="Elegir carpeta…")
        btn.connect("clicked", self.browse_project)
        box.pack_start(btn, False, False, 4)
        return box

    def open_project(self, folder):
        if folder not in [p.root for p in self.panels]:
            panel = ProjectPanel(folder, "compact", on_close=self.close_panel)
            self.panels.append(panel)
            save_recents(folder)
            self.rebuild_layout()

    def browse_project(self, btn=None):
        dlg = Gtk.FileChooserDialog(title="Abrir proyecto en multitarea", transient_for=self,
                                    action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if dlg.run() == Gtk.ResponseType.OK:
            self.open_project(dlg.get_filename())
        dlg.destroy()

    def close_panel(self, panel):
        if panel is self.main_panel:
            return
        dlg = Gtk.MessageDialog(transient_for=self, modal=True,
                                message_type=Gtk.MessageType.WARNING,
                                buttons=Gtk.ButtonsType.YES_NO,
                                text="Cerrar proyecto",
                                secondary_text="Se cerrará '%s' y su opencode." % os.path.basename(panel.root))
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.YES:
            return
        panel.shutdown()
        self.panels.remove(panel)
        if len(self.panels) == 1:
            self.exit_multitask()
        else:
            self.rebuild_layout()

    def rebuild_layout(self):
        for ch in list(self.content.get_children()):
            self.content.remove(ch)
        for p in self.panels:
            parent = p.get_parent()
            if parent is not None:
                parent.remove(p)
        widgets = []
        for i in range(MAX_PROJECTS):
            if i < len(self.panels):
                widgets.append(self.panels[i])
            else:
                widgets.append(self.make_empty_slot())
        container = None
        if MAX_PROJECTS == 2:
            container = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            container.pack1(widgets[0], True, False)
            container.pack2(widgets[1], True, False)
        else:
            p23 = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            p23.pack1(widgets[1], True, False)
            p23.pack2(widgets[2], True, False)
            container = Gtk.Paned.new(Gtk.Orientation.HORIZONTAL)
            container.pack1(widgets[0], True, False)
            container.pack2(p23, True, False)
            self._p23 = p23
        self._mt_container = container
        self.content.pack_start(container, True, True, 0)
        self.content.show_all()
        self.set_title("Multitarea — %d proyecto%s" % (len(self.panels), "s" if len(self.panels) > 1 else ""))
        GLib.idle_add(self._mt_sizes)

    def _mt_sizes(self):
        try:
            w = self._mt_container.get_allocated_width()
            if w > 50:
                self._mt_container.set_position(w // MAX_PROJECTS)
                if MAX_PROJECTS == 3:
                    rest = w - w // MAX_PROJECTS
                    self._p23.set_position(rest // 2)
        except Exception:
            pass
        return False

    # ---------------- ventana ----------------
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

    def on_win_key(self, w, ev):
        if self.mode == "multitask" and ev.state & Gdk.ModifierType.CONTROL_MASK:
            k = Gdk.keyval_name(ev.keyval)
            if k in ("1", "2", "3"):
                idx = int(k) - 1
                if idx < len(self.panels):
                    self.panels[idx].tree.grab_focus()
                return True
        return False

if __name__ == "__main__":
    folder = FOLDER
    if folder == "--last":
        try:
            rec = json.load(open(RECENT_FILE))
            folder = rec[0] if rec else os.getcwd()
        except Exception:
            folder = os.getcwd()
    win = MiniIDE(folder)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    if win.main_panel.ed_tabs.get_n_pages() == 0:
        win.main_panel.editor_pane.hide()
    Gtk.main()
