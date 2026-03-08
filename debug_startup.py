from app_remover import AppRemoverEngine
import os
import subprocess

def test_startup():
    print("Initializing Engine...")
    engine = AppRemoverEngine()
    
    print("Scanning Startup Items...")
    items = engine.get_startup_items()
    
    print(f"Found {len(items)} items:")
    for i in items:
        print(f" - [{i.get('type')}] {i.get('name')} @ {i.get('path')}")

    print("\n--- Diagnostic Info ---")
    paths = [
        os.path.expanduser("~/Library/LaunchAgents"),
        "/Library/LaunchAgents",
        "/Library/LaunchDaemons"
    ]
    for p in paths:
        print(f"Path {p}: Exists={os.path.exists(p)}, Writable={os.access(p, os.W_OK)}, Readable={os.access(p, os.R_OK)}")
        if os.path.exists(p):
            try:
                print(f"  Contents: {os.listdir(p)[:5]}...") 
            except Exception as e:
                print(f"  Error reading: {e}")

    print("\nAttempting AppleScript raw call...")
    try:
        cmd = ['osascript', '-e', 'tell application "System Events" to get name of every login item']
        out = subprocess.check_output(cmd, stderr=subprocess.PIPE).decode().strip()
        print(f"AppleScript Output: {out}")
    except subprocess.CalledProcessError as e:
        print(f"AppleScript Failed: {e.stderr.decode()}")

if __name__ == "__main__":
    test_startup()
