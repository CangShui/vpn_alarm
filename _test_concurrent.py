"""Test concurrent save + scan for hang reproduction"""
import sys
import os
import json
import time
import threading
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SERVER_URL = "http://127.0.0.1:5000"

print("=" * 60)
print("  Concurrent save + scan stress test")
print("=" * 60)

# Check if server is running
try:
    resp = requests.get(f"{SERVER_URL}/api/config", timeout=3)
    print("Server is running")
except Exception as e:
    print(f"Server not reachable: {e}")
    print("Please start the server first: python app.py")
    sys.exit(1)

# Get current config
cfg = requests.get(f"{SERVER_URL}/api/config").json()
print(f"Current config: {cfg.get('scan_interval')}s interval, {len(cfg.get('servers',[]))} servers")

# Function to trigger a scan
def trigger_scan():
    try:
        resp = requests.post(f"{SERVER_URL}/api/scan", timeout=30)
        return resp.json()
    except Exception as e:
        return {'error': str(e)}

# Function to save config
def save_config(payload):
    try:
        resp = requests.post(
            f"{SERVER_URL}/api/config",
            json=payload,
            timeout=30
        )
        return resp.json()
    except requests.exceptions.Timeout:
        return {'error': 'TIMEOUT - request hung!'}
    except Exception as e:
        return {'error': str(e)}

# Test 1: Save while scan is running (trigger scan first, then immediately save)
print("\n=== Test 1: Save immediately after triggering scan ===")
scan_thread = threading.Thread(target=trigger_scan, daemon=True)
scan_thread.start()
time.sleep(0.1)  # Let scan start

t0 = time.time()
test_cfg = cfg.copy()
test_cfg['scan_interval'] = 55
result = save_config(test_cfg)
elapsed = time.time() - t0
print(f"  Save result: {result.get('ok')}, elapsed: {elapsed:.3f}s")
if 'TIMEOUT' in str(result.get('error', '')):
    print("  *** HANG DETECTED! ***")
scan_thread.join(timeout=5)

# Test 2: Multiple rapid saves while scan is running
print("\n=== Test 2: Rapid saves during scan ===")
scan_thread2 = threading.Thread(target=trigger_scan, daemon=True)
scan_thread2.start()
time.sleep(0.1)

for i in range(5):
    t0 = time.time()
    test_cfg = cfg.copy()
    test_cfg['scan_interval'] = 50 + i
    result = save_config(test_cfg)
    elapsed = time.time() - t0
    status = "OK" if result.get('ok') else f"FAIL: {result}"
    if 'TIMEOUT' in str(result.get('error', '')):
        status = "*** HUNG ***"
    print(f"  Save {i+1}: {elapsed:.3f}s - {status}")

scan_thread2.join(timeout=5)

# Test 3: Save with server count change
print("\n=== Test 3: Save with server modification ===")
test_cfg3 = cfg.copy()
if test_cfg3.get('servers'):
    test_cfg3['servers'][0]['enabled'] = not test_cfg3['servers'][0].get('enabled', True)
t0 = time.time()
result = save_config(test_cfg3)
elapsed = time.time() - t0
print(f"  Toggle server enabled: {elapsed:.3f}s - {'OK' if result.get('ok') else result}")

# Restore
test_cfg3['servers'][0]['enabled'] = not test_cfg3['servers'][0].get('enabled', True)
save_config(test_cfg3)

# Test 4: Save with geo_file_path change
print("\n=== Test 4: Save with geo_file_path change ===")
test_cfg4 = cfg.copy()
test_cfg4['geo_file_path'] = 'GeoLite2-City.mmdb'
t0 = time.time()
result = save_config(test_cfg4)
elapsed = time.time() - t0
print(f"  geo_file_path change: {elapsed:.3f}s - {'OK' if result.get('ok') else result}")

# Test 5: Concurrent saves from multiple threads
print("\n=== Test 5: Concurrent saves from multiple threads ===")
results_lock = threading.Lock()
results = []
errors = []

def multi_save(idx):
    try:
        t0 = time.time()
        test_cfg = cfg.copy()
        test_cfg['scan_interval'] = 60 + idx
        resp = requests.post(
            f"{SERVER_URL}/api/config",
            json=test_cfg,
            timeout=15
        )
        elapsed = time.time() - t0
        data = resp.json()
        with results_lock:
            results.append(f"T{idx}: {elapsed:.3f}s - {'OK' if data.get('ok') else data}")
    except requests.exceptions.Timeout:
        with results_lock:
            errors.append(f"T{idx}: TIMEOUT - HUNG!")
    except Exception as e:
        elapsed = time.time() - t0
        with results_lock:
            errors.append(f"T{idx}: {elapsed:.3f}s - {e}")

threads = []
for i in range(3):
    t = threading.Thread(target=multi_save, args=(i,))
    threads.append(t)
    t.start()

for t in threads:
    t.join(timeout=20)

for r in results:
    print(f"  {r}")
for e in errors:
    print(f"  *** {e} ***")

if errors:
    print("  *** HANG DETECTED in concurrent test! ***")
else:
    print("  PASS: No hangs in concurrent saves")

# Restore config
cfg['scan_interval'] = 60
save_config(cfg)

print("\n" + "=" * 60)
print("  STRESS TEST COMPLETE")
print("=" * 60)
