"""
VPN 在线监控系统 - 主应用入口
Flask Web + APScheduler 定时采集 + SQLite 存储
"""
import json
import sys
import os
import time
import threading
from datetime import datetime

from flask import Flask, render_template, request, jsonify, redirect, url_for

# 将当前目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, save_scan_record, save_event, get_latest_scan_per_server, \
    get_recent_scans, get_recent_events, get_known_ips, db_ping, get_db_stats, \
    get_scans_paginated, get_events_paginated, prune_all
from collector import collect_server
from geo_resolver import init_resolvers, resolve_ip, resolve_ips, get_resolver_status
from notifier import send_telegram, send_webhook
from config_manager import load_config, save_config, get_safe_config

from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ---- 全局状态 ----
last_client_ips = {}   # server_name -> set of IPs
last_online_counts = {}  # server_name -> int
alerted_client_keys = {}  # server_name -> set of (ip, marker)
_collect_lock = threading.Lock()
scheduler = None
_last_scan_start_time = None   # datetime
_last_scan_end_time = None     # datetime

# ---- 自愈 watchdog 全局状态 ----
_watchdog_first_unhealthy_time = None  # datetime: 首次检测到关键 unhealthy 的时间
_watchdog_consecutive_unhealthy_count = 0  # 连续关键 unhealthy 次数
_watchdog_enabled = True  # 控制 watchdog 线程启停（测试用）

# 会导致进程主动退出的关键健康检查项
CRITICAL_CHECKS = {'database', 'scheduler', 'scan_job', 'last_scan', 'status_page', 'api_status'}


def _normalize_client_details(raw_details):
    normalized = []
    for item in raw_details or []:
        if not isinstance(item, dict):
            continue
        ip = str(item.get('ip') or '').strip()
        if not ip:
            continue
        seconds = item.get('connected_seconds')
        try:
            seconds = int(seconds) if seconds is not None else None
        except Exception:
            seconds = None
        normalized.append({
            'ip': ip,
            'connected_since': str(item.get('connected_since') or '').strip(),
            'connected_seconds': seconds,
            'source': str(item.get('source') or '').strip()
        })
    return normalized


def _get_session_marker(detail):
    return detail.get('connected_since') or str(detail.get('connected_seconds'))


def _get_alertable_sessions(client_details, window_seconds):
    sessions = []
    for detail in _normalize_client_details(client_details):
        seconds = detail.get('connected_seconds')
        if seconds is None or seconds < 0:
            continue
        if seconds <= window_seconds:
            sessions.append(detail)
    return sessions


def _format_connection_age(seconds):
    if seconds is None:
        return '连接时间未知'
    return f'已连接 {seconds} 秒'


def _format_ip_location(ip):
    """将 resolve_ip 结果转换为通知用的地点文本。
    优先组合 城市 / 地区 / 国家 中非空非 '-' 的字段，全部无效时返回 '未知地区'。"""
    try:
        geo = resolve_ip(ip)
    except Exception:
        return '未知地区'
    parts = []
    for key in ('city', 'region', 'country'):
        val = str(geo.get(key, '')).strip()
        if val and val != '-':
            parts.append(val)
    return ' | '.join(parts) if parts else '未知地区'


def notify_event(event_type, detail, server_name=''):
    """按配置发送通知"""
    cfg = load_config()
    notif = cfg.get('notifications', {})
    messages = []

    # Telegram
    tg = notif.get('telegram', {})
    if tg.get('enabled'):
        msg = f"<b>VPN 监控告警</b>\n类型: {event_type}\n服务器: {server_name}\n时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n详情: {detail}"
        ok, info = send_telegram(tg.get('token'), tg.get('chat_id'), msg)
        messages.append(f"Telegram: {info}")
        print(f"[NOTIFY] Telegram | 事件: {event_type} | 服务器: {server_name} | {'成功' if ok else '失败'}: {info}", flush=True)

    # Webhook
    wh = notif.get('webhook', {})
    if wh.get('enabled'):
        msg = f"[{event_type}] {server_name}: {detail}"
        ok, info = send_webhook(wh, msg)
        messages.append(f"Webhook: {info}")
        print(f"[NOTIFY] Webhook | 事件: {event_type} | 服务器: {server_name} | {'成功' if ok else '失败'}: {info}", flush=True)

    return messages


def do_scan():
    """执行一次完整采集"""
    global _last_scan_start_time, _last_scan_end_time
    _last_scan_start_time = datetime.now()

    cfg = load_config()
    servers = cfg.get('servers', [])
    alert_window = max(1, int(cfg.get('connection_alert_window', 300)))
    scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    results = []

    for srv in servers:
        if not srv.get('enabled', True):
            continue

        srv_name = srv.get('name', f"{srv['host']}:{srv['port']}")
        print(f"[{datetime.now()}] 采集: {srv_name} ...", flush=True)

        # 执行 SSH 采集
        result = collect_server(srv)
        results.append((srv, result))

        # 保存扫描记录
        save_scan_record(
            server_name=srv_name,
            server_type=srv.get('type', ''),
            scan_time=scan_time,
            online_count=result['online_count'],
            client_ips=result['client_ips'],
            client_details=result.get('client_details', []),
            raw_output=result['raw_output'],
            status=result['status'],
            error_message=result['error_message'],
            duration_ms=result['duration_ms']
        )

        # ---- 事件检测 ----
        with _collect_lock:
            prev_ips = last_client_ips.get(srv_name, set())
            prev_count = last_online_counts.get(srv_name)
            prev_alerted_keys = alerted_client_keys.get(srv_name, set())

            # 1. 服务不可达
            if result['status'] != 'success':
                detail = f"服务不可达: {result['error_message']}"
                print(f"  [EVENT] {detail}", flush=True)
                notify_event('服务不可达', detail, srv_name)

            else:
                new_ips = set(result['client_ips'])
                new_count = result['online_count']
                new_ip_set = new_ips - prev_ips
                client_details = _normalize_client_details(result.get('client_details', []))
                alertable_sessions = _get_alertable_sessions(client_details, alert_window)
                current_session_keys = {(detail['ip'], _get_session_marker(detail)) for detail in client_details}

                for detail_item in alertable_sessions:
                    session_key = (detail_item['ip'], _get_session_marker(detail_item))
                    if detail_item['ip'] not in new_ip_set and session_key in prev_alerted_keys:
                        continue
                    if session_key in prev_alerted_keys:
                        continue
                    location = _format_ip_location(detail_item['ip'])
                    connected_since = str(detail_item.get('connected_since', '')).strip()
                    structured = json.dumps({
                        'ip': detail_item['ip'],
                        'connected_since': connected_since,
                        'location': location
                    }, ensure_ascii=False)
                    detail = f"新客户端上线: {detail_item['ip']}（{location}），{_format_connection_age(detail_item.get('connected_seconds'))}|||{structured}"
                    print(f"  [EVENT] {detail}", flush=True)
                    save_event('new_client_alert', srv_name, detail, notified=1)
                    notify_event('新客户端上线', detail, srv_name)

                # 更新缓存
                last_client_ips[srv_name] = new_ips
                last_online_counts[srv_name] = new_count
                alerted_client_keys[srv_name] = prev_alerted_keys.intersection(current_session_keys)
                alerted_client_keys[srv_name].update({
                    (detail['ip'], _get_session_marker(detail)) for detail in alertable_sessions
                })

            print(f"  -> 状态={result['status']}, 在线={result['online_count']}, "
                  f"IPs={result['client_ips']}, 耗时={result['duration_ms']}ms", flush=True)

    _last_scan_end_time = datetime.now()
    return results


def on_scan_interval_changed():
    """扫描间隔变更后重新调度"""
    global scheduler
    cfg = load_config()
    interval = int(cfg.get('scan_interval', 60))
    if scheduler:
        try:
            scheduler.remove_job('periodic_scan')
        except Exception:
            pass
        scheduler.add_job(
            do_scan,
            'interval',
            seconds=interval,
            id='periodic_scan',
            replace_existing=True,
            max_instances=1
        )
        print(f"[SCHEDULER] 扫描间隔已更新为 {interval} 秒", flush=True)


def health_check():
    """健康检查：返回所有子检查的状态和详细信息"""
    checks = {}
    healthy = True

    # 1. Flask 应用可响应 — 此函数能执行即证明 Flask 可响应
    checks['flask'] = {'status': 'ok'}

    # 2. 数据库可访问
    try:
        db_ok = db_ping()
        checks['database'] = {'status': 'ok' if db_ok else 'fail'}
        if not db_ok:
            healthy = False
    except Exception as e:
        checks['database'] = {'status': 'fail', 'error': str(e)}
        healthy = False

    # 3. APScheduler 已启动
    try:
        if scheduler is not None and scheduler.running:
            checks['scheduler'] = {'status': 'ok'}
        else:
            checks['scheduler'] = {'status': 'fail', 'error': '调度器未运行'}
            healthy = False
    except Exception as e:
        checks['scheduler'] = {'status': 'fail', 'error': str(e)}
        healthy = False

    # 4. 周期扫描任务存在
    try:
        if scheduler is not None:
            job = scheduler.get_job('periodic_scan')
            if job is not None:
                checks['scan_job'] = {'status': 'ok', 'next_run': str(job.next_run_time) if job.next_run_time else None}
            else:
                checks['scan_job'] = {'status': 'fail', 'error': 'periodic_scan 任务不存在'}
                healthy = False
        else:
            checks['scan_job'] = {'status': 'fail', 'error': '调度器未初始化'}
            healthy = False
    except Exception as e:
        checks['scan_job'] = {'status': 'fail', 'error': str(e)}
        healthy = False

    # 5. 最近一次扫描时间未超时
    cfg = load_config()
    scan_interval = max(1, int(cfg.get('scan_interval', 60)))
    # 阈值策略：3 倍扫描间隔 + 60 秒缓冲（保守合理）
    threshold = scan_interval * 3 + 60

    last_time = _last_scan_end_time or _last_scan_start_time
    if last_time is not None:
        elapsed = (datetime.now() - last_time).total_seconds()
        last_scan_str = last_time.strftime('%Y-%m-%d %H:%M:%S')
        if elapsed <= threshold:
            checks['last_scan'] = {
                'status': 'ok',
                'last_scan_time': last_scan_str,
                'elapsed_seconds': round(elapsed, 1),
                'scan_interval': scan_interval,
                'threshold_seconds': threshold
            }
        else:
            checks['last_scan'] = {
                'status': 'fail',
                'last_scan_time': last_scan_str,
                'elapsed_seconds': round(elapsed, 1),
                'scan_interval': scan_interval,
                'threshold_seconds': threshold,
                'error': f'上次扫描已过去 {elapsed:.0f} 秒，超过阈值 {threshold} 秒'
            }
            healthy = False
    else:
        checks['last_scan'] = {
            'status': 'fail',
            'last_scan_time': None,
            'elapsed_seconds': None,
            'scan_interval': scan_interval,
            'threshold_seconds': threshold,
            'error': '尚未执行过扫描'
        }
        healthy = False

    # 6. 用户路径检查：/status 页面可渲染
    try:
        with app.test_client() as client:
            resp = client.get('/status')
            if resp.status_code == 200:
                checks['status_page'] = {'status': 'ok', 'type': 'user_path'}
            else:
                checks['status_page'] = {'status': 'fail', 'type': 'user_path',
                                         'error': f'/status 返回 HTTP {resp.status_code}'}
                healthy = False
    except Exception as e:
        checks['status_page'] = {'status': 'fail', 'type': 'user_path', 'error': str(e)}
        healthy = False

    # 7. 用户路径检查：/api/status 可返回正确数据
    try:
        with app.test_client() as client:
            resp = client.get('/api/status')
            if resp.status_code == 200:
                data = resp.get_json()
                if data and data.get('ok'):
                    checks['api_status'] = {'status': 'ok', 'type': 'user_path'}
                else:
                    checks['api_status'] = {'status': 'fail', 'type': 'user_path',
                                            'error': f'/api/status 返回异常数据: {data}'}
                    healthy = False
            else:
                checks['api_status'] = {'status': 'fail', 'type': 'user_path',
                                        'error': f'/api/status 返回 HTTP {resp.status_code}'}
                healthy = False
    except Exception as e:
        checks['api_status'] = {'status': 'fail', 'type': 'user_path', 'error': str(e)}
        healthy = False

    # 为已有内部检查项补充 type 标记
    _internal_check_names = {'flask', 'database', 'scheduler', 'scan_job', 'last_scan'}
    for check_name in checks:
        if 'type' not in checks[check_name]:
            checks[check_name]['type'] = 'internal' if check_name in _internal_check_names else 'user_path'

    return {
        'status': 'healthy' if healthy else 'unhealthy',
        'checks': checks,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }, healthy


def _get_watchdog_threshold():
    """获取自愈 watchdog 的持续 unhealthy 阈值（秒）。
    采用保守策略：max(300 秒, 5 倍扫描间隔)"""
    try:
        cfg = load_config()
        scan_interval = max(1, int(cfg.get('scan_interval', 60)))
    except Exception:
        scan_interval = 60
    return max(300, scan_interval * 5)


def _watchdog_loop():
    """后台 watchdog 线程：周期性调用内部健康检查，持续关键 unhealthy 超阈值时主动退出。
    关键故障类型：数据库不可访问、调度器未运行、周期扫描任务丢失、最近扫描超时、/status 页面渲染异常、/api/status 接口异常。
    退出前输出明确日志，使用 os._exit(1) 确保非 0 退出码让 Docker 重启容器。"""
    global _watchdog_first_unhealthy_time, _watchdog_consecutive_unhealthy_count

    # 首次延迟：给系统足够的启动缓冲时间
    time.sleep(60)

    while _watchdog_enabled:
        try:
            check_interval = max(15, int(load_config().get('scan_interval', 60)) // 2)
        except Exception:
            check_interval = 30

        try:
            result, healthy = health_check()
        except Exception as e:
            print(f"[WATCHDOG] 健康检查执行异常: {e}", flush=True)
            time.sleep(check_interval)
            continue

        # 判断是否存在关键故障
        critical_fails = []
        for check_name in CRITICAL_CHECKS:
            check_info = result.get('checks', {}).get(check_name)
            if check_info and check_info.get('status') == 'fail':
                critical_fails.append(check_name)

        if critical_fails:
            now = datetime.now()
            if _watchdog_first_unhealthy_time is None:
                _watchdog_first_unhealthy_time = now
            _watchdog_consecutive_unhealthy_count += 1

            duration = (now - _watchdog_first_unhealthy_time).total_seconds()
            threshold = _get_watchdog_threshold()

            print(f"[WATCHDOG] 关键 unhealthy 持续 {duration:.0f}s / 阈值 {threshold}s "
                  f"(连续 {_watchdog_consecutive_unhealthy_count} 次), "
                  f"失败检查: {critical_fails}", flush=True)

            if duration >= threshold:
                print(f"[WATCHDOG] 关键 unhealthy 已持续 {duration:.0f}s，超过阈值 {threshold}s，主动退出进程", flush=True)
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(1)
        else:
            # 健康恢复，清零故障累计
            if _watchdog_consecutive_unhealthy_count > 0:
                print(f"[WATCHDOG] 健康恢复，重置故障累计 "
                      f"(之前连续 {_watchdog_consecutive_unhealthy_count} 次 unhealthy)", flush=True)
            _watchdog_first_unhealthy_time = None
            _watchdog_consecutive_unhealthy_count = 0

        time.sleep(check_interval)


# ==================== Flask 路由 ====================

@app.route('/healthz')
def api_healthz():
    """健康检查接口：返回结构化 JSON，unhealthy 时返回 HTTP 503"""
    result, healthy = health_check()
    status_code = 200 if healthy else 503
    return jsonify(result), status_code


@app.route('/')
def index():
    return redirect(url_for('status_page'))


@app.route('/status')
def status_page():
    """当前状态页 — 前端通过 AJAX 自动刷新"""
    cfg = load_config()
    return render_template('status.html',
                           status_refresh_interval=max(3, int(cfg.get('status_refresh_interval', 5))),
                           now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@app.route('/history')
def history_page():
    """历史记录页 — 前端通过 AJAX 按标签页分页加载"""
    return render_template('history.html',
                           now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@app.route('/api/scans')
def api_scans():
    """API: 分页查询扫描记录"""
    page = max(1, int(request.args.get('page', 1)))
    page_size = max(1, min(200, int(request.args.get('page_size', 50))))
    items, total, clamped_page = get_scans_paginated(page=page, page_size=page_size)
    return jsonify({
        'ok': True,
        'items': items,
        'total': total,
        'page': clamped_page,
        'page_size': page_size
    })


@app.route('/api/events')
def api_events():
    """API: 分页查询事件日志"""
    page = max(1, int(request.args.get('page', 1)))
    page_size = max(1, min(200, int(request.args.get('page_size', 50))))
    items, total, clamped_page = get_events_paginated(page=page, page_size=page_size)
    return jsonify({
        'ok': True,
        'items': items,
        'total': total,
        'page': clamped_page,
        'page_size': page_size
    })


@app.route('/config')
def config_page():
    """系统配置页"""
    safe_cfg = get_safe_config()
    return render_template('config.html', config=safe_cfg,
                           now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


@app.route('/api/config', methods=['GET'])
def api_get_config():
    """API: 获取完整配置（含明文密码，仅 API 用）"""
    cfg = load_config()
    return jsonify(cfg)


@app.route('/api/config', methods=['POST'])
def api_save_config():
    """API: 保存配置"""
    import traceback as _tb
    try:
        new_config = request.get_json(force=True)
        if not new_config:
            return jsonify({'ok': False, 'error': '请求体为空'}), 400
        ok = save_config(new_config)
        if ok:
            # 保存后立刻按新保留条数裁剪历史数据
            prune_result = prune_all()
            if prune_result['scan_deleted'] > 0 or prune_result['event_deleted'] > 0:
                print(f"[CONFIG] 保存后裁剪: 扫描-{prune_result['scan_deleted']}条, 事件-{prune_result['event_deleted']}条", flush=True)
            # 更新调度间隔
            print("[DEBUG] save ok, calling on_scan_interval_changed...", flush=True)
            on_scan_interval_changed()
            print("[DEBUG] on_scan_interval_changed done, calling init_resolvers...", flush=True)
            # 重新初始化解析器（文件路径可能已变更）
            init_resolvers()
            print("[DEBUG] init_resolvers done", flush=True)
            return jsonify({'ok': True, 'message': '配置已保存'})
        else:
            return jsonify({'ok': False, 'error': '写入文件失败'}), 500
    except Exception as e:
        print(f"[ERROR] api_save_config exception: {_tb.format_exc()}", flush=True)
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/scan', methods=['POST'])
def api_trigger_scan():
    """API: 手动触发扫描"""
    try:
        results = do_scan()
        return jsonify({
            'ok': True,
            'results': [{
                'server': srv.get('name', ''),
                'status': res['status'],
                'online_count': res['online_count'],
                'client_ips': res['client_ips'],
                'error_message': res['error_message'],
                'duration_ms': res['duration_ms']
            } for srv, res in results]
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/status')
def api_status():
    """API: 当前状态（仅展示 config.json 中存在且启用的服务器）"""
    cfg = load_config()
    # 收集当前配置中启用服务器的名称集合
    enabled_names = set()
    for srv in cfg.get('servers', []):
        if srv.get('enabled', True):
            enabled_names.add(srv.get('name', ''))

    latest = get_latest_scan_per_server()
    result = []
    for rec in latest:
        # 只展示配置中真实存在且启用的服务器，过滤掉测试残留等
        if rec['server_name'] not in enabled_names:
            continue
        try:
            ips = json.loads(rec['client_ips']) if isinstance(rec['client_ips'], str) else rec['client_ips']
        except Exception:
            ips = []
        try:
            client_details = json.loads(rec.get('client_details') or '[]') if isinstance(rec.get('client_details'), str) else (rec.get('client_details') or [])
        except Exception:
            client_details = []
        geo_data = resolve_ips(ips)
        result.append({
            'server': rec['server_name'],
            'type': rec['server_type'],
            'scan_time': rec['scan_time'],
            'online_count': rec['online_count'],
            'client_ips': ips,
            'client_details': _normalize_client_details(client_details),
            'geo_data': geo_data,
            'status': rec['status'],
            'error_message': rec['error_message'],
            'duration_ms': rec['duration_ms']
        })
    return jsonify({
        'ok': True,
        'servers': result,
        'resolver_status': get_resolver_status(),
        'db_stats': get_db_stats(),
        'refresh_interval': max(3, int(cfg.get('status_refresh_interval', 5))),
        'now': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.route('/api/test-notification', methods=['POST'])
def api_test_notification():
    """API: 测试通知发送"""
    cfg = load_config()
    notif = cfg.get('notifications', {})
    test_msg = "这是一条 VPN 监控系统测试通知。如果您收到此消息，说明通知渠道配置正确。"
    results = {}

    tg = notif.get('telegram', {})
    if tg.get('enabled'):
        ok, info = send_telegram(tg.get('token'), tg.get('chat_id'), test_msg)
        results['telegram'] = {'ok': ok, 'message': info}
        print(f"[NOTIFY-TEST] Telegram | {'成功' if ok else '失败'}: {info}", flush=True)
    else:
        results['telegram'] = {'ok': False, 'message': 'Telegram 通知未启用'}
        print(f"[NOTIFY-TEST] Telegram | 跳过: 通知未启用", flush=True)

    wh = notif.get('webhook', {})
    if wh.get('enabled'):
        ok, info = send_webhook(wh, test_msg)
        results['webhook'] = {'ok': ok, 'message': info}
        print(f"[NOTIFY-TEST] Webhook | {'成功' if ok else '失败'}: {info}", flush=True)
    else:
        results['webhook'] = {'ok': False, 'message': 'Webhook 通知未启用'}
        print(f"[NOTIFY-TEST] Webhook | 跳过: 通知未启用", flush=True)

    return jsonify({'ok': True, 'results': results})


@app.route('/api/resolver-status')
def api_resolver_status():
    """API: 解析器状态"""
    return jsonify({'ok': True, 'resolvers': get_resolver_status()})


# ==================== 启动 ====================

def main():
    global scheduler

    # 将 stdout / stderr 重定向到日志文件，配合 docker compose 挂载实现持久化
    log_dir = '/app/logs'
    os.makedirs(log_dir, exist_ok=True)
    sys.stdout = open(os.path.join(log_dir, 'stdout.log'), 'a', buffering=1)
    sys.stderr = open(os.path.join(log_dir, 'stderr.log'), 'a', buffering=1)

    print("=" * 60)
    print("  VPN 在线监控系统 v1.0")
    print("=" * 60)

    # 初始化
    print("[INIT] 初始化数据库...")
    init_db()

    print("[INIT] 初始化城市解析器...")
    init_resolvers()
    rs = get_resolver_status()
    for r in rs:
        print(f"  - {r['name']}: available={r['available']}, {r.get('error', '')}")

    # 首次采集
    print("[INIT] 执行首次采集...")
    do_scan()

    # 启动调度器
    cfg = load_config()
    interval = int(cfg.get('scan_interval', 60))
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        do_scan,
        'interval',
        seconds=interval,
        id='periodic_scan',
        replace_existing=True,
        max_instances=1
    )
    scheduler.start()
    print(f"[SCHEDULER] 定时采集已启动，间隔 {interval} 秒")

    # 启动自愈 watchdog 后台线程
    watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True, name='watchdog')
    watchdog_thread.start()
    print(f"[WATCHDOG] 自愈 watchdog 已启动，阈值 {_get_watchdog_threshold()}s (max(300, 5×{interval}))")

    # 启动 Flask
    print("[WEB] 启动 Web 服务 http://127.0.0.1:5000")
    print("  页面: /status | /history | /config")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
