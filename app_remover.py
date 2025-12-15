import os
import subprocess
import tkinter as tk
from tkinter import messagebox
import plistlib
import threading
import shutil
import time
import math
import sys

# Try imports for new features, fallback if missing
try:
    import customtkinter as ctk
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_MODERN_UI = True
except ImportError:
    HAS_MODERN_UI = False
    print("Warning: customtkinter or tkinterdnd2 not found. Falling back to standard tk logic or partial functionality.")

# ==========================
# CONSTANTS & CONFIG
# ==========================
SYSTEM_APPS_PATH = "/System/Applications"
USER_APPS_PATHS = [
    "/Applications",
    os.path.expanduser("~/Applications")
]

# Configure CTk
if HAS_MODERN_UI:
    ctk.set_appearance_mode("System")  
    ctk.set_default_color_theme("blue")

# Known complex app paths that don't match Bundle ID (Legacy/Fallback)
KNOWN_APPS_PATHS = {
    "com.google.Chrome": [
        "~/Library/Application Support/Google/Chrome",
        "~/Library/Caches/Google/Chrome"
    ],
    "com.discord": [
        "~/Library/Application Support/discord",
        "~/Library/Caches/com.discord"
    ]
}

# ==========================
# CORE ENGINE (Enhanced)
# ==========================
class AppRemoverEngine:
    """
    Enhanced Engine: Scanning, Leftovers, Reset, Orphans, Startup Items.
    """
    
    def get_installed_apps(self, progress_callback=None):
        """Scans standard application directories."""
        apps = []
        app_paths_found = []

        # Gather all .app paths
        for folder in USER_APPS_PATHS:
            if not os.path.exists(folder):
                continue
            try:
                for entry in os.listdir(folder):
                    full_path = os.path.join(folder, entry)
                    if entry.endswith(".app") and not full_path.startswith(SYSTEM_APPS_PATH):
                        app_paths_found.append(full_path)
            except Exception:
                pass

        total_apps = len(app_paths_found)
        for i, full_path in enumerate(app_paths_found):
            if progress_callback:
                progress_callback(i + 1, total_apps, f"Scanning: {os.path.basename(full_path)}")
            
            try:
                name = os.path.basename(full_path)
                size_bytes = self._get_size(full_path)
                meta = self._get_app_metadata(full_path)
                
                apps.append({
                    "name": name,
                    "path": full_path,
                    "size": size_bytes,
                    "size_str": self._format_size(size_bytes),
                    "bundle_id": meta["id"],
                    "bundle_name": meta["bundle_name"]
                })
            except Exception:
                pass

        return sorted(apps, key=lambda x: x["name"].lower())

    def find_leftovers(self, app_data):
        """Finds related files using mdfind AND smart heuristics."""
        bundle_id = app_data.get("bundle_id")
        bundle_name = app_data.get("bundle_name") # e.g. "Code"
        app_path = app_data.get("path")
        
        print(f"DEBUG: Finding leftovers for {app_data.get('name')} (ID: {bundle_id}, Name: {bundle_name})...")
        
        found_paths = set()
        
        # 1. MDFIND (Spotlight)
        if bundle_id:
            try:
                home = os.path.expanduser("~")
                cmd = ["mdfind", "-onlyin", home, bundle_id]
                output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
                if output:
                    for line in output.split('\n'):
                        path = line.strip()
                        if path and path != app_path and not path.startswith(app_path):
                            if self._is_safe_to_delete_candidate(path):
                                found_paths.add(path)
            except Exception as e:
                print(f"DEBUG: mdfind error: {e}")

        # 2. Standard Paths (Bundle ID based)
        if bundle_id:
            manual_checks = [
                os.path.expanduser(f"~/Library/Caches/{bundle_id}"),
                os.path.expanduser(f"~/Library/Preferences/{bundle_id}.plist"),
                os.path.expanduser(f"~/Library/Saved Application State/{bundle_id}.savedState"),
                os.path.expanduser(f"~/Library/Application Support/{bundle_id}"),
                os.path.expanduser(f"~/Library/Containers/{bundle_id}"),
                os.path.expanduser(f"~/Library/HTTPStorages/{bundle_id}"),
                os.path.expanduser(f"~/Library/Cookies/{bundle_id}.binarycookies"),
                os.path.expanduser(f"~/Library/WebKit/{bundle_id}")
            ]
            for p in manual_checks:
                if os.path.exists(p) and p != app_path:
                     if self._is_safe_to_delete_candidate(p):
                         found_paths.add(p)

        # 3. Smart Heuristics (Bundle Name based)
        # Check standard folders for 'bundle_name' (e.g. "Code")
        if bundle_name and bundle_name != bundle_id: 
            print(f"DEBUG: Checking smart heuristics for name '{bundle_name}'...")
            smart_checks = [
                os.path.expanduser(f"~/Library/Application Support/{bundle_name}"),
                os.path.expanduser(f"~/Library/Caches/{bundle_name}"),
                os.path.expanduser(f"~/Library/Saved Application State/{bundle_name}.savedState") # Rare but possible
            ]
            for p in smart_checks:
                if os.path.exists(p) and p != app_path:
                    # HEURISTIC SAFETY CHECK: Ensure we don't match common words like "Python" or "Java" unless strict
                    if self._is_safe_to_delete_candidate(p):
                        print(f"DEBUG: Found heuristic match: {p}")
                        found_paths.add(p)

        # 4. Known Complex Paths (Hardcoded overrides)
        if bundle_id and bundle_id in KNOWN_APPS_PATHS:
            print(f"DEBUG: Checking known paths for {bundle_id}...")
            for kp in KNOWN_APPS_PATHS[bundle_id]:
                full_kp = os.path.expanduser(kp)
                if os.path.exists(full_kp):
                    if self._is_safe_to_delete_candidate(full_kp):
                        print(f"DEBUG: Found known path: {full_kp}")
                        found_paths.add(full_kp)

        results = sorted(list(found_paths))
        print(f"DEBUG: Found {len(results)} leftovers: {results}")
        return results

    def move_to_trash(self, path):
        """Moves path to Trash via AppleScript."""
        if not os.path.exists(path):
            return
        print(f"DEBUG: Moving to trash: {path}")
        clean_path = path.replace('"', '\\"')
        cmd = ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{clean_path}"']
        subprocess.run(cmd, stderr=subprocess.DEVNULL)

    def reset_app(self, app_data):
        """
        Resets an app by deleting its extras (containers, caches, prefs) but KEEPING the .app bundle.
        """
        print(f"DEBUG: Starting RESET for {app_data.get('name')}")
        leftovers = self.find_leftovers(app_data)
        deleted_count = 0
        for item in leftovers:
            self.move_to_trash(item)
            deleted_count += 1
        print(f"DEBUG: Reset complete. Moved {deleted_count} items to trash.")
        return deleted_count

    def scan_orphans(self, installed_bundle_ids, progress_callback=None):
        """
        Scans common library paths for folders that look like bundle IDs
        BUT are not in the currently installed list.
        """
        orphans = []
        scan_dirs = [
            os.path.expanduser("~/Library/Containers"),
            os.path.expanduser("~/Library/Application Support"),
            os.path.expanduser("~/Library/Caches"),
            os.path.expanduser("~/Library/Preferences")
        ]
        
        installed_ids_set = set(installed_bundle_ids)
        
        total_steps = len(scan_dirs)
        current_step = 0
        
        for d in scan_dirs:
            current_step += 1
            if progress_callback:
                progress_callback(current_step, total_steps, f"Scanning orphans in {os.path.basename(d)}")
                
            if not os.path.exists(d): 
                continue
                
            try:
                for entry in os.listdir(d):
                    # Heuristic: Check if it looks like a bundle ID (contains dots, >2 parts)
                    if "." in entry and len(entry.split(".")) >= 3:
                        clean_id = entry.replace(".plist", "")
                        if clean_id.startswith("com.apple."): continue
                        if clean_id not in installed_ids_set:
                            full_path = os.path.join(d, entry)
                            size = self._get_size(full_path)
                            orphans.append({
                                "name": entry,
                                "path": full_path,
                                "size": size,
                                "size_str": self._format_size(size),
                                "probable_id": clean_id
                            })
            except Exception:
                pass
                
        return sorted(orphans, key=lambda x: x["size"], reverse=True)

    def get_startup_items(self):
        """
        Scans User Login Items (Apps) AND LaunchAgents/Daemons.
        """
        items = []
        
        # 1. Login Items via AppleScript
        print("DEBUG: Fetching Login Items via AppleScript...")
        try:
            names_raw = subprocess.check_output(
                ['osascript', '-e', 'tell application "System Events" to get name of every login item'], 
                stderr=subprocess.DEVNULL,
                timeout=5
            ).decode().strip()
            
            names = names_raw.split(', ')
            print(f"DEBUG: Found login items: {names}")
            
            for name in names:
                if not name: continue
                items.append({
                    "name": name.strip(),
                    "path": "Login Item (System Settings)",
                    "type": "Login Item",
                    "location": "System Settings",
                    "can_delete": True
                })
        except subprocess.TimeoutExpired:
            print("DEBUG: AppleScript timed out!")
        except Exception as e:
            print(f"DEBUG: AppleScript error: {e}")

        # 2. Launch Agents
        print("DEBUG: Scanning LaunchAgents...")
        paths = [
            os.path.expanduser("~/Library/LaunchAgents"),
            "/Library/LaunchAgents",
            "/Library/LaunchDaemons"
        ]
        
        for p in paths:
            if not os.path.exists(p): continue
            try:
                for entry in os.listdir(p):
                    if entry.endswith(".plist") and not entry.startswith("com.apple."):
                        full_path = os.path.join(p, entry)
                        items.append({
                            "name": entry,
                            "path": full_path,
                            "location": p,
                            "type": "Launch Agent"
                        })
            except Exception:
                pass
        return items

    def remove_startup_item(self, item):
        if item.get("type") == "Login Item":
            name = item["name"]
            cmd = ['osascript', '-e', f'tell application "System Events" to delete login item "{name}"']
            subprocess.run(cmd, stderr=subprocess.DEVNULL)
        else:
            path = item.get("path")
            if path and os.path.exists(path):
                subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", path], stderr=subprocess.DEVNULL)
                subprocess.run(["launchctl", "unload", path], stderr=subprocess.DEVNULL)
                self.move_to_trash(path)

    def disable_startup_item(self, item):
        """
        Disables a startup item without deleting the file.
        """
        if item.get("type") == "Login Item":
            # For Login Items, removing from the list is effectively disabling.
            self.remove_startup_item(item)
        else:
            # LaunchAgent - Unload but KEEP file
            path = item.get("path")
            if path and os.path.exists(path):
                subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", path], stderr=subprocess.DEVNULL)
                subprocess.run(["launchctl", "unload", "-w", path], stderr=subprocess.DEVNULL)

    # --- Helpers ---
    def _is_safe_to_delete_candidate(self, path):
        forbidden_exact = [
            os.path.expanduser("~"),
            os.path.expanduser("~/Desktop"),
            os.path.expanduser("~/Documents"),
            os.path.expanduser("~/Downloads"),
            "/Applications"
        ]
        if path in forbidden_exact: return False
        return True

    def _get_size(self, path):
        total_size = 0
        try:
            if os.path.isfile(path):
                total_size = os.path.getsize(path)
            elif os.path.isdir(path):
                with os.scandir(path) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False):
                            total_size += entry.stat().st_size
                        elif entry.is_dir(follow_symlinks=False):
                            total_size += self._get_size(entry.path)
        except Exception:
            pass
        return total_size

    def _format_size(self, size_bytes):
        if size_bytes == 0: return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"

    def _get_app_metadata(self, app_path):
        """Returns dict with bundle_id and bundle_name (CFBundleName)."""
        plist_path = os.path.join(app_path, "Contents", "Info.plist")
        meta = {"id": None, "bundle_name": None}
        
        if os.path.exists(plist_path):
            try:
                with open(plist_path, 'rb') as fp:
                    pl = plistlib.load(fp)
                    meta["id"] = pl.get("CFBundleIdentifier")
                    meta["bundle_name"] = pl.get("CFBundleName") 
            except Exception:
                pass
        return meta

# ==========================
# GUI (CustomTkinter)
# ==========================
class ModernAppRemover(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self):
        super().__init__()
        self.TkdndVersion = TkinterDnD._require(self)
        
        self.title("App Remover Pro")
        self.geometry("900x700")
        
        self.engine = AppRemoverEngine()
        self.all_apps = []
        self.filtered_apps = []
        self.orphans = []
        self.startup_items = []
        
        # Grid Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self._init_sidebar()
        self._init_pages()
        
        # Select first page
        self.select_frame("uninstall")

        # Initial Scan
        self.after(500, self.start_full_scan)

    def _init_sidebar(self):
        self.sidebar_frame = ctk.CTkFrame(self, width=180, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1)
        
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="🚀 Cleaner", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.btn_uninstall = ctk.CTkButton(self.sidebar_frame, text="Apps & leftovers", fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"), command=lambda: self.select_frame("uninstall"))
        self.btn_uninstall.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        
        self.btn_orphans = ctk.CTkButton(self.sidebar_frame, text="Orphaned Files", fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"), command=lambda: self.select_frame("orphans"))
        self.btn_orphans.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.btn_startup = ctk.CTkButton(self.sidebar_frame, text="Startup Items", fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"), command=lambda: self.select_frame("startup"))
        self.btn_startup.grid(row=3, column=0, padx=20, pady=10, sticky="ew")

        # Drag Drop area visual
        self.drop_label = ctk.CTkLabel(self.sidebar_frame, text="Drag & Drop \n.app here", text_color="gray")
        self.drop_label.grid(row=5, column=0, padx=20, pady=20, sticky="s")
        
        # Register DND
        self.drop_target_register(DND_FILES)
        self.dnd_bind('<<Drop>>', self.on_drop)

    def _init_pages(self):
        # 1. Uninstall Page
        self.frame_uninstall = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        
        # Search
        self.search_entry = ctk.CTkEntry(self.frame_uninstall, placeholder_text="Search apps...")
        self.search_entry.pack(fill="x", padx=20, pady=10)
        self.search_entry.bind("<KeyRelease>", self.on_search)
        
        # App List
        self.list_cnt_uninstall = ctk.CTkFrame(self.frame_uninstall)
        self.list_cnt_uninstall.pack(fill="both", expand=True, padx=20, pady=10)
        self.tree_apps = self._create_treeview(self.list_cnt_uninstall, ("name", "bundle", "size"))
        
        # Actions
        self.btn_refresh = ctk.CTkButton(self.frame_uninstall, text="Refresh", command=self.start_full_scan)
        self.btn_refresh.pack(side="left", padx=20, pady=20)
        
        self.btn_reset = ctk.CTkButton(self.frame_uninstall, text="Reset App", fg_color="#F39C12", command=self.confirm_reset)
        self.btn_reset.pack(side="right", padx=10, pady=20)

        self.btn_delete = ctk.CTkButton(self.frame_uninstall, text="Uninstall App", fg_color="#C0392B", command=self.confirm_uninstall)
        self.btn_delete.pack(side="right", padx=(0, 20), pady=20)
        
        # 2. Orphans Page
        self.frame_orphans = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        
        self.list_cnt_orphans = ctk.CTkFrame(self.frame_orphans)
        self.list_cnt_orphans.pack(fill="both", expand=True, padx=20, pady=10)
        self.tree_orphans = self._create_treeview(self.list_cnt_orphans, ("name", "path", "size"))
        
        self.btn_scan_orphans = ctk.CTkButton(self.frame_orphans, text="Scan Now", command=self.start_orphan_scan)
        self.btn_scan_orphans.pack(pady=10)
        self.btn_del_orphans = ctk.CTkButton(self.frame_orphans, text="Delete Selected", fg_color="#C0392B", command=self.delete_orphans)
        self.btn_del_orphans.pack(pady=10)

        # 3. Startup Page
        self.frame_startup = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        
        self.list_cnt_startup = ctk.CTkFrame(self.frame_startup)
        self.list_cnt_startup.pack(fill="both", expand=True, padx=20, pady=10)
        self.tree_startup = self._create_treeview(self.list_cnt_startup, ("name", "type", "location"))
        
        self.btn_ref_startup = ctk.CTkButton(self.frame_startup, text="Refresh", command=self.start_startup_scan)
        self.btn_ref_startup.pack(pady=(10, 5))
        
        self.btn_disable_startup = ctk.CTkButton(self.frame_startup, text="Disable / Stop Selected", fg_color="#F39C12", command=self.disable_startup)
        self.btn_disable_startup.pack(pady=5)

        self.btn_del_startup = ctk.CTkButton(self.frame_startup, text="Permanently Delete", fg_color="#C0392B", command=self.delete_startup)
        self.btn_del_startup.pack(pady=10)

        # Progress bar overlay (global)
        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        
        self.status_label = ctk.CTkLabel(self, text="")
    
    def _create_treeview(self, parent, cols):
        import tkinter.ttk as ttk
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#2b2b2b", fieldbackground="#2b2b2b", foreground="white", borderwidth=0)
        style.configure("Treeview.Heading", background="#333333", foreground="white", relief="flat")
        style.map("Treeview", background=[('selected', '#1f538d')])
        
        tree = ttk.Treeview(parent, columns=cols, show="headings", selectmode="extended")
        for c in cols:
            tree.heading(c, text=c.title())
            if c == "size":
                tree.column(c, width=100, anchor="e")
            elif c == "type":
                tree.column(c, width=150)
            else:
                tree.column(c, width=200)
        
        sb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tree

    def select_frame(self, name):
        # hide all (use grid_forget because we used grid)
        for f in [self.frame_uninstall, self.frame_orphans, self.frame_startup]:
            f.grid_forget()
        
        # Highlight button
        self.btn_uninstall.configure(fg_color=("gray75", "gray25") if name == "uninstall" else "transparent")
        self.btn_orphans.configure(fg_color=("gray75", "gray25") if name == "orphans" else "transparent")
        self.btn_startup.configure(fg_color=("gray75", "gray25") if name == "startup" else "transparent")

        if name == "uninstall":
            self.frame_uninstall.grid(row=0, column=1, sticky="nsew")
        elif name == "orphans":
            self.frame_orphans.grid(row=0, column=1, sticky="nsew")
        elif name == "startup":
            self.frame_startup.grid(row=0, column=1, sticky="nsew")
            self.start_startup_scan() # Threaded

    def on_drop(self, event):
        files = self.tk.splitlist(event.data)
        for f in files:
            if f.endswith(".app"):
                self.select_frame("uninstall")
                base = os.path.basename(f)
                self.search_entry.delete(0, "end")
                self.search_entry.insert(0, base)
                self.on_search(None)
                break

    # --- LOGIC INTEGRATION ---
    
    def start_full_scan(self):
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10)
        self.status_label.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.progress_bar.set(0)
        
        t = threading.Thread(target=self._scan_thread)
        t.start()
        
    def _scan_thread(self):
        try:
            def cb(cur, tot, msg):
                self.after(0, lambda: self._update_status(cur, tot, msg))
                
            apps = self.engine.get_installed_apps(cb)
            self.after(0, lambda: self._finish_scan(apps))
        except Exception as e:
            print(f"Scan Thread Error: {e}")
            self.after(0, lambda: messagebox.showerror("Error", f"Scan failed: {e}"))

    def _update_status(self, cur, tot, msg):
        pct = cur / tot if tot else 0
        self.progress_bar.set(pct)
        self.status_label.configure(text=msg)
        
    def _finish_scan(self, apps):
        self.all_apps = apps
        self.btn_refresh.configure(text=f"Refresh ({len(apps)})")
        self.on_search(None) # populate
        self.progress_bar.grid_forget()
        self.status_label.configure(text="Ready")

    def on_search(self, event):
        query = self.search_entry.get().lower()
        self.tree_apps.delete(*self.tree_apps.get_children())
        for app in self.all_apps:
            if not query or query in app["name"].lower():
                self.tree_apps.insert("", "end", values=(app["name"], app.get("bundle_id"), app["size_str"]), tags=(app["path"],))

    # --- UNINSTALL / RESET ---
    def confirm_uninstall(self):
        sel = self.tree_apps.selection()
        if not sel: return
        
        targets = []
        for item in sel:
            vals = self.tree_apps.item(item)['values']
            app = next((a for a in self.all_apps if a["name"] == vals[0]), None)
            if app:
                leftovers = self.engine.find_leftovers(app)
                targets.append({"app": app, "leftovers": leftovers})
                
        if not targets: return
        
        msg = "Deleting:\n"
        for t in targets:
            msg += f"- {t['app']['name']} (+ {len(t['leftovers'])} files)\n"
            
        if messagebox.askyesno("Confirm Delete", msg):
            for t in targets:
                self.engine.move_to_trash(t['app']['path'])
                for l in t['leftovers']:
                    self.engine.move_to_trash(l)
            self.start_full_scan()

    def confirm_reset(self):
        sel = self.tree_apps.selection()
        if not sel: return
        
        targets = []
        for item in sel:
            vals = self.tree_apps.item(item)['values']
            app = next((a for a in self.all_apps if a["name"] == vals[0]), None)
            if app: targets.append(app)
            
        if not targets: return
        
        if messagebox.askyesno("Confirm Reset", "This will delete preferences and cache but KEEP the app.\nContinue?"):
            count = 0
            for app in targets:
                 count += self.engine.reset_app(app)
            messagebox.showinfo("Done", f"Resetted {len(targets)} apps.\nMoved {count} files to Trash.")

    # --- ORPHANS ---
    def start_orphan_scan(self):
        self.status_label.configure(text="Scanning orphans...")
        
        def run():
            installed_ids = [a.get("bundle_id") for a in self.all_apps if a.get("bundle_id")]
            orphans = self.engine.scan_orphans(installed_ids)
            self.after(0, lambda: self._show_orphans(orphans))
            
        threading.Thread(target=run).start()
        
    def _show_orphans(self, orphans):
        self.orphans = orphans
        self.tree_orphans.delete(*self.tree_orphans.get_children())
        for o in orphans:
            self.tree_orphans.insert("", "end", values=(o["name"], o["path"], o["size_str"]))
        self.status_label.configure(text=f"Found {len(orphans)} orphans.")

    def delete_orphans(self):
        sel = self.tree_orphans.selection()
        if not sel: return
        
        if messagebox.askyesno("Delete Orphans", f"Delete {len(sel)} items?"):
            for item in sel:
                vals = self.tree_orphans.item(item)['values']
                path = vals[1]
                self.engine.move_to_trash(path)
            self.start_orphan_scan()

    # --- STARTUP ---
    def start_startup_scan(self):
        self.status_label.configure(text="Listing startup items...")
        self.tree_startup.delete(*self.tree_startup.get_children())
        threading.Thread(target=self._load_startup_thread).start()

    def _load_startup_thread(self):
        try:
            items = self.engine.get_startup_items()
            self.after(0, lambda: self._show_startup_items(items))
        except Exception as e:
            print(f"Startup Thread Error: {e}")
            self.after(0, lambda: messagebox.showerror("Error", f"Startup scan failed: {e}"))

    def _show_startup_items(self, items):
        self.startup_items_data = items 
        self.tree_startup.delete(*self.tree_startup.get_children())
        for i in items:
            self.tree_startup.insert("", "end", values=(i["name"], i["type"], i["location"]))
        self.status_label.configure(text=f"Found {len(items)} startup items.")

    def delete_startup(self):
        sel = self.tree_startup.selection()
        if not sel: return
        if messagebox.askyesno("Delete Startup Item", f"Permantently DELETE {len(sel)} items?\n(Files will be moved to Trash)"):
            for item in sel:
                vals = self.tree_startup.item(item)['values']
                name = vals[0]
                type_ = vals[1]
                path = vals[2]
                
                actual_path = None
                if type_ == "Launch Agent":
                    actual_path = os.path.join(path, name)
                
                item_dict = {"name": name, "type": type_, "path": actual_path}
                self.engine.remove_startup_item(item_dict)
                
            self.start_startup_scan()

    def disable_startup(self):
        sel = self.tree_startup.selection()
        if not sel: return
        
        if messagebox.askyesno("Disable Startup Item", f"Disable/Stop {len(sel)} items?\n(Files will be kept, but won't start automatically)"):
            for item in sel:
                vals = self.tree_startup.item(item)['values']
                name = vals[0]
                type_ = vals[1]
                path = vals[2]
                
                actual_path = None
                if type_ == "Launch Agent":
                    actual_path = os.path.join(path, name)
                
                item_dict = {"name": name, "type": type_, "path": actual_path}
                self.engine.disable_startup_item(item_dict)
                
            self.start_startup_scan()
            messagebox.showinfo("Done", "Selected items have been unloaded/disabled.")

if __name__ == "__main__":
    if not HAS_MODERN_UI:
        print("ERROR: Please install customtkinter and tkinterdnd2")
    else:
        app = ModernAppRemover()
        app.mainloop()
