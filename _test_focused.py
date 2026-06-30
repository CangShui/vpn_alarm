"""Focused tests for page clamping and retention config"""
import sys, os
sys.path.insert(0, '.')
from database import get_scans_paginated, get_events_paginated
from config_manager import load_config, save_config

print('=== Page Clamping Tests (database.py) ===')

# Test A: total=0, any page clamps to 1
items, total, page = get_events_paginated(page=1, page_size=50)
# Note: DB may have events. We check that page <= max_pages
total_pages = max(1, (total + 49) // 50)
assert page >= 1 and page <= total_pages, f'page={page} out of [1, {total_pages}]'
print(f'A: total={total}, page=1 -> clamped_page={page} (max={total_pages}) PASS')

# Test B: page=99999 should clamp
items, total, page = get_events_paginated(page=99999, page_size=10)
total_pages = max(1, (total + 9) // 10)
assert page == total_pages, f'Expected clamp to {total_pages}, got {page}'
print(f'B: page=99999 clamped to {page} (max={total_pages}) PASS')

# Test C: page=0 should clamp to 1
items, total, page = get_scans_paginated(page=0, page_size=50)
assert page == 1, f'Expected 1, got {page}'
print(f'C: page=0 clamped to {page} PASS')

# Test D: page=-5 should clamp to 1
items, total, page = get_scans_paginated(page=-5, page_size=50)
assert page == 1, f'Expected 1, got {page}'
print(f'D: page=-5 clamped to {page} PASS')

# Test E: normal valid page passes through
total_for_E = total
if total_for_E > 0:
    mid_page = max(1, total_for_E // 2)
    items2, total2, page2 = get_events_paginated(page=mid_page, page_size=1)
    assert page2 == mid_page, f'Expected {mid_page}, got {page2}'
    print(f'E: valid page={mid_page} passes through ({len(items2)} items) PASS')
else:
    print(f'E: skipped (no data)')

print()
print('=== Config Retention Tests ===')

# Test F: config save/load round-trip
cfg = load_config()
original_scan = cfg['scan_history_retention']
original_event = cfg['event_history_retention']
print(f'F1: Original: scan={original_scan}, event={original_event}')

cfg['scan_history_retention'] = 777
cfg['event_history_retention'] = 333
assert save_config(cfg), 'Save failed'

cfg2 = load_config()
assert cfg2['scan_history_retention'] == 777, f'Expected 777, got {cfg2["scan_history_retention"]}'
assert cfg2['event_history_retention'] == 333, f'Expected 333, got {cfg2["event_history_retention"]}'
print(f'F2: After save/load: scan={cfg2["scan_history_retention"]}, event={cfg2["event_history_retention"]} PASS')

# Restore
cfg3 = load_config()
cfg3['scan_history_retention'] = original_scan
cfg3['event_history_retention'] = original_event
save_config(cfg3)
cfg4 = load_config()
assert cfg4['scan_history_retention'] == original_scan
assert cfg4['event_history_retention'] == original_event
print(f'F3: Restored: scan={cfg4["scan_history_retention"]}, event={cfg4["event_history_retention"]} PASS')

# Test G: Two retention fields are independent
cfg5 = load_config()
cfg5['scan_history_retention'] = 100
cfg5['event_history_retention'] = 50000
save_config(cfg5)
cfg6 = load_config()
assert cfg6['scan_history_retention'] == 100
assert cfg6['event_history_retention'] == 50000
print(f'G: Independent retention fields: scan={cfg6["scan_history_retention"]}, event={cfg6["event_history_retention"]} PASS')

# Restore
cfg7 = load_config()
cfg7['scan_history_retention'] = original_scan
cfg7['event_history_retention'] = original_event
save_config(cfg7)

print()
print('=== ALL TESTS PASSED ===')
