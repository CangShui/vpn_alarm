"""Debug the HTTP save issue"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from config_manager import load_config

SERVER_URL = "http://127.0.0.1:5000"

# Test 1: GET config, modify, POST back
print("=== Test 1: GET -> modify -> POST ===")
resp = requests.get(f"{SERVER_URL}/api/config", timeout=10)
cfg = resp.json()
print(f"GET returned ok, keys: {list(cfg.keys())}")
print(f"servers: {len(cfg.get('servers',[]))}")
for s in cfg.get('servers', []):
    print(f"  {s.get('name','?')}: pass_len={len(s.get('password',''))}")

# Modify and save
cfg['scan_interval'] = 55
print(f"\nSending POST with scan_interval=55...")
resp2 = requests.post(f"{SERVER_URL}/api/config", json=cfg, timeout=10)
print(f"Response status: {resp2.status_code}")
print(f"Response body: {resp2.text}")

# Restore
cfg['scan_interval'] = 60
resp3 = requests.post(f"{SERVER_URL}/api/config", json=cfg, timeout=10)
print(f"\nRestore response: {resp3.text}")

# Test 2: Save with minimal changes
print("\n=== Test 2: Minimal change ===")
cfg2 = load_config()
cfg2['scan_interval'] = 45
resp4 = requests.post(f"{SERVER_URL}/api/config", json=cfg2, timeout=10)
print(f"Save 45s: {resp4.text}")

cfg2['scan_interval'] = 60
resp5 = requests.post(f"{SERVER_URL}/api/config", json=cfg2, timeout=10)
print(f"Restore 60s: {resp5.text}")

print("\n=== All HTTP tests done ===")
