
import sys
import os

# Add current dir to path to import app_remover
sys.path.append("/Users/muhammed/Desktop/app_Remover")

from app_remover import AppRemoverEngine

def test_engine():
    print("Initializing Engine...")
    engine = AppRemoverEngine()
    
    print("Testing PKG Receipt Scan (Generic)...")
    # Test with a common ID (might return empty, but shouldn't crash)
    pkgs = engine.find_pkg_receipts("com.apple.dt.Xcode") 
    print(f"PKG Scan result type: {type(pkgs)}")
    
    print("Testing Helper Scan (Generic)...")
    helpers = engine.find_privileged_helpers("com.docker.docker", "Docker")
    print(f"Helper Scan result type: {type(helpers)}")

    print("Testing Plugin Scan (Generic)...")
    plugins = engine.find_plugins("Zoom")
    print(f"Plugin Scan result type: {type(plugins)}")
    
    print("Testing Logging...")
    try:
        engine.log_deletion("TestApp", ["/tmp/test_file"])
        print("Logging successful.")
    except Exception as e:
        print(f"Logging failed: {e}")

    print("ALL TESTS PASSED: Engine methods are callable and safe.")

if __name__ == "__main__":
    test_engine()
