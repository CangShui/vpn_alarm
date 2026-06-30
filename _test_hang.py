"""Reproduce the hang issue with /api/config save"""
import sys
import os
import json
import time
import threading
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("  Reproduce /api/config hang investigation")
print("=" * 60)

# === Test 1: maxminddb double open ===
print("\n=== Test 1: maxminddb open/close behavior ===")
import maxminddb
MMDB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'GeoLite2-City.mmdb')
print(f"MMDB file exists: {os.path.exists(MMDB_FILE)}, size: {os.path.getsize(MMDB_FILE)}")

t0 = time.time()
r1 = maxminddb.open_database(MMDB_FILE)
print(f"  Open 1: {time.time()-t0:.3f}s")

t0 = time.time()
r2 = maxminddb.open_database(MMDB_FILE)
print(f"  Open 2 (reader1 still open): {time.time()-t0:.3f}s")

t0 = time.time()
r1.close()
print(f"  Close r1: {time.time()-t0:.3f}s")

t0 = time.time()
r2.close()
print(f"  Close r2: {time.time()-t0:.3f}s")

print("  PASS: No hang on double open")

# === Test 2: init_resolvers() speed ===
print("\n=== Test 2: init_resolvers() performance ===")
from geo_resolver import init_resolvers, get_resolver_status

t0 = time.time()
init_resolvers()
print(f"  First call: {time.time()-t0:.3f}s")

t0 = time.time()
init_resolvers()
print(f"  Second call (re-init, old not closed): {time.time()-t0:.3f}s")

status = get_resolver_status()
print(f"  Resolvers: {len(status)}, available: {status[0]['available'] if status else 'N/A'}")
print("  PASS: init_resolvers is fast")

# === Test 3: save_config speed ===
print("\n=== Test 3: save_config() performance ===")
from config_manager import save_config, load_config

cfg = load_config()
t0 = time.time()
ok = save_config(cfg)
print(f"  save_config (same config): {time.time()-t0:.3f}s, ok={ok}")

# === Test 4: on_scan_interval_changed simulation ===
print("\n=== Test 4: scheduler interaction (simulated) ===")
from apscheduler.schedulers.background import BackgroundScheduler

def dummy_scan():
    time.sleep(0.1)

sched = BackgroundScheduler()
sched.add_job(dummy_scan, 'interval', seconds=60, id='periodic_scan', max_instances=1)
sched.start()

t0 = time.time()
try:
    sched.remove_job('periodic_scan')
except Exception:
    pass
sched.add_job(dummy_scan, 'interval', seconds=60, id='periodic_scan', replace_existing=True, max_instances=1)
print(f"  remove + add job: {time.time()-t0:.3f}s")

t0 = time.time()
for i in range(5):
    try:
        sched.remove_job('periodic_scan')
    except Exception:
        pass
    sched.add_job(dummy_scan, 'interval', seconds=60, id='periodic_scan', replace_existing=True, max_instances=1)
print(f"  5x remove+add: {time.time()-t0:.3f}s")

sched.shutdown(wait=False)
print("  PASS: scheduler ops are fast")

# === Test 5: HTTP request to running server ===
print("\n=== Test 5: HTTP /api/config POST test ===")
import subprocess
import urllib.request
import urllib.error

# Start server in background
server_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')
print(f"  Starting server: {server_script}")

# We'll use a separate process
SERVER_URL = "http://127.0.0.1:5000"

# Try to detect if server is already running
try:
    resp = urllib.request.urlopen(f"{SERVER_URL}/api/config", timeout=2)
    print("  Server already running!")
    server_running = True
except Exception:
    server_running = False
    print("  Server not running, will start it...")
    # Start in background
    proc = subprocess.Popen(
        [sys.executable, server_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    # Wait for server to start
    print("  Waiting for server to start (may take time for initial scan)...")
    for attempt in range(120):
        try:
            resp = urllib.request.urlopen(f"{SERVER_URL}/api/config", timeout=2)
            print(f"  Server started after {attempt+1}s")
            server_running = True
            break
        except Exception:
            time.sleep(1)
    else:
        print("  FAIL: Server did not start within 120s")
        server_running = False

if server_running:
    print("\n  === Running save tests ===")
    
    # Test 5a: Simple save (no changes)
    test_payload = json.dumps(load_config()).encode('utf-8')
    print(f"  Test 5a: Simple save...")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/api/config",
            data=test_payload,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        elapsed = time.time() - t0
        print(f"  Result: {result}, elapsed: {elapsed:.3f}s")
        if result.get('ok'):
            print("  PASS: Simple save works")
        else:
            print(f"  FAIL: {result}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  FAIL after {elapsed:.3f}s: {e}")
    
    # Test 5b: Change scan interval
    test_payload2 = json.dumps(load_config()).encode('utf-8')
    cfg2 = load_config()
    cfg2['scan_interval'] = 30
    test_payload2 = json.dumps(cfg2).encode('utf-8')
    print(f"\n  Test 5b: Change scan interval to 30...")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/api/config",
            data=test_payload2,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        elapsed = time.time() - t0
        print(f"  Result: {result}, elapsed: {elapsed:.3f}s")
        if result.get('ok'):
            print("  PASS: Interval change works")
        else:
            print(f"  FAIL: {result}")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  FAIL after {elapsed:.3f}s: {e}")
    
    # Restore interval
    cfg3 = load_config()
    cfg3['scan_interval'] = 60
    test_payload3 = json.dumps(cfg3).encode('utf-8')
    print(f"\n  Test 5c: Restore scan interval to 60...")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/api/config",
            data=test_payload3,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        elapsed = time.time() - t0
        print(f"  Result: {result}, elapsed: {elapsed:.3f}s")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  FAIL after {elapsed:.3f}s: {e}")
    
    # Test 5d: Change geo_file_path
    cfg4 = load_config()
    cfg4['geo_file_path'] = 'GeoLite2-City.mmdb'
    test_payload4 = json.dumps(cfg4).encode('utf-8')
    print(f"\n  Test 5d: Change geo_file_path...")
    t0 = time.time()
    try:
        req = urllib.request.Request(
            f"{SERVER_URL}/api/config",
            data=test_payload4,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        elapsed = time.time() - t0
        print(f"  Result: {result}, elapsed: {elapsed:.3f}s")
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  FAIL after {elapsed:.3f}s: {e}")
    
    # Test 5e: Rapid consecutive saves (stress test)
    print(f"\n  Test 5e: Rapid consecutive saves (5 in a row)...")
    for i in range(5):
        cfg_i = load_config()
        cfg_i['scan_interval'] = 60 + i
        payload = json.dumps(cfg_i).encode('utf-8')
        t0 = time.time()
        try:
            req = urllib.request.Request(
                f"{SERVER_URL}/api/config",
                data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read().decode())
            elapsed = time.time() - t0
            status_str = "OK" if result.get('ok') else f"FAIL: {result}"
            print(f"    Save {i+1}: {elapsed:.3f}s - {status_str}")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"    Save {i+1}: {elapsed:.3f}s - EXCEPTION: {e}")
    
    # Restore
    cfg_restore = load_config()
    cfg_restore['scan_interval'] = 60
    payload_r = json.dumps(cfg_restore).encode('utf-8')
    req = urllib.request.Request(
        f"{SERVER_URL}/api/config",
        data=payload_r,
        headers={'Content-Type': 'application/json'},
        method='POST'
    )
    urllib.request.urlopen(req, timeout=10)

print("\n" + "=" * 60)
print("  INVESTIGATION COMPLETE")
print("=" * 60)
