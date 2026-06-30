import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import save_config, load_config

# Simulate the exact flow from the concurrent test
cfg = load_config()
print("=== Config from load_config ===")
print("scan_interval:", cfg["scan_interval"])
srv_count = len(cfg.get("servers", []))
print("servers count:", srv_count)
for s in cfg.get("servers", []):
    name = s.get("name", "?")
    pwd_len = len(s.get("password", ""))
    print(f"  {name}: pass_len={pwd_len}")

# Modify and save
cfg["scan_interval"] = 55
try:
    ok = save_config(cfg)
    print(f"save_config result: {ok}")
except Exception as e:
    print(f"save_config ERROR: {type(e).__name__}: {e}")

# Reload
cfg2 = load_config()
print(f"After save, scan_interval: {cfg2['scan_interval']}")

# Restore
cfg2["scan_interval"] = 60
save_config(cfg2)
print("Restored to 60")
