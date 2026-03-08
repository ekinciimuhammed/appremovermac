import os
import subprocess
import shutil
import customtkinter
import tkinterdnd2
from pathlib import Path

def build_app():
    print("🚀 Starting Build Process...")
    
    # Clean previous builds
    if os.path.exists("dist"): shutil.rmtree("dist")
    if os.path.exists("build"): shutil.rmtree("build")
    
    # Get Paths
    ctk_path = os.path.dirname(customtkinter.__file__)
    dnd_path = os.path.dirname(tkinterdnd2.__file__)
    
    # Define Name
    APP_NAME = "App Remover Pro"
    SCRIPT = "app_remover.py"
    
    # PyInstaller Command
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onedir",
        "--windowed", # No Terminal
        "--clean",
        f"--name={APP_NAME}",
        "--icon=AppIcon.icns", # Added Icon
        f"--add-data={ctk_path}:customtkinter",
        f"--add-data={dnd_path}:tkinterdnd2",
        "--collect-all=tkinterdnd2", # Extra safety for dnd binaries
        SCRIPT
    ]
    
    print(f"Running PyInstaller: {' '.join(cmd)}")
    subprocess.check_call(cmd)
    
    app_path = f"dist/{APP_NAME}.app"
    if not os.path.exists(app_path):
        print("❌ Build Failed: .app not found")
        return False
        
    print("✅ Standalone App Built!")
    return True

def create_dmg():
    APP_NAME = "App Remover Pro"
    APP_PATH = f"dist/{APP_NAME}.app"
    DMG_NAME = f"{APP_NAME}.dmg"
    DMG_ROOT = "dmg_root"
    
    print("📦 Creating DMG Installer...")
    
    if os.path.exists(DMG_ROOT): shutil.rmtree(DMG_ROOT)
    os.makedirs(DMG_ROOT)
    
    # Copy App
    print(f"Copying {APP_PATH} to {DMG_ROOT}...")
    subprocess.check_call(["cp", "-R", APP_PATH, DMG_ROOT])
    
    # Create /Applications Symlink
    print("Creating /Applications shortcut...")
    os.symlink("/Applications", f"{DMG_ROOT}/Applications")
    
    # Create DMG
    print("Generating .dmg file (this may take a moment)...")
    if os.path.exists(DMG_NAME): os.remove(DMG_NAME)
    
    cmd = [
        "hdiutil", "create",
        "-volname", APP_NAME,
        "-srcfolder", DMG_ROOT,
        "-ov",
        "-format", "UDZO",
        DMG_NAME
    ]
    subprocess.check_call(cmd)
    
    # Cleanup
    shutil.rmtree(DMG_ROOT)
    
    print(f"✅ DMG Created Successfully: {os.path.abspath(DMG_NAME)}")

if __name__ == "__main__":
    if build_app():
        create_dmg()
