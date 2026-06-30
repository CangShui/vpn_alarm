"""Verification script for fixes"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("  Verification of Fixes")
print("=" * 60)

# === Test 1: MMDB validation ===
print("\n=== Test 1: MMDB validation ===")
from geo_resolver import LocalFileResolver

# Test with valid mmdb file
resolver = LocalFileResolver('GeoLite2-City.mmdb')
status = resolver.status()
print(f"Valid mmdb -> Available: {status['available']}, Error: {status['error'] or '(none)'}")

# Test resolve
if status['available']:
    result = resolver.resolve('8.8.8.8')
    print(f"  Resolve 8.8.8.8: city={result.get('city')}, country={result.get('country')}")

# Test with invalid file (config.json is not mmdb)
resolver2 = LocalFileResolver('config.json')
status2 = resolver2.status()
print(f"Invalid file -> Available: {status2['available']}")
print(f"  Error: {status2['error'][:150]}...")

# Test with non-existent file
resolver3 = LocalFileResolver('nonexistent.mmdb')
status3 = resolver3.status()
print(f"Non-existent -> Available: {status3['available']}, Error: {status3['error']}")

# === Test 2: Password merge logic ===
print("\n=== Test 2: Password merge logic ===")
from config_manager import _is_masked_password, _merge_server_passwords, load_config

test_pwds = [
    ("Hu******#$", True),
    ("Za**********************23", True),
    ("Huawei12#$", False),
    ("", False),
    ("abc", False),
]
for pwd, expected in test_pwds:
    result = _is_masked_password(pwd)
    status_str = "PASS" if result == expected else "FAIL"
    print(f"  {status_str}: _is_masked_password({repr(pwd)}) = {result} (expected={expected})")

# Test merge: if masked password is in current config and user submits empty/masked, keep old
print("\n  Merge test - masked password should be preserved:")
cfg = load_config()
print(f"  Current config servers count: {len(cfg.get('servers', []))}")
for srv in cfg.get('servers', []):
    pwd = srv.get('password', '')
    is_masked = _is_masked_password(pwd)
    print(f"    {srv['name']}: password has_asterisks={is_masked}, length={len(pwd)}")

# Simulate frontend saving with empty passwords
test_new_servers = [
    {"name": "ServerA-Test", "host": "1.2.3.4", "password": "", "command": "test"},
]
merged = _merge_server_passwords(test_new_servers)
print(f"  After merge (empty password): {repr(merged[0].get('password', ''))}")

# === Test 3: Imports ===
print("\n=== Test 3: Module imports ===")
try:
    from collector import collect_server, _build_auth_hint
    print("  collector.py: OK")
except Exception as e:
    print(f"  collector.py: FAIL - {e}")

try:
    from config_manager import save_config, get_safe_config
    print("  config_manager.py: OK")
except Exception as e:
    print(f"  config_manager.py: FAIL - {e}")

try:
    from geo_resolver import init_resolvers, get_resolver_status
    print("  geo_resolver.py: OK")
except Exception as e:
    print(f"  geo_resolver.py: FAIL - {e}")

# === Test 4: Safe config includes new fields ===
print("\n=== Test 4: Safe config includes new fields ===")
safe = get_safe_config()
for srv in safe.get('servers', []):
    has_ssh = 'ssh_key_path' in srv
    has_placeholder = 'password_display_placeholder' in srv
    print(f"  {srv['name']}:")
    print(f"    has ssh_key_path: {has_ssh}")
    print(f"    has password_display_placeholder: {has_placeholder}")
    print(f"    password_display_placeholder value: {srv.get('password_display_placeholder')}")

# === Test 5: init_resolvers works ===
print("\n=== Test 5: init_resolvers integration ===")
init_resolvers()
statuses = get_resolver_status()
for s in statuses:
    print(f"  {s['name']}: available={s['available']}, error={str(s.get('error', '(none)'))[:80]}")

# === Test 6: Auth hint function ===
print("\n=== Test 6: Auth hint function ===")
test_configs = [
    ({'password': 'test'}, 'password'),
    ({'ssh_key_path': '/key'}, 'key'),
    ({'password': 'test', 'ssh_key_path': '/key'}, 'both'),
    ({}, 'none'),
]
for config, desc in test_configs:
    hint = _build_auth_hint(config)
    print(f"  {desc}: {hint}")

print("\n" + "=" * 60)
print("  ALL VERIFICATION COMPLETE")
print("=" * 60)
