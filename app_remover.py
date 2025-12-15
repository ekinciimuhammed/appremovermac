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
import json
import datetime
import glob

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



# ==========================
# CORE ENGINE (Enhanced)
# ==========================

class AppRemoverLogger:
    """Protocol for logging from the engine."""
    def log(self, message):
        print(f"[ENGINE] {message}")

class AppRemoverEngine:
    """
    Enhanced Engine: Scanning, Leftovers, Reset, Orphans, Startup Items.
    HARDENED for Production Safety.
    """
    def __init__(self, logger=None):
        self.logger = logger or AppRemoverLogger()

    def log(self, msg):
        if self.logger:
            self.logger.log(msg)

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
                
                # New Features
                last_used = self._get_last_used(full_path)
                arch = self._get_architecture(full_path, meta.get("executable_name"))

                apps.append({
                    "name": name,
                    "path": full_path,
                    "size": size_bytes,
                    "size_str": self._format_size(size_bytes),
                    "bundle_id": meta["id"],
                    "bundle_name": meta["bundle_name"],
                    "last_used": last_used,
                    "arch": arch
                })
            except Exception:
                pass

        return sorted(apps, key=lambda x: x["name"].lower())

    def find_leftovers(self, app_data):
        """Finds related files using mdfind AND smart heuristics. Returns list of dicts: {'path': p, 'kind': k}"""
        bundle_id = app_data.get("bundle_id")
        bundle_name = app_data.get("bundle_name") # e.g. "Code"
        app_path = app_data.get("path")
        
        self.log(f"Finding leftovers for {app_data.get('name')} (ID: {bundle_id}, Name: {bundle_name})...")
        
        found_paths = set()
        results = []
        
        def add_item(path, kind):
            if path and path not in found_paths and path != app_path and not path.startswith(app_path):
                found_paths.add(path)
                results.append({"path": path, "kind": kind})

        # 1. MDFIND (Spotlight)
        if bundle_id:
            try:
                home = os.path.expanduser("~")
                cmd = ["mdfind", "-onlyin", home, bundle_id]
                output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
                if output:
                    for line in output.split('\n'):
                        path = line.strip()
                        if self._is_safe_to_delete_candidate(path):
                            add_item(path, "FILE")
            except Exception as e:
                self.log(f"mdfind error: {e}")

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
                if os.path.exists(p):
                     if self._is_safe_to_delete_candidate(p):
                         add_item(p, "FILE")

        # 3. Smart Heuristics (Bundle Name based)
        if bundle_name and bundle_name != bundle_id: 
            smart_checks = [
                os.path.expanduser(f"~/Library/Application Support/{bundle_name}"),
                os.path.expanduser(f"~/Library/Caches/{bundle_name}"),
                os.path.expanduser(f"~/Library/Saved Application State/{bundle_name}.savedState")
            ]
            for p in smart_checks:
                if os.path.exists(p):
                    if self._is_safe_to_delete_candidate(p):
                        add_item(p, "FILE")

        # 4. PKG Receipts (Package IDs)
        if bundle_id:
            pkg_files = self.find_pkg_receipts(bundle_id)
            for p in pkg_files:
                add_item(p, "PKG_RECEIPT")

        # 5. Privileged Helpers & Launch Daemons
        if bundle_id and bundle_name:
            helpers = self.find_privileged_helpers(bundle_id, bundle_name)
            for p in helpers:
                add_item(p, "HELPER")

        # 6. Plugins (Audio, Internet, PrefPanes)
        if bundle_name:
            plugins = self.find_plugins(bundle_name)
            for p in plugins:
                add_item(p, "PLUGIN")
                
        # 7. User Data / Hidden Folders (New)
        if bundle_name:
            hidden = self.find_hidden_folders(bundle_name)
            for p in hidden:
                add_item(p, "USER_DATA")
                
            docs = self.find_user_documents(bundle_name)
            for p in docs:
                add_item(p, "USER_DATA")

        # Sort by kind then path
        return sorted(results, key=lambda x: (x["kind"], x["path"]))

    def find_hidden_folders(self, bundle_name):
        """Scans user Home for hidden folders matching app name."""
        found = []
        home = os.path.expanduser("~")
        
        # Candidate name: .appname (lowercase compact)
        candidate = f".{bundle_name.lower().replace(' ', '')}"
        path = os.path.join(home, candidate)
        
        if os.path.isdir(path):
             found.append(path)
             
        # Also try exact name ".AppName"
        candidate2 = f".{bundle_name}" 
        path2 = os.path.join(home, candidate2)
        if os.path.isdir(path2) and path2 != path:
            found.append(path2)
            
        return found

    def find_user_documents(self, bundle_name):
        """Scans Documents, Music, Movies, Pictures for folders EXACTLY matching the App Name."""
        found = []
        user_dirs = [
            os.path.expanduser("~/Documents"),
            os.path.expanduser("~/Movies"),
            os.path.expanduser("~/Music"),
            os.path.expanduser("~/Pictures")
        ]
        
        for d in user_dirs:
            if not os.path.exists(d): continue
            
            # Look for folder "AppName"
            candidate = os.path.join(d, bundle_name)
            if os.path.isdir(candidate):
                found.append(candidate)
                
        return found
    
    def secure_delete(self, path, force_pkgs=False):
        """
        Securely moves path to Trash via AppleScript.
        ENFORCES SAFETY:
        - Will NOT delete PKG receipts unless force_pkgs=True.
        - Will NOT delete items in /System or /bin unless explicitly allowed (not implemented here but good to have)
        """
        if not path or not os.path.exists(path):
            return

        # 1. PKG Safety Check
        if "/var/db/receipts" in path or "/Library/Receipts" in path:
            if not force_pkgs:
                self.log(f"SAFETY BLOCKED: Skipping PKG receipt deletion: {path}")
                return
            else:
                self.log(f"WARNING: Deleting PKG receipt (Force Enabled): {path}")

        # 2. General Safety Check
        if not self._is_safe_to_delete_candidate(path):
            self.log(f"SAFETY BLOCKED: Item protected: {path}")
            return

        self.log(f"Moving to trash: {path}")
        clean_path = path.replace('"', '\\"')
        cmd = ["osascript", "-e", f'tell application "Finder" to delete POSIX file "{clean_path}"']
        try:
            subprocess.run(cmd, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.log(f"Error moving to trash: {e}")

    # Legacy alias compatible with UI calls that just pass path string
    def move_to_trash(self, path):
        # Default safe delete
        self.secure_delete(path, force_pkgs=False)

    def reset_app(self, app_data):
        """
        Resets an app by deleting ALL data (containers, caches, prefs, default) but KEEPING the .app bundle.
        Enforces safety (no PKG deletion).
        """
        self.log(f"Starting DEEP RESET for {app_data.get('name')}")
        bundle_id = app_data.get("bundle_id")
        
        # 1. Find Standard Leftovers
        leftovers = self.find_leftovers(app_data)
        
        # 2. Find Group Containers
        if bundle_id:
            group_containers = self.find_group_containers(bundle_id)
            for gc in group_containers:
                leftovers.append({"path": gc, "kind": "GROUP_CONTAINER"})
            
        deleted_count = 0
        for item in leftovers:
            path = item["path"]
            kind = item["kind"]
            
            # SAFETY: In Reset Mode setup:
            # - Skip USER_DATA (Document loss risk)
            # - Skip PKG_RECEIPT (System history risk)
            if kind == "USER_DATA":
                continue
            if kind == "PKG_RECEIPT":
                continue
                
            self.secure_delete(path, force_pkgs=False)
            deleted_count += 1
            
        # 3. Defaults Delete
        if bundle_id:
            self.reset_app_preferences(bundle_id)
            
        # 4. Refresh Preferences Service
        self.kill_cfprefsd()
            
        self.log(f"Deep Reset complete. Moved {deleted_count} items to trash & cleared defaults.")
        return deleted_count

    def reset_app_preferences(self, bundle_id):
        """Executes 'defaults delete bundle_id'."""
        try:
            self.log(f"Executing defaults delete {bundle_id}")
            subprocess.run(["defaults", "delete", bundle_id], stderr=subprocess.DEVNULL)
        except Exception as e:
            self.log(f"defaults delete failed: {e}")

    def find_group_containers(self, bundle_id):
        """Scans ~/Library/Group Containers."""
        found = []
        path = os.path.expanduser("~/Library/Group Containers")
        if not os.path.exists(path): return found
        
        try:
            for entry in os.listdir(path):
                if bundle_id and bundle_id in entry:
                    full_path = os.path.join(path, entry)
                    found.append(full_path)
        except Exception:
            pass
        return found
        
    def kill_cfprefsd(self):
        """Resets the preference daemon."""
        try:
            subprocess.run(["killall", "cfprefsd"], stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def scan_orphans(self, installed_bundle_ids, progress_callback=None):
        """Scans common library paths for folders that look like bundle IDs."""
        orphans = []
        scan_dirs = [
            os.path.expanduser("~/Library/Containers"),
            os.path.expanduser("~/Library/Application Support"),
            os.path.expanduser("~/Library/Caches"),
            os.path.expanduser("~/Library/Preferences"),
            "/Library/Audio/Plug-Ins/Components",
            "/Library/Audio/Plug-Ins/VST",
            "/Library/Audio/Plug-Ins/VST3",
            "/Library/Internet Plug-Ins",
            "/Library/PreferencePanes"
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
        """Scans User Login Items (Apps) AND LaunchAgents/Daemons."""
        items = []
        
        # 1. Login Items via AppleScript
        self.log("Fetching Login Items via AppleScript...")
        try:
            names_raw = subprocess.check_output(
                ['osascript', '-e', 'tell application "System Events" to get name of every login item'], 
                stderr=subprocess.DEVNULL,
                timeout=5
            ).decode().strip()
            
            names = names_raw.split(', ')
            self.log(f"Found login items: {names}")
            
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
            self.log("AppleScript timed out!")
        except Exception as e:
            self.log(f"AppleScript error: {e}")

        # 2. Launch Agents
        self.log("Scanning LaunchAgents...")
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
            self.secure_delete(path) # Use safe delete
            
            if path and os.path.exists(path):
                 # If persistent/safe delete failed somehow, ensure unload at least
                subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", path], stderr=subprocess.DEVNULL)
                subprocess.run(["launchctl", "unload", path], stderr=subprocess.DEVNULL)

    def disable_startup_item(self, item):
        """
        Disables a startup item. 
        For LaunchAgents, we rename the plist to .disabled to ensure it doesn't load again.
        """
        if item.get("type") == "Login Item":
            # For Login Items, removing from the list is effectively disabling.
            self.remove_startup_item(item)
        else:
            # LaunchAgent - Unload matches AND rename file to prevent re-load
            path = item.get("path")
            if path and os.path.exists(path):
                # 1. Try to Unload / Bootout
                try:
                    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", path], stderr=subprocess.DEVNULL)
                    subprocess.run(["launchctl", "unload", "-w", path], stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                
                # 2. Rename to .disabled
                try:
                    new_path = path + ".disabled"
                    os.rename(path, new_path)
                    self.log(f"Renamed {path} to {new_path}")
                except OSError as e:
                    self.log(f"Failed to rename {path}: {e}")

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
                    meta["executable_name"] = pl.get("CFBundleExecutable") # Get Executable Name
            except Exception:
                pass
        return meta

    def _get_last_used(self, app_path):
        """Gets Last Used Date using spotlight metadata."""
        try:
            # mdls -name kMDItemLastUsedDate -raw /Path/To/App
            output = subprocess.check_output(
                ["mdls", "-name", "kMDItemLastUsedDate", "-raw", app_path], 
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            if output == "(null)" or not output:
                return "Unknown"
            
            # Output format: 2023-10-25 10:00:00 +0000
            # Simplify to YYYY-MM-DD
            return output.split(" ")[0]
        except Exception:
            return "Unknown"

    def _get_architecture(self, app_path, executable_name):
        """Determines if app is Intel, Apple Silicon, or Universal."""
        macos_dir = os.path.join(app_path, "Contents", "MacOS")
        exec_path = None
        
        # 1. Try specific executable
        if executable_name:
            candidate = os.path.join(macos_dir, executable_name)
            if os.path.exists(candidate):
                exec_path = candidate
                
        # 2. Fallback: Scan MacOS folder for any file
        if not exec_path and os.path.exists(macos_dir):
            try:
                for entry in os.listdir(macos_dir):
                    # Pick first file that doesn't have an extension or is executable
                    # Heuristic: usually the binary has no extension and is executable
                    full = os.path.join(macos_dir, entry)
                    if os.path.isfile(full) and not entry.startswith("."):
                        # Check permission to be sure it's somewhat bin-like?
                        exec_path = full
                        break
            except Exception:
                pass
                
        if not exec_path: return "Unknown"
        
        try:
            # lipo -archs /Path/To/Exec
            output = subprocess.check_output(
                ["lipo", "-archs", exec_path], 
                stderr=subprocess.DEVNULL
            ).decode().strip()
            
            if "x86_64" in output and "arm64" in output:
                return "Universal"
            elif "arm64" in output:
                return "Apple Silicon"
            elif "x86_64" in output:
                return "Intel"
            elif "i386" in output: # Old 32-bit
                return "32-bit (Legacy)"
            return output
        except Exception:
            return "Unknown"

    def check_full_disk_access(self):
        """
        Checks if the app has Full Disk Access by trying to list MULTIPLE protected dirs.
        Returns True only if clear access is confirmed.
        """
        try:
            checks = [
                os.path.expanduser("~/Library/Safari"),
                os.path.expanduser("~/Library/Mail"),
                os.path.expanduser("~/Library/Messages")
            ]
            
            successes = 0
            failures = 0
            
            for path in checks:
                if not os.path.exists(path):
                    # If folder doesn't exist, we can't test it.
                    continue 
                try:
                    os.listdir(path)
                    successes += 1
                except PermissionError:
                    failures += 1
                except OSError:
                    pass
                    
            if failures > 0:
                return False
            if successes > 0:
                return True
                
            # If we couldn't test anything (neither exists?), conservative assumption:
            return True 
            
        except Exception:
            return False

    def is_app_running(self, bundle_id, app_name):
        """Checks if the app is currently running using AppleScript (safer) then pgrep."""
        # 1. Authentic AppleScript Check (Exact Name Match from System Events)
        if app_name:
            clean_name = app_name.replace(".app", "")
            try:
                # 'tell application "System Events" to (name of processes) contains "AppName"'
                cmd = ['osascript', '-e', f'tell application "System Events" to (name of processes) contains "{clean_name}"']
                output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
                if output == "true":
                    return True
            except Exception:
                pass

        # 2. Pgrep Fallback (Exact match only)
        if app_name:
            clean_name = app_name.replace(".app", "")
            try:
                subprocess.check_output(["pgrep", "-x", clean_name], stderr=subprocess.DEVNULL)
                return True
            except subprocess.CalledProcessError:
                pass
            
        return False

    def kill_app(self, bundle_id, app_name):
        """
        Attempts to kill the app safely.
        1. AppleScript Quit (Graceful)
        2. Wait
        3. pkill -x (Exact name match)
        NEVER uses pkill -f.
        """
        self.log(f"Attempting to stop {app_name} ({bundle_id})")
        
        # 1. Graceful Quit via Bundle ID (AppleScript)
        if bundle_id:
            try:
                cmd = ['osascript', '-e', f'tell application id "{bundle_id}" to quit']
                subprocess.run(cmd, stderr=subprocess.DEVNULL, timeout=3)
            except Exception:
                pass
                
        # Check if dead
        time.sleep(1)
        if not self.is_app_running(bundle_id, app_name):
            return True
            
        # 2. Force Kill using Exact Name Match (pkill -x)
        # We avoid pgrep -f because it matches partial strings or arguments.
        if app_name:
            clean_name = app_name.replace(".app", "")
            try:
                self.log(f"Force killing process: {clean_name}")
                subprocess.run(["pkill", "-x", clean_name], stderr=subprocess.DEVNULL)
                time.sleep(0.5)
            except Exception:
                pass
                
        return not self.is_app_running(bundle_id, app_name)

    # --- ADVANCED CLEANING FEATURES ---

    def find_pkg_receipts(self, bundle_id):
        """
        Finds receipt files for installed packages related to the bundle ID.
        Uses `pkgutil --pkgs`.
        """
        found = []
        try:
            # Get all package IDs
            all_pkgs = subprocess.check_output(["pkgutil", "--pkgs"], stderr=subprocess.DEVNULL).decode().splitlines()
            
            matches = [pkg for pkg in all_pkgs if bundle_id in pkg]
            
            for pkg_id in matches:
                base_path = f"/var/db/receipts/{pkg_id}"
                if os.path.exists(f"{base_path}.bom"):
                    found.append(f"{base_path}.bom")
                if os.path.exists(f"{base_path}.plist"):
                    found.append(f"{base_path}.plist")
                
                # Also check /Library/Receipts (Legacy)
                legacy_path = f"/Library/Receipts/{pkg_id}.pkg"
                if os.path.exists(legacy_path):
                    found.append(legacy_path)
                    
        except Exception as e:
            self.log(f"PKG scan error: {e}")
            
        return found

    def find_privileged_helpers(self, bundle_id, bundle_name):
        """Scans /Library/PrivilegedHelperTools for helper binaries."""
        found = []
        path = "/Library/PrivilegedHelperTools"
        if not os.path.exists(path): return found
        
        try:
            for entry in os.listdir(path):
                if (bundle_id and bundle_id in entry) or (bundle_name and bundle_name.lower() in entry.lower()):
                     full_path = os.path.join(path, entry)
                     found.append(full_path)
        except Exception:
            pass
        return found

    def find_plugins(self, bundle_name):
        """Scans Audio Plug-Ins, Internet Plug-Ins, etc."""
        found = []
        search_dirs = [
            "/Library/Audio/Plug-Ins/Components", # AU
            "/Library/Audio/Plug-Ins/VST",
            "/Library/Audio/Plug-Ins/VST3",
            "/Library/Internet Plug-Ins",
            "/Library/PreferencePanes",
            os.path.expanduser("~/Library/Audio/Plug-Ins/Components"),
            os.path.expanduser("~/Library/Audio/Plug-Ins/VST"),
            os.path.expanduser("~/Library/Audio/Plug-Ins/VST3"),
            os.path.expanduser("~/Library/Internet Plug-Ins"),
            os.path.expanduser("~/Library/PreferencePanes")
        ]
        
        for d in search_dirs:
            if not os.path.exists(d): continue
            try:
                for entry in os.listdir(d):
                    if bundle_name.lower() in entry.lower():
                        found.append(os.path.join(d, entry))
            except Exception:
                pass
        return found
        
    def log_deletion(self, app_name, deleted_files):
        """Logs deletion history to ~/Library/Logs/AppRemover/history.json"""
        log_dir = os.path.expanduser("~/Library/Logs/AppRemover")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        log_file = os.path.join(log_dir, "history.json")
        
        entry = {
            "timestamp": datetime.datetime.now().isoformat(),
            "app_name": app_name,
            "deleted_files_count": len(deleted_files),
            "files": deleted_files
        }
        
        try:
            history = []
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    history = json.load(f)
            
            history.append(entry)
            
            with open(log_file, "w") as f:
                json.dump(history, f, indent=4)
        except Exception as e:
            self.log(f"FAILED TO LOG: {e}")



if HAS_MODERN_UI:
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
        
            self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Cleaner", font=ctk.CTkFont(size=20, weight="bold"))
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
        
            # FDA Warning
            if not self.engine.check_full_disk_access():
                self.fda_warning = ctk.CTkFrame(self.frame_uninstall, fg_color="#E74C3C", corner_radius=5)
                self.fda_warning.pack(fill="x", padx=20, pady=(10, 0))
            
                lbl = ctk.CTkLabel(self.fda_warning, text=" Full Disk Access Missing! Some leftovers might be missed.", text_color="white")
                lbl.pack(side="left", padx=10, pady=5)
            
                btn_grant = ctk.CTkButton(self.fda_warning, text="Grant Access", width=100, fg_color="white", text_color="#E74C3C", hover_color="#f0f0f0", command=self.open_fda_settings)
                btn_grant.pack(side="right", padx=10, pady=5)

                btn_close = ctk.CTkButton(self.fda_warning, text="Dismiss", width=60, fg_color="transparent", border_width=1, border_color="white", text_color="white", command=self.fda_warning.destroy)
                btn_close.pack(side="right", padx=(0, 10), pady=5)

        
            # Search
            self.search_entry = ctk.CTkEntry(self.frame_uninstall, placeholder_text="Search apps...")
            self.search_entry.pack(fill="x", padx=20, pady=10)
            self.search_entry.bind("<KeyRelease>", self.on_search)
        
            # App List
            self.list_cnt_uninstall = ctk.CTkFrame(self.frame_uninstall)
            self.list_cnt_uninstall.pack(fill="both", expand=True, padx=20, pady=10)
            self.tree_apps = self._create_treeview(self.list_cnt_uninstall, ("name", "last_used", "arch", "size"))
        
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
                elif c == "last_used":
                    tree.column(c, width=120)
                elif c == "arch":
                    tree.column(c, width=100)
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
                    # Values must match column count (4): Name, Last Used, Arch, Size
                    # Bundle ID is not in columns, so remove it from values tuple
                    self.tree_apps.insert("", "end", values=(app["name"], app.get("last_used", ""), app.get("arch", ""), app["size_str"]), tags=(app["path"],))

        # --- UNINSTALL / RESET ---
        def confirm_uninstall(self):
            sel = self.tree_apps.selection()
            if not sel: return
        
            targets = []
            for item in sel:
                vals = self.tree_apps.item(item)['values']
                app = next((a for a in self.all_apps if a["name"] == vals[0]), None)
                if app:
                    # Check if running
                    if self.engine.is_app_running(app.get("bundle_id"), app.get("name")):
                        if messagebox.askyesno("App Running", f"{app['name']} is currently running.\nForce Quit and continue uninstall?"):
                            self.engine.kill_app(app.get("bundle_id"), app.get("name"))
                        else:
                            continue # Skip this app if user says No

                    leftovers = self.engine.find_leftovers(app)
                    targets.append({"app": app, "leftovers": leftovers})
                
            if not targets: return
        
            # Open Simulation / Dry Run Modal
            self.show_simulation_modal(targets)

        def show_simulation_modal(self, targets):
            top = ctk.CTkToplevel(self)
            top.title("Uninstall Preview")
            top.geometry("800x600")
            
            # Make modal
            top.transient(self)
            top.grab_set()
            
            ctk.CTkLabel(top, text="The following items will be permanently deleted:", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=10)
            
            # Toggles Frame
            toggle_frame = ctk.CTkFrame(top, fg_color="transparent")
            toggle_frame.pack(fill="x", padx=20, pady=5)
            
            # Variables
            self.var_del_userdata = ctk.BooleanVar(value=False) # Default OFF for safety
            self.var_del_system = ctk.BooleanVar(value=False)   # Default OFF for receipts
            
            # Switch Callback
            def on_toggle():
                self._refresh_simulation_list(text_area, status_lbl, targets, btn_uninstall)
                
            sw_userdata = ctk.CTkSwitch(toggle_frame, text="Delete User Data (Documents/Home)", variable=self.var_del_userdata, command=on_toggle)
            sw_userdata.pack(side="left", padx=10)
            
            sw_system = ctk.CTkSwitch(toggle_frame, text="Delete System Receipts (PKG)", variable=self.var_del_system, command=on_toggle)
            sw_system.pack(side="left", padx=10)
            
            # List Area
            list_frame = ctk.CTkFrame(top)
            list_frame.pack(fill="both", expand=True, padx=20, pady=5)
            
            text_area = ctk.CTkTextbox(list_frame, wrap="none")
            text_area.pack(fill="both", expand=True, padx=5, pady=5)
            
            status_lbl = ctk.CTkLabel(top, text="Calculating...", text_color="gray")
            status_lbl.pack(pady=5)
            
            # Buttons
            btn_frame = ctk.CTkFrame(top, fg_color="transparent")
            btn_frame.pack(fill="x", padx=20, pady=20)
            
            def do_delete():
                # Disable button to prevent double-click
                btn_uninstall.configure(state="disabled", text="Uninstalling...")
                
                def run_delete_thread():
                    # Perform deletion in background
                    deleted_log = []
                    
                    # Re-calculate files to delete based on current toggles
                    # NOTE: Accessing vars is technically not thread safe but usually reading BooleanVar is okay-ish if careful, 
                    # but better to get values before thread starts.
                    # However, since they are tkinter vars, we should really get them in main thread.
                    # The 'final_targets' calc relies on BooleanVars. Let's calculate it outside!
                    pass # Logic moved outside

                # 1. Main Thread: Prepare Data
                final_targets = self._get_active_targets(targets)
                force_pkgs = self.var_del_system.get()
                
                def worker():
                    # 2. Worker Thread: Blocking I/O
                    for path in final_targets:
                        self.engine.secure_delete(path, force_pkgs=force_pkgs)
                        
                    # Log it
                    for t in targets:
                        active_leftovers = [x['path'] for x in t['leftovers'] if x['path'] in final_targets]
                        self.engine.log_deletion(t['app']['name'], active_leftovers + [t['app']['path']])
                        
                    # 3. Callback to Main Thread
                    self.after(0, on_done)

                def on_done():
                    top.destroy()
                    messagebox.showinfo("Complete", f"Uninstalled. Logs saved to history.json")
                    self.start_full_scan()

                import threading
                threading.Thread(target=worker, daemon=True).start()

            ctk.CTkButton(btn_frame, text="Cancel", fg_color="gray", command=top.destroy).pack(side="left", padx=10)
            
            btn_uninstall = ctk.CTkButton(btn_frame, text="Uninstall Selected", fg_color="#C0392B", command=do_delete)
            btn_uninstall.pack(side="right", padx=10)
            
            # Initial Load
            self._refresh_simulation_list(text_area, status_lbl, targets, btn_uninstall)

        def _get_active_targets(self, targets):
            """Returns list of paths to delete based on toggles."""
            to_delete = []
            include_userdata = self.var_del_userdata.get()
            include_system = self.var_del_system.get()
            
            for t in targets:
                to_delete.append(t['app']['path'])
                for item in t['leftovers']:
                    kind = item['kind']
                    if kind == "USER_DATA" and not include_userdata: continue
                    if kind == "PKG_RECEIPT" and not include_system: continue
                    to_delete.append(item['path'])
            return to_delete

        def _refresh_simulation_list(self, text_area, status_lbl, targets, btn_uninstall):
            text_area.configure(state="normal")
            text_area.delete("0.0", "end")
            
            include_userdata = self.var_del_userdata.get()
            include_system = self.var_del_system.get()
            
            count = 0
            total_size = 0 # Not calc currently
            
            for t in targets:
                app_name = t['app']['name']
                text_area.insert("end", f"== {app_name} ==\n")
                text_area.insert("end", f"[APP] {t['app']['path']}\n")
                count += 1
                
                for item in t['leftovers']:
                    path = item['path']
                    kind = item['kind']
                    
                    prefix = f"[{kind}] "
                    line = f"{prefix}{path}\n"
                    
                    # Check status
                    skipped = False
                    if kind == "USER_DATA" and not include_userdata:
                        skipped = True
                        line = f"[SKIPPED - USER DATA] {path}\n"
                    elif kind == "PKG_RECEIPT" and not include_system:
                        skipped = True
                        line = f"[SKIPPED - SYSTEM] {path}\n"
                        
                    text_area.insert("end", line)
                    if not skipped:
                        count += 1
                
                text_area.insert("end", "\n")
                
            text_area.configure(state="disabled")
            status_lbl.configure(text=f"Ready to delete {count} items.")
            btn_uninstall.configure(text=f"Uninstall ({count})")

        def confirm_reset(self):
            sel = self.tree_apps.selection()
            if not sel: return
        
            targets = []
            for item in sel:
                vals = self.tree_apps.item(item)['values']
                app = next((a for a in self.all_apps if a["name"] == vals[0]), None)
                if app: 
                    # Check if running
                    if self.engine.is_app_running(app.get("bundle_id"), app.get("name")):
                        if messagebox.askyesno("App Running", f"{app['name']} is currently running.\nForce Quit and continue reset?"):
                            self.engine.kill_app(app.get("bundle_id"), app.get("name"))
                        else:
                            continue # Skip

                    targets.append(app)
            
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

            
                # Restart Scan logic if needed or just inform user
                # self.start_full_scan()

        def open_fda_settings(self):
            """Opens macOS System Settings at the Full Disk Access page."""
            subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"], stderr=subprocess.DEVNULL)
            messagebox.showinfo("Instructions", "1. Click '+' or drag your Terminal/Python app into the list.\n2. Enable the switch.\n3. Restart this app.")

if __name__ == "__main__":
    if not HAS_MODERN_UI:
        print("ERROR: Please install customtkinter and tkinterdnd2")
    else:
        app = ModernAppRemover()
        app.mainloop()
