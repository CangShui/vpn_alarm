"""
采集器模块 - 通过 SSH 登录远程服务器执行只读命令
支持连接复用：对每个服务器保持长连接，10 秒心跳，自动重连。
"""
import os
import re
import time
import socket
import threading
from datetime import datetime
import paramiko

DAT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- 连接缓存（线程安全） ----
_conn_cache = {}       # key -> {'client': SSHClient, 'created_at': float}
_conn_lock = threading.Lock()


class CollectError(Exception):
    pass


def _make_cache_key(server_config):
    """根据服务器配置生成稳定的缓存键"""
    host = str(server_config.get('host', '') or '')
    port = int(server_config.get('port', 22))
    username = str(server_config.get('username', 'root') or 'root')
    return (host, port, username)


def _invalidate_connection(server_config):
    """从缓存中移除并关闭指定服务器的连接"""
    key = _make_cache_key(server_config)
    with _conn_lock:
        entry = _conn_cache.pop(key, None)
    if entry:
        try:
            entry['client'].close()
        except Exception:
            pass


def _get_or_create_connection(server_config, timeout=30):
    """
    从缓存获取可用连接，若不存在或已断开则创建新连接。
    返回 paramiko.SSHClient 实例。
    注意：此函数不关闭连接，由 _invalidate_connection 负责清理。
    """
    key = _make_cache_key(server_config)

    # 先尝试复用缓存中的连接
    with _conn_lock:
        entry = _conn_cache.get(key)
    if entry:
        client = entry['client']
        try:
            transport = client.get_transport()
            if transport is not None and transport.is_active():
                return client
        except Exception:
            pass
        # 连接已失效，移除并关闭
        _invalidate_connection(server_config)

    # 创建新连接
    client = _build_client(server_config, timeout)

    # 设置 SSH 层 keepalive（每 10 秒发送心跳包，防止空闲断开）
    try:
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(10)
    except Exception:
        pass

    # 放入缓存
    with _conn_lock:
        _conn_cache[key] = {'client': client, 'created_at': time.time()}

    return client


def _build_client(server_config, timeout=30):
    """
    根据服务器配置创建并认证 SSHClient（原 collect_server 中的连接逻辑提取）。
    仅在 _get_or_create_connection 内部调用。
    """
    host = server_config.get('host', '')
    port = int(server_config.get('port', 22))
    username = server_config.get('username', 'root')
    password = server_config.get('password', '')
    ssh_key_path = server_config.get('ssh_key_path', '')
    ssh_key_passphrase = server_config.get('ssh_key_passphrase', '')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # 构建 pkey 对象（如果配置了密钥路径）
    pkey = None
    if ssh_key_path:
        try:
            key_path = os.path.expanduser(ssh_key_path)
            if not os.path.isabs(key_path):
                key_path = os.path.join(DAT_DIR, key_path)
            if os.path.exists(key_path):
                key_loaders = [
                    paramiko.RSAKey,
                    paramiko.Ed25519Key,
                    paramiko.ECDSAKey,
                    paramiko.DSSKey,
                ]
                loaded = False
                for key_cls in key_loaders:
                    try:
                        if ssh_key_passphrase:
                            pkey = key_cls.from_private_key_file(key_path, password=ssh_key_passphrase)
                        else:
                            pkey = key_cls.from_private_key_file(key_path)
                        loaded = True
                        break
                    except paramiko.PasswordRequiredException:
                        continue
                    except Exception:
                        continue
                if not loaded:
                    try:
                        if ssh_key_passphrase:
                            pkey = paramiko.RSAKey.from_private_key_file(key_path, password=ssh_key_passphrase)
                        else:
                            pkey = paramiko.RSAKey.from_private_key_file(key_path)
                    except Exception:
                        pass
        except Exception:
            # 密钥加载失败不在此处报错，留给 connect 阶段处理
            pass

    connect_kwargs = {
        'hostname': host,
        'port': port,
        'username': username,
        'timeout': timeout,
    }
    if pkey is not None:
        connect_kwargs['pkey'] = pkey
        if password:
            connect_kwargs['password'] = password
        connect_kwargs['allow_agent'] = False
        connect_kwargs['look_for_keys'] = False
    elif password:
        connect_kwargs['password'] = password
        connect_kwargs['allow_agent'] = False
        connect_kwargs['look_for_keys'] = False
    else:
        connect_kwargs['allow_agent'] = True
        connect_kwargs['look_for_keys'] = True

    client.connect(**connect_kwargs)
    return client


def _ssh_exec(client, command, timeout=30):
    """
    执行 SSH 命令。
    注意：原命令中若含 docker exec -it，因 -it 在非交互式 SSH 中会导致
    "the input device is not a TTY" 错误，已在配置中去掉 -it 参数。
    若仍需 TTY，此处分配 PTY 伪终端作为兼容路径。
    """
    if '-it' in command or '-t' in command.split():
        # docker exec -it 需要 TTY（兼容路径）
        chan = client.get_transport().open_session()
        chan.get_pty()
        chan.exec_command(command)
        chan.settimeout(timeout)
        try:
            raw_output = chan.recv(65536).decode('utf-8', errors='replace')
        except socket.timeout:
            raw_output = ''
        except OSError:
            chan.close()
            raise
        except Exception:
            raw_output = ''
        try:
            err = chan.recv_stderr(4096).decode('utf-8', errors='replace')
        except Exception:
            err = ''
        chan.close()
        if not raw_output.strip() and err.strip():
            raw_output = err
        return raw_output.strip()
    else:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
        # 设置读取超时
        stdout.channel.settimeout(timeout)
        stderr.channel.settimeout(timeout)
        try:
            raw_output = stdout.read().decode('utf-8', errors='replace').strip()
        except socket.timeout:
            raw_output = ''
        except OSError:
            raise
        except Exception:
            raw_output = ''
        try:
            err_output = stderr.read().decode('utf-8', errors='replace').strip()
        except socket.timeout:
            err_output = ''
        except OSError:
            raise
        except Exception:
            err_output = ''
        if not raw_output and err_output:
            raw_output = err_output
        return raw_output


def _build_auth_hint(server_config):
    """根据服务器配置生成认证方式提示"""
    has_password = bool(server_config.get('password', ''))
    has_key = bool(server_config.get('ssh_key_path', ''))
    if has_password and has_key:
        return '(同时配置了密码和密钥，优先使用密钥)'
    if has_key:
        return '(使用 SSH 密钥认证)'
    if has_password:
        return '(使用密码认证)'
    return '(未配置密码或密钥)'


def collect_server(server_config, timeout=30):
    """
    通过 SSH 连接服务器，执行只读命令并返回结果。
    支持密码认证和 SSH 密钥认证，复用长连接（心跳 10s）。
    返回 dict: {status, online_count, client_ips, client_details, raw_output, error_message, duration_ms}
    """
    host = server_config.get('host', '')
    port = int(server_config.get('port', 22))
    command = server_config.get('command', '')
    server_type = server_config.get('type', 'unknown')

    t0 = time.time()

    # 获取或创建长连接
    try:
        client = _get_or_create_connection(server_config, timeout)
    except paramiko.AuthenticationException as e:
        duration_ms = int((time.time() - t0) * 1000)
        hint = _build_auth_hint(server_config)
        err_msg = f'认证失败: {str(e)}\n可能原因：① 密码错误 ② 目标服务器禁止密码登录(需使用SSH密钥) ③ 密钥权限不正确(应为0600) ④ 密钥类型不受支持\n当前认证方式: {hint}'
        return {
            'status': 'auth_failed',
            'online_count': 0,
            'client_ips': [],
            'client_details': [],
            'raw_output': '',
            'error_message': err_msg,
            'duration_ms': duration_ms
        }
    except Exception as e:
        duration_ms = int((time.time() - t0) * 1000)
        err_msg = str(e)
        if 'timeout' in err_msg.lower() or 'timed out' in err_msg.lower():
            err_msg = f'连接超时: 无法在 {timeout} 秒内连接到 {host}:{port}，请检查网络和防火墙'
        elif 'refused' in err_msg.lower() or 'connection refused' in err_msg.lower():
            err_msg = f'连接被拒绝: {host}:{port} SSH 服务未运行或端口被防火墙拦截'
        elif 'name or service not known' in err_msg.lower() or 'getaddrinfo' in err_msg.lower():
            err_msg = f'无法解析主机名: {host}，请检查主机地址是否正确'
        return {
            'status': 'error',
            'online_count': 0,
            'client_ips': [],
            'client_details': [],
            'raw_output': '',
            'error_message': f'连接失败: {err_msg}',
            'duration_ms': duration_ms
        }

    # 执行命令（使用缓存的长连接），失败时自动重试一次（剔除旧连接后新建）
    raw_output = None
    last_error = None
    last_is_ssh_exc = False
    for attempt in (1, 2):
        try:
            raw_output = _ssh_exec(client, command, timeout)
            break
        except paramiko.SSHException as e:
            # SSH 协议级异常 → 连接大概率已损坏，剔除缓存后重试
            last_error = e
            last_is_ssh_exc = True
            _invalidate_connection(server_config)
            if attempt == 1:
                try:
                    client = _get_or_create_connection(server_config, timeout)
                except Exception:
                    pass
            continue
        except Exception as e:
            last_error = e
            last_is_ssh_exc = False
            # 执行失败时检查连接是否存活；不论 is_active 是否 True
            # 都剔除缓存（因为实际 I/O 已失败），然后重试一次
            try:
                _invalidate_connection(server_config)
            except Exception:
                pass
            if attempt == 1:
                try:
                    client = _get_or_create_connection(server_config, timeout)
                except Exception:
                    pass
            continue

    if raw_output is None:
        duration_ms = int((time.time() - t0) * 1000)
        err_msg = str(last_error) if last_error else '未知错误'
        if last_is_ssh_exc:
            return {
                'status': 'error',
                'online_count': 0,
                'client_ips': [],
                'client_details': [],
                'raw_output': '',
                'error_message': f'SSH 会话异常: {err_msg}',
                'duration_ms': duration_ms
            }
        else:
            return {
                'status': 'error',
                'online_count': 0,
                'client_ips': [],
                'client_details': [],
                'raw_output': '',
                'error_message': f'命令执行失败: {err_msg}',
                'duration_ms': duration_ms
            }

    # 解析客户端 IP（根据服务器类型）
    if server_type == 'ikev2':
        client_ips, online_count, client_details = _parse_ikev2(raw_output)
    elif server_type == 'openvpn':
        client_ips, online_count, client_details = _parse_openvpn(raw_output)
    else:
        client_ips, online_count, client_details = _parse_generic(raw_output)

    duration_ms = int((time.time() - t0) * 1000)

    return {
        'status': 'success',
        'online_count': online_count,
        'client_ips': client_ips,
        'client_details': client_details,
        'raw_output': raw_output,
        'error_message': '',
        'duration_ms': duration_ms
    }


def _parse_duration_to_seconds(text):
    total = 0
    patterns = [
        (r'(\d+)\s+days?', 86400),
        (r'(\d+)\s+hours?', 3600),
        (r'(\d+)\s+minutes?', 60),
        (r'(\d+)\s+seconds?', 1)
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            total += int(match.group(1)) * multiplier
    return total if total > 0 else None


def _parse_datetime_string(value):
    if not value:
        return None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%a %b %d %H:%M:%S %Y'):
        try:
            return datetime.strptime(value.strip(), fmt)
        except Exception:
            continue
    return None


def _build_client_detail(ip, connected_since=None, connected_seconds=None, source=''):
    return {
        'ip': ip,
        'connected_since': connected_since or '',
        'connected_seconds': connected_seconds,
        'source': source
    }


def _is_private_172(ip):
    """检查 IP 是否落在 172.16.0.0/12 私网段（172.16.x.x - 172.31.x.x）。"""
    try:
        parts = ip.split('.')
        if len(parts) == 4 and parts[0] == '172':
            second = int(parts[1])
            return 16 <= second <= 31
    except (ValueError, IndexError):
        pass
    return False


def _parse_ikev2(output):
    """
    解析 strongSwan ipsec statusall 输出，提取客户端 IP。
    实际输出示例：
      Security Associations (0 up, 0 connecting):
        none
    或带连接时：
      Security Associations (1 up, 0 connecting):
        ikev2-psk[1]: ESTABLISHED 2 minutes ago, 192.168.4.4[id]...114.246.237.147[10.10.10.1]
        ikev2-psk{1}:  INSTALLED, TUNNEL, reqid 1, ...
          10.10.10.0/24 === 0.0.0.0/0

    ESTABLISHED 行格式: <conn>[I]: ESTABLISHED <time> ago, <local_ip>[<local_id>]...<remote_ip>[<remote_id>]
    其中 remote_ip 是客户端的公网 IP，[<remote_id>] 中可能包含虚拟 IP（如 10.10.10.1）。
    需要用排除列表过滤掉内部 IP，才能正确提取客户端公网 IP 并关联 connected_seconds。
    """
    from datetime import datetime as dt_module

    client_ips = set()
    client_details = []
    online_count = 0

    # 排除非客户端 IP（服务器自身、Docker 网桥、VPN 地址池等）
    # 172.16.0.0/12 整段由 _is_private_172() 统一过滤
    exclude_starts = ['0.0.0.', '255.255.', '127.0.', '192.168.4.', '192.168.0.',
                      '10.10.10.']
    exclude_exact = {'0.0.0.0', '255.255.255.255', '127.0.0.1'}

    # 解析 "Security Associations (N up, M connecting):" 中的 N
    sa_match = re.search(r'Security Associations\s*\((\d+)\s+up', output)
    if sa_match:
        online_count = int(sa_match.group(1))

    if online_count == 0:
        return [], 0, []

    seen_detail_ips = set()
    now = dt_module.now()
    ip_pattern = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')

    for line in output.split('\n'):
        line = line.strip()
        if 'ESTABLISHED' not in line:
            continue
        all_ips_in_line = ip_pattern.findall(line)
        if not all_ips_in_line:
            continue

        duration_seconds = _parse_duration_to_seconds(line)

        # 从 ESTABLISHED 行提取客户端公网 IP：
        # 过滤掉服务器自身和内部 IP，取最后一个剩余 IP 作为客户端公网 IP
        # 如果全部被排除（纯内网场景），回退到最后一个 IP
        candidate_ips = [ip for ip in all_ips_in_line
                         if ip not in exclude_exact
                         and not any(ip.startswith(p) for p in exclude_starts)
                         and not _is_private_172(ip)]
        if candidate_ips:
            client_ip = candidate_ips[-1]
        else:
            # 整行 IP 均在排除范围内（如纯 172.16/12 私网），跳过该行
            continue

        # 计算稳定的 connected_since 时间戳（用于去重，避免每次扫描 marker 变化）
        connected_since = ''
        if duration_seconds is not None and duration_seconds >= 0:
            try:
                connected_since = (now - dt_module.resolution * duration_seconds * 1000000).strftime('%Y-%m-%d %H:%M:%S')
            except Exception:
                connected_since = ''

        client_ips.add(client_ip)
        if client_ip not in seen_detail_ips:
            client_details.append(_build_client_detail(
                client_ip,
                connected_since=connected_since,
                connected_seconds=duration_seconds,
                source='ikev2'
            ))
            seen_detail_ips.add(client_ip)

    # 提取所有 IP 地址
    all_ips = ip_pattern.findall(output)

    for ip in all_ips:
        if ip in exclude_exact:
            continue
        if any(ip.startswith(p) for p in exclude_starts):
            continue
        if _is_private_172(ip):
            continue
        client_ips.add(ip)

    for ip in sorted(client_ips):
        if ip not in seen_detail_ips:
            client_details.append(_build_client_detail(ip, source='ikev2'))

    return list(client_ips), online_count, client_details


def _parse_openvpn(output):
    """
    解析 OpenVPN 状态日志（实际格式）：
      OpenVPN CLIENT LIST
      Updated,2026-06-29 01:08:18
      Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since
      client1,114.246.237.147:35648,29761,181928,2026-06-29 01:07:17
      ROUTING TABLE
      Virtual Address,Common Name,Real Address,Last Ref
      10.8.0.2,client1,114.246.237.147:35648,2026-06-29 01:08:12
      GLOBAL STATS
      ...
      END
    """
    client_ips = set()
    client_details = []
    online_count = 0
    in_client_section = False
    seen_detail_ips = set()
    updated_at = None

    for line in output.split('\n'):
        line = line.strip()
        if not line:
            continue

        # 跳过标题行和分隔行
        if line.startswith('OpenVPN') or line == 'END':
            continue
        if line.startswith('Updated'):
            parts = line.split(',', 1)
            updated_at = _parse_datetime_string(parts[1] if len(parts) > 1 else '')
            continue
        if line == 'Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since':
            in_client_section = True
            continue
        if line.startswith('ROUTING TABLE') or line.startswith('GLOBAL STATS'):
            in_client_section = False
            continue
        if line.startswith('Virtual Address') or line.startswith('Max bcast'):
            continue

        if in_client_section:
            parts = line.split(',')
            if len(parts) >= 2:
                # parts[1] is "Real Address" like "114.246.237.147:35648"
                addr_port = parts[1].strip()
                if ':' in addr_port:
                    addr = addr_port.split(':')[0]
                else:
                    addr = addr_port
                if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', addr):
                    connected_since = parts[4].strip() if len(parts) >= 5 else ''
                    connected_since_dt = _parse_datetime_string(connected_since)
                    connected_seconds = None
                    if updated_at and connected_since_dt:
                        connected_seconds = max(0, int((updated_at - connected_since_dt).total_seconds()))
                    client_ips.add(addr)
                    if addr not in seen_detail_ips:
                        client_details.append(_build_client_detail(
                            addr,
                            connected_since=connected_since,
                            connected_seconds=connected_seconds,
                            source='openvpn'
                        ))
                        seen_detail_ips.add(addr)
                    online_count += 1

    return list(client_ips), online_count, client_details


def _parse_generic(output):
    """通用 IP 提取"""
    ip_pattern = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')
    all_ips = ip_pattern.findall(output)
    exclude_patterns = {'0.0.0.0', '255.255.255.255', '127.0.0.1'}
    client_ips = [ip for ip in all_ips if ip not in exclude_patterns]
    client_details = [_build_client_detail(ip, source='generic') for ip in client_ips]
    return client_ips, len(client_ips), client_details
