"""SSH connectivity test script"""
import paramiko

# Test Server A - full output
print('=== Server A - ipsec statusall (FULL) ===')
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(hostname='192.168.4.4', port=44443, username='root',
          password='Huawei12#$', timeout=15, allow_agent=False, look_for_keys=False)
stdin, stdout, stderr = c.exec_command('docker exec ikev2-psk ipsec statusall', timeout=15)
out = stdout.read().decode('utf-8', errors='replace')
err = stderr.read().decode('utf-8', errors='replace')
print(out)
if err:
    print('---STDERR---')
    print(err)
c.close()

print('\n\n=== Server B - openvpn status log (FULL) ===')
c2 = paramiko.SSHClient()
c2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c2.connect(hostname='192.168.4.1', port=22, username='root',
           password='ZamRwD6881056417319H3c@123', timeout=15,
           allow_agent=False, look_for_keys=False)
stdin2, stdout2, stderr2 = c2.exec_command('cat /var/log/openvpn_status.log', timeout=15)
out2 = stdout2.read().decode('utf-8', errors='replace')
err2 = stderr2.read().decode('utf-8', errors='replace')
print(out2)
if err2:
    print('---STDERR---')
    print(err2)
c2.close()
