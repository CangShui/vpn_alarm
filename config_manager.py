"""
配置管理模块 - 读写 config.json，同时支持从网页修改
"""
import json
import os
import threading

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# 线程锁保护配置读写（RLock 支持同一线程重入）
_config_lock = threading.RLock()

# 默认配置
DEFAULT_CONFIG = {
    "servers": [],
    "scan_interval": 60,
    "connection_alert_window": 300,
    "status_refresh_interval": 5,
    "geo_file_path": "",
    "scan_history_retention": 10000,
    "event_history_retention": 5000,
    "notifications": {
        "telegram": {"enabled": False, "token": "", "chat_id": ""},
        "webhook": {"enabled": False, "url": "", "content_type": "application/json",
                     "headers": {}, "body_template": '{"msg": "{{message}}"}'}
    }
}


def _deep_copy_default():
    return json.loads(json.dumps(DEFAULT_CONFIG))


def _normalize_config(cfg):
    source = cfg or {}
    normalized = _deep_copy_default()
    normalized.update(source)
    normalized['servers'] = list(source.get('servers') or [])
    normalized['scan_interval'] = int(normalized.get('scan_interval') or 60)
    normalized['connection_alert_window'] = int(normalized.get('connection_alert_window') or 300)
    normalized['status_refresh_interval'] = int(normalized.get('status_refresh_interval') or 5)
    normalized['geo_file_path'] = str(normalized.get('geo_file_path') or '').strip()
    normalized['scan_history_retention'] = int(normalized.get('scan_history_retention') or 10000)
    normalized['event_history_retention'] = int(normalized.get('event_history_retention') or 5000)

    notifications = source.get('notifications') or {}
    default_notifications = _deep_copy_default()['notifications']
    merged_notifications = json.loads(json.dumps(default_notifications))
    merged_notifications.update(notifications)

    telegram = merged_notifications.get('telegram') or {}
    telegram_defaults = default_notifications['telegram'].copy()
    telegram_defaults.update(telegram)
    merged_notifications['telegram'] = telegram_defaults

    webhook = merged_notifications.get('webhook') or {}
    webhook_defaults = default_notifications['webhook'].copy()
    webhook_defaults.update(webhook)
    webhook_defaults['headers'] = dict(webhook_defaults.get('headers') or {})
    merged_notifications['webhook'] = webhook_defaults

    normalized['notifications'] = merged_notifications
    return normalized


def load_config():
    """加载配置"""
    with _config_lock:
        if not os.path.exists(CONFIG_PATH):
            return _deep_copy_default()
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            return _normalize_config(cfg)
        except Exception as e:
            print(f"[WARN] 加载配置失败: {e}, 使用默认")
            return _deep_copy_default()


# 脱敏/掩码保护策略已彻底删除。
# 所有配置字段按真实值明文读取和保存，不再做任何脱敏展示或掩码值保留。


def save_config(config):
    """保存配置到文件（直接写入用户提交内容，不做掩码识别或旧值保留）"""
    with _config_lock:
        try:
            normalized = _normalize_config(config)
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(normalized, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[ERROR] 保存配置失败: {e}")
            return False


def get_safe_config():
    """获取配置（直接返回真实值，不再脱敏）"""
    cfg = load_config()
    safe = json.loads(json.dumps(cfg))  # deep copy
    for srv in safe.get('servers', []):
        # 设置占位字段为 False，兼容模板旧逻辑
        srv['password_display_placeholder'] = False
        srv['ssh_key_passphrase_placeholder'] = False
        # 确保新增字段存在
        srv.setdefault('ssh_key_path', '')
        srv.setdefault('ssh_key_passphrase', '')
    return safe
