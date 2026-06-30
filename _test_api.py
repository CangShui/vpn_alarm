"""Live Flask API test for pagination and page clamping"""
import sys, os, json, time, threading
sys.path.insert(0, '.')

from app import app

# Create test client
client = app.test_client()

print('=== Flask API Tests ===')

# Test 1: /api/scans with valid params
r = client.get('/api/scans?page=1&page_size=5')
data = json.loads(r.data)
assert data['ok'], 'API should return ok'
assert 'items' in data and 'total' in data and 'page' in data
assert data['page'] == 1
assert data['page_size'] == 5
assert len(data['items']) <= 5
print(f'Test 1: /api/scans page=1 size=5 -> total={data["total"]}, items={len(data["items"])}, page={data["page"]} PASS')

# Test 2: /api/scans with out-of-bounds page
r = client.get('/api/scans?page=99999&page_size=10')
data = json.loads(r.data)
assert data['ok']
total_pages = max(1, (data['total'] + 9) // 10)
assert data['page'] == total_pages, f'Expected page clamp to {total_pages}, got {data["page"]}'
print(f'Test 2: /api/scans page=99999 -> clamped to {data["page"]} (max={total_pages}) PASS')

# Test 3: /api/events with out-of-bounds page
r = client.get('/api/events?page=99999&page_size=5')
data = json.loads(r.data)
assert data['ok']
total_pages = max(1, (data['total'] + 4) // 5)
assert data['page'] == total_pages, f'Expected page clamp to {total_pages}, got {data["page"]}'
print(f'Test 3: /api/events page=99999 -> clamped to {data["page"]} (max={total_pages}) PASS')

# Test 4: Both tabs have independent state check via API
r1 = client.get('/api/scans?page=1&page_size=10')
s1 = json.loads(r1.data)
r2 = client.get('/api/events?page=1&page_size=20')
s2 = json.loads(r2.data)
# They should have different page_size values
assert s1['page_size'] == 10
assert s2['page_size'] == 20
print(f'Test 4: Independent API calls -> scans page_size={s1["page_size"]}, events page_size={s2["page_size"]} PASS')

# Test 5: /api/config GET returns retention fields
r = client.get('/api/config')
data = json.loads(r.data)
assert 'scan_history_retention' in data, 'Missing scan_history_retention'
assert 'event_history_retention' in data, 'Missing event_history_retention'
print(f'Test 5: /api/config has retention: scan={data["scan_history_retention"]}, event={data["event_history_retention"]} PASS')

# Test 6: /api/config POST saves retention fields
from config_manager import load_config
old_cfg = load_config()
old_scan = old_cfg['scan_history_retention']
old_event = old_cfg['event_history_retention']

new_config = dict(old_cfg)
new_config['scan_history_retention'] = 3333
new_config['event_history_retention'] = 7777
r = client.post('/api/config', json=new_config)
data = json.loads(r.data)
assert data['ok'], f'Config save failed: {data}'

verify = load_config()
assert verify['scan_history_retention'] == 3333, f'Expected 3333, got {verify["scan_history_retention"]}'
assert verify['event_history_retention'] == 7777, f'Expected 7777, got {verify["event_history_retention"]}'
print(f'Test 6: Config POST saved retention: scan={verify["scan_history_retention"]}, event={verify["event_history_retention"]} PASS')

# Restore
restore_cfg = load_config()
restore_cfg['scan_history_retention'] = old_scan
restore_cfg['event_history_retention'] = old_event
r = client.post('/api/config', json=restore_cfg)
json.loads(r.data)

# Test 7: History page renders
r = client.get('/history')
assert r.status_code == 200
html = r.data.decode('utf-8')
assert '扫描历史' in html
assert '事件日志' in html
assert 'tab-scans' in html
assert 'tab-events' in html
assert 'scans-pagination' in html
assert 'events-pagination' in html
print('Test 7: /history page renders with two tabs and pagination containers PASS')

# Test 8: Config page renders with retention fields
r = client.get('/config')
assert r.status_code == 200
html = r.data.decode('utf-8')
assert 'scan_history_retention' in html
assert 'event_history_retention' in html
print('Test 8: /config page renders with retention fields PASS')

print()
print('=== ALL FLASK API TESTS PASSED ===')
