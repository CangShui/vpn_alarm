"""Diagnose the exact error location in save_config"""
import sys, os, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import save_config, load_config, _normalize_config, _merge_server_passwords, CONFIG_PATH

# Get config exactly as the server receives it via HTTP
import requests
resp = requests.get("http://127.0.0.1:5000/api/config", timeout=10)
new_config = resp.json()
print("Config from API:", list(new_config.keys()))
print("servers:", len(new_config.get('servers',[])))
for s in new_config.get('servers',[]):
    name = s.get('name','?')
    pwd = s.get('password','')
    print(f"  {name}: pass_len={len(pwd)}, pass_type={type(pwd).__name__}")

# Now trace save_config step by step
print("\n=== Tracing save_config ===")
config = new_config

# Step 1: merge passwords
try:
    if config.get('servers'):
        print("Step 1: _merge_server_passwords...")
        config['servers'] = _merge_server_passwords(config['servers'])
        print("  OK")
except Exception as e:
    print(f"  FAIL: {traceback.format_exc()}")

# Step 2: normalize
try:
    print("Step 2: _normalize_config...")
    normalized = _normalize_config(config)
    print("  OK, keys:", list(normalized.keys()))
except Exception as e:
    print(f"  FAIL: {traceback.format_exc()}")

# Step 3: write
try:
    print("Step 3: open file for writing...")
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        print("  File opened")
        json.dump(normalized, f, ensure_ascii=False, indent=2)
        print("  json.dump OK")
    print("Step 3: OK")
except Exception as e:
    print(f"  FAIL: {traceback.format_exc()}")

# Step 4: verify
try:
    print("Step 4: verify by reloading...")
    cfg2 = load_config()
    print("  Reload OK, scan_interval:", cfg2.get('scan_interval'))
except Exception as e:
    print(f"  FAIL: {traceback.format_exc()}")

print("\n=== Trace complete ===")
