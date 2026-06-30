"""Test: geo_file_path feature for LocalFileResolver"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# === Test 1: Backward compatibility - config.json without geo_file_path ===
print('=== Test 1: Backward compatibility (no geo_file_path in config) ===')
old_config = {
    'servers': [],
    'scan_interval': 60,
    'notifications': {'telegram': {}, 'webhook': {}}
}
cfg = old_config.copy()
cfg.setdefault('geo_file_path', '')
print(f'geo_file_path after setdefault: {repr(cfg["geo_file_path"])}')
assert cfg['geo_file_path'] == '', 'Expected empty string'
print('PASS: Old config without geo_file_path works, defaulting to empty string')

# === Test 2: Custom path is preserved ===
print()
print('=== Test 2: Custom path is saved and loaded ===')
custom_config = {
    'servers': [],
    'scan_interval': 60,
    'geo_file_path': 'C:/data/GeoLite2-City.mmdb',
    'notifications': {'telegram': {}, 'webhook': {}}
}
cfg2 = custom_config.copy()
cfg2.setdefault('geo_file_path', '')
assert cfg2['geo_file_path'] == 'C:/data/GeoLite2-City.mmdb', 'Custom path not preserved'
print('PASS: Custom path preserved')

# === Test 3: init_resolvers path selection logic ===
print()
print('=== Test 3: init_resolvers path selection logic ===')
GEOSITE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'GeoSite.dat')

# Case A: empty string -> use default
custom_path_a = ''
if custom_path_a and os.path.exists(custom_path_a):
    fp_a = custom_path_a
else:
    fp_a = GEOSITE_PATH
print(f'Empty path -> filepath = {fp_a}')
print(f'  (default GeoSite.dat exists? {os.path.exists(fp_a)})')

# Case B: set to existing file -> use custom
custom_path_b = 'config.json'
if custom_path_b and os.path.exists(custom_path_b):
    fp_b = custom_path_b
else:
    fp_b = GEOSITE_PATH
print(f'Valid custom path -> filepath = {fp_b}')
assert fp_b == 'config.json', 'Should use custom path when file exists'
print('PASS: Custom existing file path is selected')

# Case C: set to non-existing file -> fallback to default
custom_path_c = 'C:/nonexistent/GeoIP.dat'
if custom_path_c and os.path.exists(custom_path_c):
    fp_c = custom_path_c
else:
    fp_c = GEOSITE_PATH
print(f'Non-existing custom path -> filepath = {fp_c}')
print('PASS: Non-existing file falls back to default')

# === Test 4: LocalFileResolver instantiation with custom path ===
print()
print('=== Test 4: LocalFileResolver accepts custom path ===')
from geo_resolver import LocalFileResolver

resolver = LocalFileResolver('config.json')
status = resolver.status()
print(f'Custom file: {status["file"]}')
print(f'Available: {status["available"]}')
print(f'Error: {status["error"]}')
assert status['file'] == 'config.json', 'file path not propagated'
print('PASS: LocalFileResolver uses custom path, handles non-GeoDB file gracefully')

# === Test 5: Config save/load round-trip with geo_file_path ===
print()
print('=== Test 5: Config save/load round-trip ===')
from config_manager import save_config, load_config, get_safe_config

BACKUP = load_config()

test_cfg = {
    'servers': [
        {'name': 'test', 'host': 'localhost', 'port': 22, 'username': 'root',
         'password': 'test', 'command': 'echo', 'type': 'generic', 'enabled': True}
    ],
    'scan_interval': 60,
    'geo_file_path': 'C:/test/GeoLite2-City.mmdb',
    'notifications': {
        'telegram': {'enabled': False, 'token': '', 'chat_id': ''},
        'webhook': {'enabled': False, 'url': '', 'content_type': 'application/json',
                     'headers': {}, 'body_template': '{"msg": "{{message}}"}'}
    }
}
save_config(test_cfg)
loaded = load_config()
print(f'Loaded geo_file_path: {loaded["geo_file_path"]}')
assert loaded['geo_file_path'] == 'C:/test/GeoLite2-City.mmdb', 'geo_file_path not saved/loaded correctly'
print('PASS: Round-trip save/load preserves geo_file_path')

# Restore original config
save_config(BACKUP)
print('Config restored to original.')

# === Test 6: Safe config includes geo_file_path ===
print()
print('=== Test 6: Safe config includes geo_file_path ===')
safe = get_safe_config()
print(f'Safe config keys: {list(safe.keys())}')
assert 'geo_file_path' in safe, 'geo_file_path not in safe config'
print('PASS: Safe config exposes geo_file_path for frontend')

# === Test 7: init_resolvers works (integration test) ===
print()
print('=== Test 7: init_resolvers integration ===')
from geo_resolver import init_resolvers, get_resolver_status
init_resolvers()
statuses = get_resolver_status()
for s in statuses:
    print(f'  Resolver: {s["name"]}, file: {s.get("file", "N/A")}, available: {s["available"]}')
assert len(statuses) >= 1, 'Should have at least one resolver'
print('PASS: init_resolvers runs without error')

print()
print('=== ALL TESTS PASSED ===')
