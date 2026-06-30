"""测试分页越界修正和配置保留字段"""
import sys, os
sys.path.insert(0, '.')
from database import get_scans_paginated, get_events_paginated, init_db, save_scan_record, save_event
from config_manager import load_config, save_config, get_safe_config

errors = []

def check(name, condition, detail=''):
    if not condition:
        errors.append(f'FAIL: {name} {detail}')

# Test 1: Initialize DB
init_db()
print('Test 1: DB initialized OK')

# Test 2: Config defaults for retention
cfg = load_config()
print(f"Test 2: scan_history_retention={cfg['scan_history_retention']}, event_history_retention={cfg['event_history_retention']}")
check('default scan_history_retention', cfg['scan_history_retention'] == 10000)
check('default event_history_retention', cfg['event_history_retention'] == 5000)
print('  -> Defaults OK' if not any('2' in e for e in errors) else '  -> FAIL')

# Test 3: Paging with empty DB (page clamping)
items, total, page = get_scans_paginated(page=1, page_size=50)
print(f'Test 3: Empty scans page=1 -> items={len(items)}, total={total}, clamped_page={page}')
check('empty page=1', page == 1 and total == 0)

# Test 4: Empty DB, page=999 should clamp to 1
items, total, page = get_scans_paginated(page=999, page_size=50)
print(f'Test 4: Empty scans page=999 -> items={len(items)}, total={total}, clamped_page={page}')
check('empty clamp to 1', page == 1, f'got page={page}')

# Test 5: Empty events page=999 should clamp to 1
items, total, page = get_events_paginated(page=999, page_size=50)
print(f'Test 5: Empty events page=999 -> items={len(items)}, total={total}, clamped_page={page}')
check('empty events clamp to 1', page == 1, f'got page={page}')

# Test 6: Insert records and test normal paging
for i in range(10):
    save_scan_record(
        server_name='test_server_{}'.format(i), server_type='test',
        scan_time='2026-06-29 00:00:00', online_count=i,
        client_ips=[], client_details=[], raw_output='',
        status='success', error_message='', duration_ms=100
    )

items, total, page = get_scans_paginated(page=1, page_size=3)
print(f'Test 6: 10 records, page=1, size=3 -> items={len(items)}, total={total}, clamped_page={page}')
check('10 records page 1', total >= 10 and len(items) == 3 and page == 1,
      f'total={total}, len={len(items)}, page={page}')

# Test 7: Normal page 4 of 3-per-page
items, total, page = get_scans_paginated(page=4, page_size=3)
print(f'Test 7: 10 records, page=4, size=3 -> items={len(items)}, total={total}, clamped_page={page}')
check('10 records page 4', page == 4, f'got page={page}')

# Test 8: Out of bounds page=999 with 10 records and page_size=3
items, total, page = get_scans_paginated(page=999, page_size=3)
expected_page = max(1, (total + 2) // 3)
print(f'Test 8: 10 records, page=999, size=3 -> items={len(items)}, total={total}, clamped_page={page} (expected={expected_page})')
check('out of bounds clamp', page == expected_page, f'expected={expected_page}, got={page}')

# Test 9: Page=0 should clamp to 1
items, total, page = get_scans_paginated(page=0, page_size=3)
print(f'Test 9: page=0 -> clamped_page={page}')
check('page 0 clamp', page == 1, f'got page={page}')

# Test 10: Save config with retention and verify
cfg1 = load_config()
cfg1['scan_history_retention'] = 500
cfg1['event_history_retention'] = 200
ok = save_config(cfg1)
print(f'Test 10: Save config with retention={ok}')
reloaded = load_config()
check('scan_history_retention saved', reloaded['scan_history_retention'] == 500,
      f'got {reloaded["scan_history_retention"]}')
check('event_history_retention saved', reloaded['event_history_retention'] == 200,
      f'got {reloaded["event_history_retention"]}')

# Test 11: get_safe_config includes retention
safe = get_safe_config()
print(f"Test 11: safe_config scan_history_retention={safe['scan_history_retention']}")
check('safe_config has retention', 'scan_history_retention' in safe and 'event_history_retention' in safe)

# Test 12: Events paging with data
for i in range(5):
    save_event('test_type', 'test_server', 'detail_{}'.format(i), notified=1)
items, total, page = get_events_paginated(page=1, page_size=2)
print(f'Test 12: 5 events, page=1, size=2 -> items={len(items)}, total={total}, clamped_page={page}')
check('events page 1', total >= 5 and len(items) == 2 and page == 1,
      f'total={total}, len={len(items)}, page={page}')

items, total, page = get_events_paginated(page=999, page_size=2)
expected_page = max(1, (total + 1) // 2)
print(f'Test 13: 5 events, page=999 -> clamped_page={page} (expected={expected_page})')
check('events out of bounds', page == expected_page, f'got page={page}')

# Restore config
cfg2 = load_config()
cfg2['scan_history_retention'] = 10000
cfg2['event_history_retention'] = 5000
save_config(cfg2)

print()
if errors:
    print('=== ERRORS ===')
    for e in errors:
        print('  ' + e)
else:
    print('=== ALL TESTS PASSED ===')
