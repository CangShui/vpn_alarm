"""Test retry mechanism: simulate stale connection then verify auto-reconnect"""
import sys, os, json, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from collector import (
    collect_server, _get_or_create_connection, _ssh_exec,
    _invalidate_connection, _conn_cache, _conn_lock, _make_cache_key
)
import paramiko

with open('config.json', 'r') as f:
    cfg = json.load(f)

# Test with server B (OpenVPN) - simpler command, faster
srv = cfg['servers'][1]  # server B
print(f'=== Retry mechanism test ===')
print(f'Target: {srv["name"]} ({srv["host"]}:{srv["port"]})')
print()

# Step 1: Create a cached connection
print('Step 1: Creating cached connection...')
client = _get_or_create_connection(srv, timeout=30)
key = _make_cache_key(srv)
print(f'  Cache key: {key}')
print(f'  Connection created, transport active: {client.get_transport().is_active()}')

# Step 2: Verify command works on this connection
print('\nStep 2: Test command on fresh connection...')
try:
    out = _ssh_exec(client, srv['command'], timeout=30)
    print(f'  Output length: {len(out)} chars')
    print(f'  Success!')
except Exception as e:
    print(f'  FAILED: {type(e).__name__}: {e}')

# Step 3: Simulate stale connection by closing the transport's socket
print('\nStep 3: Simulating stale connection (closing underlying socket)...')
try:
    transport = client.get_transport()
    # Force close the socket to simulate network drop
    sock = transport.sock
    print(f'  Socket type: {type(sock).__name__}')
    sock.shutdown(2)  # SHUT_RDWR
    sock.close()
    print('  Socket forcibly closed (simulating connection loss)')
except Exception as e:
    print(f'  Warning during socket close: {e}')

# Step 4: Verify transport.is_active() still returns True (the bug scenario)
print('\nStep 4: Check transport.is_active() after socket close...')
try:
    still_active = client.get_transport().is_active()
    print(f'  is_active(): {still_active} (may still be True - this is the root cause)')
except Exception as e:
    print(f'  is_active() raised: {type(e).__name__}: {e}')

# Step 5: Now try to use the stale connection - should fail
print('\nStep 5: Try command on stale connection (should fail and trigger retry)...')
t0 = time.time()
result = collect_server(srv, timeout=30)
elapsed = time.time() - t0
print(f'  Result status: {result["status"]}')
print(f'  Error message: {result["error_message"] or "(none)"}')
print(f'  Duration: {result["duration_ms"]}ms (wall: {elapsed:.2f}s)')
if result['status'] == 'success':
    print('  ** RETRY MECHANISM WORKS: auto-reconnected and succeeded! **')
else:
    print(f'  ** RETRY FAILED: {result["error_message"]}')

# Step 6: Verify cache has a fresh connection
print(f'\nStep 6: Cache state after test...')
with _conn_lock:
    keys = list(_conn_cache.keys())
print(f'  Cache entries: {len(keys)}')
for k in keys:
    entry = _conn_cache[k]
    age = time.time() - entry['created_at']
    transport = entry['client'].get_transport()
    try:
        active = transport.is_active() if transport else False
    except:
        active = 'error'
    print(f'  {k}: age={age:.1f}s, active={active}')

print('\n=== Test complete ===')
