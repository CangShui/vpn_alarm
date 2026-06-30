"""Integration test: save_config password merge logic"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import save_config, load_config, get_safe_config, _is_masked_password

# Backup original config
BACKUP = load_config()

print("=== Integration Test: Password Merge on Save ===")

# Scenario 1: Old config has REAL password, user saves with masked display value
print("\n--- Scenario 1: Real password in config, user saves masked value ---")
test1_old = {
    "servers": [{"name": "TestSrv", "host": "1.2.3.4", "port": 22, "username": "root", "password": "MyRealPass123", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test1_old)
loaded = load_config()
print(f"  After save (real): password = {loaded['servers'][0]['password']}")

# Now simulate frontend sending masked value
test1_masked = {
    "servers": [{"name": "TestSrv", "host": "1.2.3.4", "port": 22, "username": "root", "password": "My******123", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test1_masked)
loaded = load_config()
pwd = loaded['servers'][0]['password']
print(f"  After save (masked value): password = {pwd}")
print(f"  Password preserved? {'PASS' if pwd == 'MyRealPass123' else 'FAIL - got: ' + pwd}")

# Scenario 2: Old config has REAL password, user saves with empty password
print("\n--- Scenario 2: Real password in config, user saves empty ---")
test1_old2 = {
    "servers": [{"name": "TestSrv2", "host": "1.2.3.4", "port": 22, "username": "root", "password": "AnotherReal456", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test1_old2)

test1_empty = {
    "servers": [{"name": "TestSrv2", "host": "1.2.3.4", "port": 22, "username": "root", "password": "", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test1_empty)
loaded = load_config()
pwd = loaded['servers'][0]['password']
print(f"  After save (empty): password = {repr(pwd)}")
print(f"  Password preserved? {'PASS' if pwd == 'AnotherReal456' else 'FAIL - got: ' + repr(pwd)}")

# Scenario 3: Old config has MASKED password, user saves with empty
print("\n--- Scenario 3: Already-broken masked password, user saves empty ---")
test3_old = {
    "servers": [{"name": "TestSrv3", "host": "1.2.3.4", "port": 22, "username": "root", "password": "Hu******#$", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test3_old)
loaded = load_config()
print(f"  Before (masked in config): password = {loaded['servers'][0]['password']}")

test3_empty = {
    "servers": [{"name": "TestSrv3", "host": "1.2.3.4", "port": 22, "username": "root", "password": "", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test3_empty)
loaded = load_config()
pwd = loaded['servers'][0]['password']
print(f"  After save (empty): password = {repr(pwd)}")
print(f"  Expected: stays masked (can't recover) - {'PASS' if pwd == 'Hu******#$' else 'Got: ' + repr(pwd)}")

# Scenario 4: User enters NEW real password
print("\n--- Scenario 4: User enters new correct password ---")
test4_new = {
    "servers": [{"name": "TestSrv4", "host": "1.2.3.4", "port": 22, "username": "root", "password": "Huawei12#$", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test4_new)
loaded = load_config()
pwd = loaded['servers'][0]['password']
print(f"  After save (new real): password = {pwd}")
print(f"  Password accepted? {'PASS' if pwd == 'Huawei12#$' else 'FAIL'}")

# Scenario 5: SSH key authentication fields
print("\n--- Scenario 5: SSH key fields merge ---")
test5_old = {
    "servers": [{"name": "TestSrv5", "host": "1.2.3.4", "port": 22, "username": "root", "password": "pass123", "ssh_key_path": "/home/user/.ssh/id_rsa", "ssh_key_passphrase": "keypass456", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test5_old)

test5_empty_keypass = {
    "servers": [{"name": "TestSrv5", "host": "1.2.3.4", "port": 22, "username": "root", "password": "", "ssh_key_path": "", "ssh_key_passphrase": "", "command": "test", "type": "generic", "enabled": True}],
    "scan_interval": 60
}
save_config(test5_empty_keypass)
loaded = load_config()
srv = loaded['servers'][0]
print(f"  After save (all empty): pass={srv['password']}, key_path={srv['ssh_key_path']}, key_pass={srv['ssh_key_passphrase']}")
all_ok = srv['password'] == 'pass123' and srv['ssh_key_path'] == '/home/user/.ssh/id_rsa' and srv['ssh_key_passphrase'] == 'keypass456'
print(f"  All fields preserved? {'PASS' if all_ok else 'FAIL'}")

# Restore backup
print("\n--- Restoring original config ---")
save_config(BACKUP)

print("\n=== ALL INTEGRATION TESTS COMPLETE ===")
