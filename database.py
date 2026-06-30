"""
数据库模块 - SQLite 持久化存储
"""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'vpn_alarm.db')


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库表（确保父目录存在）"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS scan_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_name TEXT NOT NULL,
            server_type TEXT,
            scan_time TEXT NOT NULL,
            online_count INTEGER DEFAULT 0,
            client_ips TEXT DEFAULT '[]',
            client_details TEXT DEFAULT '[]',
            raw_output TEXT DEFAULT '',
            status TEXT DEFAULT 'success',
            error_message TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_time TEXT NOT NULL,
            event_type TEXT NOT NULL,
            server_name TEXT,
            detail TEXT,
            notified INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS config_store (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT
        );
    ''')
    columns = [row['name'] for row in conn.execute('PRAGMA table_info(scan_records)').fetchall()]
    if 'client_details' not in columns:
        conn.execute("ALTER TABLE scan_records ADD COLUMN client_details TEXT DEFAULT '[]'")
    conn.commit()
    conn.close()


def _prune_scan_records(conn, max_retention):
    """按最大保留条数裁剪扫描记录（保留最新的）"""
    if not max_retention or max_retention <= 0:
        return
    count_row = conn.execute('SELECT COUNT(*) as c FROM scan_records').fetchone()
    total = count_row['c']
    if total > max_retention:
        delete_count = total - max_retention
        # 删除最旧的记录，保留最新的 max_retention 条
        conn.execute(
            'DELETE FROM scan_records WHERE id NOT IN (SELECT id FROM scan_records ORDER BY id DESC LIMIT ?)',
            (max_retention,)
        )
        print(f"[DB] 裁剪扫描记录：删除 {delete_count} 条，保留 {max_retention} 条", flush=True)


def _prune_events(conn, max_retention):
    """按最大保留条数裁剪事件日志（保留最新的）"""
    if not max_retention or max_retention <= 0:
        return
    count_row = conn.execute('SELECT COUNT(*) as c FROM events').fetchone()
    total = count_row['c']
    if total > max_retention:
        delete_count = total - max_retention
        conn.execute(
            'DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)',
            (max_retention,)
        )
        print(f"[DB] 裁剪事件日志：删除 {delete_count} 条，保留 {max_retention} 条", flush=True)


def save_scan_record(server_name, server_type, scan_time, online_count,
                     client_ips, client_details, raw_output, status, error_message, duration_ms):
    conn = get_connection()
    conn.execute('''
        INSERT INTO scan_records (server_name, server_type, scan_time, online_count,
                                  client_ips, client_details, raw_output, status, error_message, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (server_name, server_type, scan_time, online_count,
          json.dumps(client_ips), json.dumps(client_details), raw_output, status, error_message, duration_ms))
    # 自动裁剪：按 scan_history_retention 上限删除旧记录
    from config_manager import load_config
    cfg = load_config()
    max_retention = int(cfg.get('scan_history_retention', 10000) or 10000)
    _prune_scan_records(conn, max_retention)
    conn.commit()
    conn.close()


def save_event(event_type, server_name, detail, notified=0):
    conn = get_connection()
    conn.execute('''
        INSERT INTO events (event_time, event_type, server_name, detail, notified)
        VALUES (?, ?, ?, ?, ?)
    ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
          event_type, server_name, detail, notified))
    # 自动裁剪：按 event_history_retention 上限删除旧记录
    from config_manager import load_config
    cfg = load_config()
    max_retention = int(cfg.get('event_history_retention', 5000) or 5000)
    _prune_events(conn, max_retention)
    conn.commit()
    conn.close()


def get_latest_scan_per_server():
    conn = get_connection()
    rows = conn.execute('''
        SELECT s.* FROM scan_records s
        INNER JOIN (
            SELECT server_name, MAX(id) as max_id FROM scan_records GROUP BY server_name
        ) latest ON s.id = latest.max_id
        ORDER BY s.server_name
    ''').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_scans(limit=50):
    conn = get_connection()
    rows = conn.execute(
        'SELECT * FROM scan_records ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_events(limit=100):
    conn = get_connection()
    rows = conn.execute(
        'SELECT * FROM events ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_scans_paginated(page=1, page_size=50):
    """分页查询扫描记录，返回 (items, total_count)，自动将越界页码修正为最大有效页"""
    conn = get_connection()
    total = conn.execute('SELECT COUNT(*) as c FROM scan_records').fetchone()['c']
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * page_size
    rows = conn.execute(
        'SELECT * FROM scan_records ORDER BY id DESC LIMIT ? OFFSET ?',
        (page_size, offset)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total, page


def get_events_paginated(page=1, page_size=50):
    """分页查询事件日志，返回 (items, total_count, clamped_page)，自动将越界页码修正为最大有效页"""
    conn = get_connection()
    total = conn.execute('SELECT COUNT(*) as c FROM events').fetchone()['c']
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    offset = (page - 1) * page_size
    rows = conn.execute(
        'SELECT * FROM events ORDER BY id DESC LIMIT ? OFFSET ?',
        (page_size, offset)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total, page


def get_known_ips():
    """获取历史出现过的所有 IP"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT client_ips FROM scan_records WHERE client_ips != '[]' ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    all_ips = set()
    for r in rows:
        try:
            ips = json.loads(r['client_ips'])
            all_ips.update(ips)
        except Exception:
            pass
    return list(all_ips)


def db_ping():
    """轻量数据库连通性检查，用于健康检查"""
    try:
        conn = get_connection()
        conn.execute('SELECT 1')
        conn.close()
        return True
    except Exception:
        return False


def get_db_stats():
    conn = get_connection()
    scan_count = conn.execute('SELECT COUNT(*) as c FROM scan_records').fetchone()['c']
    event_count = conn.execute('SELECT COUNT(*) as c FROM events').fetchone()['c']
    conn.close()
    return {'scan_count': scan_count, 'event_count': event_count}


def prune_all():
    """
    立即按配置的保留条数裁剪扫描记录和事件日志（互不影响）。
    用于配置保存后立刻清理超出上限的旧数据。
    返回 dict: {scan_deleted, event_deleted}
    """
    from config_manager import load_config
    cfg = load_config()
    max_scan = int(cfg.get('scan_history_retention', 10000) or 10000)
    max_event = int(cfg.get('event_history_retention', 5000) or 5000)

    conn = get_connection()
    result = {'scan_deleted': 0, 'event_deleted': 0}

    try:
        # 裁剪扫描记录
        if max_scan > 0:
            count_row = conn.execute('SELECT COUNT(*) as c FROM scan_records').fetchone()
            total = count_row['c']
            if total > max_scan:
                result['scan_deleted'] = total - max_scan
                conn.execute(
                    'DELETE FROM scan_records WHERE id NOT IN (SELECT id FROM scan_records ORDER BY id DESC LIMIT ?)',
                    (max_scan,)
                )
                print(f"[DB] prune_all: 扫描记录删除 {result['scan_deleted']} 条，保留 {max_scan} 条", flush=True)
    except Exception as e:
        print(f"[DB] prune_all scan error: {e}", flush=True)

    try:
        # 裁剪事件日志
        if max_event > 0:
            count_row = conn.execute('SELECT COUNT(*) as c FROM events').fetchone()
            total = count_row['c']
            if total > max_event:
                result['event_deleted'] = total - max_event
                conn.execute(
                    'DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)',
                    (max_event,)
                )
                print(f"[DB] prune_all: 事件日志删除 {result['event_deleted']} 条，保留 {max_event} 条", flush=True)
    except Exception as e:
        print(f"[DB] prune_all event error: {e}", flush=True)

    conn.commit()
    conn.close()
    return result
