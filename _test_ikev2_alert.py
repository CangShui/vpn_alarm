"""
IKEv2 Alert Chain Verification
Simulates the full chain: SSH output -> parse -> normalize -> alertable check -> save_event/notify
Uses real server output format with simulated ESTABLISHED lines.
"""
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from collector import _parse_ikev2
from app import _normalize_client_details, _get_alertable_sessions, _get_session_marker
from database import init_db, save_event, get_recent_events


def build_realistic_output(established_line):
    """Build realistic strongSwan output with the given ESTABLISHED line"""
    return f"""Status of IKE charon daemon (strongSwan 5.9.13, Linux 6.8.12-9-pve, x86_64):
  uptime: 6 days, since Jun 22 09:04:27 2026
  worker threads: 11 of 16 idle, 5/0/0/0 working, job queue: 0/0/0/0, scheduled: 0
  loaded plugins: charon aesni mgf1 random nonce x509 revocation constraints pubkey pkcs1 pkcs7 pkcs12 pgp dnskey sshkey pem openssl pkcs8 fips-prf gmp curve25519 xcbc cmac kdf gcm drbg curl sqlite attr kernel-netlink resolve socket-default bypass-lan farp stroke vici updown eap-identity eap-sim eap-aka eap-aka-3gpp2 eap-simaka-pseudonym eap-simaka-reauth eap-md5 eap-mschapv2 eap-radius eap-tls xauth-generic xauth-eap dhcp unity counters
Virtual IP pools (size/online/offline):
  10.10.10.0/24: 254/0/1
Listening IP addresses:
  192.168.4.4
  192.168.0.1
  172.17.0.1
  172.18.0.1
Connections:
   ikev2-psk:  %any...%any  IKEv2, dpddelay=30s
   ikev2-psk:   local:  [openwrt.781998.xyz] uses pre-shared key authentication
   ikev2-psk:   remote: uses pre-shared key authentication
   ikev2-psk:   child:  0.0.0.0/0 === dynamic TUNNEL, dpdaction=none
Shunted Connections:
Bypass LAN 172.17.0.0/16:  172.17.0.0/16 === 172.17.0.0/16 PASS
Bypass LAN 172.18.0.0/16:  172.18.0.0/16 === 172.18.0.0/16 PASS
Bypass LAN 192.168.0.0/24:  192.168.0.0/24 === 192.168.0.0/24 PASS
Bypass LAN 192.168.4.0/24:  192.168.4.0/24 === 192.168.4.0/24 PASS
Bypass LAN fe80::/64:  fe80::/64 === fe80::/64 PASS
Security Associations (1 up, 0 connecting):
{established_line}
  ikev2-psk{{1}}:  INSTALLED, TUNNEL, reqid 1, ESP in UDP SPIs: c1234567_i d7654321_o
  ikev2-psk{{1}}:   0.0.0.0/0 === 10.10.10.1/32"""


def simulate_do_scan_alert_check(client_details, client_ips, prev_ips, prev_alerted_keys, alert_window):
    """Simulate the alert checking logic from do_scan()"""
    new_ips = set(client_ips)
    prev_ips = set(prev_ips) if prev_ips else set()
    new_ip_set = new_ips - prev_ips
    normalized = _normalize_client_details(client_details)
    alertable = _get_alertable_sessions(normalized, alert_window)
    current_keys = {(d['ip'], _get_session_marker(d)) for d in normalized}

    alerts = []
    for d in alertable:
        sk = (d['ip'], _get_session_marker(d))
        skip1 = d['ip'] not in new_ip_set and sk in prev_alerted_keys
        skip2 = sk in prev_alerted_keys
        if skip1 or skip2:
            continue
        alerts.append(d)

    # Update prev_alerted_keys (mirrors do_scan)
    new_prev_alerted = prev_alerted_keys.intersection(current_keys)
    new_prev_alerted.update({(d['ip'], _get_session_marker(d)) for d in alertable})

    return alerts, new_ips, new_prev_alerted


# ============================================================
def main():
    print("=" * 60)
    print("  IKEv2 ALERT CHAIN - END TO END VERIFICATION")
    print("=" * 60)

    init_db()
    alert_window = 300

    # ===== SCENARIO A: New client, 30 seconds connected =====
    print("\n--- SCENARIO A: New client connects (30s ago) ---")
    established_line = "  ikev2-psk[1]: ESTABLISHED 30 seconds ago, 192.168.4.4[openwrt.781998.xyz]...114.246.237.147[10.10.10.1]"
    output = build_realistic_output(established_line)
    ips, cnt, details = _parse_ikev2(output)

    print(f"  Parsed: online_count={cnt}, client_ips={ips}")
    for d in details:
        print(f"    detail: IP={d['ip']}, connected_since='{d['connected_since']}', connected_seconds={d['connected_seconds']}")

    details_a_cs = details[0]['connected_since'] if details else ''
    details_a_sec = details[0]['connected_seconds'] if details else None

    alerts, new_ips, prev_alerted = simulate_do_scan_alert_check(
        details, ips, set(), set(), alert_window
    )

    print(f"  Alerts fired: {len(alerts)}")
    for a in alerts:
        print(f"    -> ALERT: {a['ip']}, age={a['connected_seconds']}s")
        save_event('new_client_alert', '服务器A (IKEv2)',
                   f"新客户端上线: {a['ip']}，已连接 {a['connected_seconds']} 秒",
                   notified=1)

    test_a_pass = len(alerts) == 1 and alerts[0]['ip'] == '114.246.237.147'
    print(f"  SCENARIO A: {'PASS' if test_a_pass else 'FAIL'}")

    # ===== SCENARIO B: Old client (>300s) =====
    print("\n--- SCENARIO B: Old client (400s) - should NOT alert ---")
    established_line_b = "  ikev2-psk[1]: ESTABLISHED 400 seconds ago, 192.168.4.4[openwrt.781998.xyz]...203.0.113.5[10.10.10.2]"
    output_b = build_realistic_output(established_line_b)
    ips_b, cnt_b, details_b = _parse_ikev2(output_b)

    alerts_b, _, _ = simulate_do_scan_alert_check(
        details_b, ips_b, set(), set(), alert_window
    )

    print(f"  Alerts fired: {len(alerts_b)} (expected: 0)")
    test_b_pass = len(alerts_b) == 0
    print(f"  SCENARIO B: {'PASS' if test_b_pass else 'FAIL'}")

    # ===== SCENARIO C: Same connection, second scan - no re-alert =====
    print("\n--- SCENARIO C: Same connection on second scan (no re-alert) ---")
    # Wait 2 seconds so that 'now' advances. Then use duration = 32s (30 + 2)
    # This simulates real time passage: connected_since = now - 32 = (T0+32) - 32 = T0 (same as scan A)
    time.sleep(2)
    established_line_c = "  ikev2-psk[1]: ESTABLISHED 32 seconds ago, 192.168.4.4[openwrt.781998.xyz]...114.246.237.147[10.10.10.1]"
    output_c = build_realistic_output(established_line_c)
    ips_c, cnt_c, details_c = _parse_ikev2(output_c)

    print(f"  Scan A detail: connected_since='{details_a_cs}', connected_seconds={details_a_sec}")
    for d in details_c:
        print(f"  Scan C detail: connected_since='{d['connected_since']}', connected_seconds={d['connected_seconds']}")

    alerts_c, _, prev_alerted_c = simulate_do_scan_alert_check(
        details_c, ips_c, set(ips), prev_alerted, alert_window  # prev_ips from scenario A
    )

    print(f"  Alerts fired: {len(alerts_c)}")
    for a in alerts_c:
        print(f"    -> ALERT: {a['ip']} (this would be a re-alert BUG)")
    test_c_pass = len(alerts_c) == 0
    print(f"  SCENARIO C: {'PASS' if test_c_pass else 'FAIL'}")

    # ===== SCENARIO D: Client reconnects (disconnect then reconnect) =====
    print("\n--- SCENARIO D: Reconnect (IP was gone, now back) ---")
    # Simulate: IP was gone (empty prev_ips), now back
    established_line_d = "  ikev2-psk[1]: ESTABLISHED 10 seconds ago, 192.168.4.4[openwrt.781998.xyz]...114.246.237.147[10.10.10.1]"
    output_d = build_realistic_output(established_line_d)
    ips_d, cnt_d, details_d = _parse_ikev2(output_d)

    alerts_d, _, _ = simulate_do_scan_alert_check(
        details_d, ips_d, set(), set(), alert_window  # empty prev_ips: "reconnect"
    )

    print(f"  Alerts fired: {len(alerts_d)} (expected: 1)")
    for a in alerts_d:
        print(f"    -> ALERT: {a['ip']}, age={a['connected_seconds']}s")
        save_event('new_client_alert', '服务器A (IKEv2)',
                   f"新客户端上线: {a['ip']}，已连接 {a['connected_seconds']} 秒",
                   notified=1)
    test_d_pass = len(alerts_d) == 1
    print(f"  SCENARIO D: {'PASS' if test_d_pass else 'FAIL'}")

    # ===== SCENARIO E: Unparseable time - no alert =====
    print("\n--- SCENARIO E: Unparseable time (no false positive) ---")
    established_line_e = "  ikev2-psk[1]: ESTABLISHED just now, 192.168.4.4[openwrt.781998.xyz]...198.51.100.10[10.10.10.3]"
    output_e = build_realistic_output(established_line_e)
    ips_e, cnt_e, details_e = _parse_ikev2(output_e)

    alerts_e, _, _ = simulate_do_scan_alert_check(
        details_e, ips_e, set(), set(), alert_window
    )

    print(f"  Alerts fired: {len(alerts_e)} (expected: 0)")
    for a in alerts_e:
        print(f"    -> ALERT: {a['ip']} (this would be a FALSE POSITIVE)")
    test_e_pass = len(alerts_e) == 0
    print(f"  SCENARIO E: {'PASS' if test_e_pass else 'FAIL'}")

    # ===== CHECK DATABASE =====
    print("\n--- Database Events ---")
    events = get_recent_events(limit=10)
    for evt in events:
        print(f"  [{evt['event_time']}] {evt['event_type']}: {evt['detail']}")

    # ===== SUMMARY =====
    print("\n" + "=" * 60)
    all_pass = test_a_pass and test_b_pass and test_c_pass and test_d_pass and test_e_pass
    print(f"  ALL SCENARIOS: {'PASS' if all_pass else 'FAIL'}")
    if all_pass:
        print("  IKEv2 alert chain is WORKING CORRECTLY.")
        print("  - New connections within window: ALERT")
        print("  - Old connections beyond window: NO ALERT")
        print("  - Same connection on 2nd scan: NO RE-ALERT")
        print("  - Reconnect after disconnect: ALERT")
        print("  - Unparseable connection time: NO FALSE POSITIVE")
    else:
        failed = []
        if not test_a_pass: failed.append('A')
        if not test_b_pass: failed.append('B')
        if not test_c_pass: failed.append('C')
        if not test_d_pass: failed.append('D')
        if not test_e_pass: failed.append('E')
        print(f"  FAILED: {failed}")
    print("=" * 60)


if __name__ == '__main__':
    main()
