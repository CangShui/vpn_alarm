"""Direct collector test - verify Errno 22 fix"""
import sys, os, json, time, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from collector import collect_server, _conn_cache, _conn_lock

# Load config
with open('config.json', 'r') as f:
    cfg = json.load(f)

servers = cfg.get('servers', [])
print('=== Direct collector test ===')
print(f'Conn cache before test: {len(_conn_cache)} entries')

for srv in servers:
    if not srv.get('enabled', True):
        continue
    name = srv.get('name', 'unknown')
    host = srv.get('host', '?')
    port = srv.get('port', '?')
    print(f'\n--- Testing: {name} ({host}:{port}) ---')
    t0 = time.time()
    try:
        result = collect_server(srv, timeout=30)
        elapsed = time.time() - t0
        print(f'  Status: {result["status"]}')
        print(f'  Online: {result["online_count"]}')
        print(f'  IPs: {result["client_ips"]}')
        print(f'  Error: {result["error_message"] or "(none)"}')
        print(f'  Duration: {result["duration_ms"]}ms (wall: {elapsed:.2f}s)')
        if result['status'] != 'success':
            print(f'  ** WARNING: non-success status **')
    except Exception as e:
        elapsed = time.time() - t0
        print(f'  EXCEPTION after {elapsed:.2f}s: {type(e).__name__}: {e}')
        traceback.print_exc()

print(f'\nConn cache after test: {len(_conn_cache)} entries')
for key, entry in _conn_cache.items():
    age = time.time() - entry['created_at']
    print(f'  {key}: age={age:.1f}s')
