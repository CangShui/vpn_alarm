"""
通知模块 - Telegram 和 Webhook 通知
"""
import json
import requests

# 超时设置
REQUEST_TIMEOUT = 15


def send_telegram(token, chat_id, message):
    """发送 Telegram 消息"""
    if not token or not chat_id:
        return False, "Token 或 chat_id 为空"

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }

    try:
        resp = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        data = resp.json()
        if resp.status_code == 200 and data.get('ok'):
            return True, f"发送成功 (msg_id={data['result']['message_id']})"
        else:
            return False, f"发送失败: {data.get('description', resp.text)}"
    except Exception as e:
        return False, f"请求异常: {str(e)}"


def send_webhook(config, message):
    """发送 Webhook 通知"""
    url = config.get('url', '')
    if not url:
        return False, "Webhook URL 为空"

    content_type = config.get('content_type', 'application/json')
    headers = dict(config.get('headers', {}))
    body_template = config.get('body_template', '{"msg": "{{message}}"}')

    # 替换模板变量
    body = body_template.replace('{{message}}', message)

    try:
        if content_type == 'application/json':
            headers['Content-Type'] = 'application/json'
            # body 已经是 JSON 字符串，尝试解析后再发送
            try:
                body_json = json.loads(body)
            except json.JSONDecodeError:
                body_json = body
            resp = requests.post(url, json=body_json, headers=headers, timeout=REQUEST_TIMEOUT)
        else:
            headers['Content-Type'] = content_type
            resp = requests.post(url, data=body.encode('utf-8'), headers=headers, timeout=REQUEST_TIMEOUT)

        if 200 <= resp.status_code < 300:
            return True, f"发送成功 (status={resp.status_code})"
        else:
            return False, f"发送失败 (status={resp.status_code}): {resp.text[:200]}"
    except Exception as e:
        return False, f"请求异常: {str(e)}"
