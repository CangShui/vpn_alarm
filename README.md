# VPN 在线监控系统

通过 SSH 远程采集 IKEv2 / OpenVPN 服务器的在线客户端信息，实时监控并推送告警。

## 部署方式 (Debian Docker Compose)

### 1. 安装 Docker 和 Docker Compose

```bash
# Docker
curl -fsSL https://get.docker.com | bash
# Docker Compose 插件
apt install -y docker-compose-plugin
```

### 2. 准备部署目录

```bash
mkdir -p /opt/vpn-alarm && cd /opt/vpn-alarm
```

下载 `docker-compose.yml` 和 `config.json` 到该目录:

```bash
wget https://raw.githubusercontent.com/CangShui/vpn_alarm/main/docker-compose.yml
wget https://raw.githubusercontent.com/CangShui/vpn_alarm/main/config.json
```

下载 `GeoLite2-City.mmdb` 到该目录（可选，用于城市级 IP 归属地解析）:

```bash
wget -O GeoLite2-City.mmdb "https://raw.githubusercontent.com/CangShui/vpn_alarm/main/GeoLite2-City.mmdb"
```

> **注意**: `GeoLite2-City.mmdb` 不提供也不会影响系统核心功能（服务器监控、在线统计、告警推送），仅城市级 IP 解析不可用。该文件需遵循 [MaxMind GeoLite2 EULA](https://www.maxmind.com/en/geolite2/eula)。

### 3. 修改配置

编辑 `config.json`，填入你的服务器信息和通知渠道：

```bash
nano config.json
```

### 4. 启动服务

```bash
docker compose up -d
```

访问 `http://<服务器IP>:5000` 查看监控面板。

---

## 发布 Release (用于自动构建镜像)

1. **推送代码到 GitHub**:
   ```bash
   git remote add origin https://github.com/CangShui/vpn_alarm.git
   git push -u origin main
   ```

2. **在 GitHub 上创建 Release**:
   - 进入仓库 `https://github.com/CangShui/vpn_alarm`
   - 点击 `Releases` → `Create a new release`
   - 填写 Tag (如 `v1.0.0`)、标题和说明
   - 点击 `Publish release`

3. **自动构建**: GitHub Actions 会自动构建 Docker 镜像并推送到 `ghcr.io/cangshui/vpn_alarm`。

---

## 配置说明

编辑 `config.json` 后通过 `docker compose up -d` 启动即可（或重启容器: `docker compose restart`）。

- **servers**: SSH 服务器列表，支持 `ikev2` / `openvpn` 两种类型
- **notifications**: 支持 Telegram Bot 和 Webhook 通知
- **geo_file_path**: GeoIP 数据库路径（默认 `/app/GeoLite2-City.mmdb`，需用户自行下载并通过 volume 挂载）

> 注意: 如需使用 SSH 密钥认证，请将密钥文件放在部署目录并通过 volumes 挂载到容器内。

## 数据库与日志

首次 `docker compose up -d` 启动后，以下文件/目录将在宿主机部署目录自动生成：

- `data/vpn_alarm.db` — SQLite 数据库文件（表结构自动初始化，初始无历史数据）
- `logs/` — 日志目录
  - `logs/stdout.log` — 应用业务日志（采集记录、事件检测、调度信息等）
  - `logs/stderr.log` — Flask/Werkzeug 访问日志和错误信息

> 以上文件均通过 `docker-compose.yml` 的 volumes 挂载实现持久化，容器重启不会丢失数据。

### 常用查看命令

```bash
# 实时跟踪业务日志
tail -f logs/stdout.log

# 查看最近 50 行访问日志
tail -50 logs/stderr.log

# 搜索特定服务器日志
grep "服务器名称" logs/stdout.log
```

## 健康检查

系统提供 `/healthz` 接口用于运行状态监控，返回结构化 JSON：

```bash
curl http://localhost:5000/healthz
```

### 检查项

| 检查项 | 说明 |
|--------|------|
| `flask` | Flask 应用可响应 |
| `database` | SQLite 数据库可访问 |
| `scheduler` | APScheduler 已启动 |
| `scan_job` | 周期扫描任务 `periodic_scan` 存在 |
| `last_scan` | 最近一次扫描未超时（阈值 = 3× 扫描间隔 + 60 秒缓冲） |

### 响应示例

**健康** (HTTP 200)：
```json
{
  "status": "healthy",
  "checks": {
    "flask": {"status": "ok"},
    "database": {"status": "ok"},
    "scheduler": {"status": "ok"},
    "scan_job": {"status": "ok", "next_run": "2026-06-30 12:00:00"},
    "last_scan": {
      "status": "ok",
      "last_scan_time": "2026-06-30 11:59:30",
      "elapsed_seconds": 30.5,
      "scan_interval": 60,
      "threshold_seconds": 240
    }
  },
  "timestamp": "2026-06-30 12:00:00"
}
```

**不健康** (HTTP 503)：
```json
{
  "status": "unhealthy",
  "checks": {
    "flask": {"status": "ok"},
    "database": {"status": "ok"},
    "scheduler": {"status": "fail", "error": "调度器未运行"},
    "scan_job": {"status": "fail", "error": "调度器未初始化"},
    "last_scan": {"status": "fail", "error": "上次扫描已过去 300 秒，超过阈值 240 秒"}
  },
  "timestamp": "2026-06-30 12:05:00"
}
```

### Docker 健康检查

Docker 镜像内置了 `HEALTHCHECK`（30s 间隔 / 10s 超时 / 3 次重试 / 60s 启动缓冲），自动通过 `/healthz` 判定容器状态。使用 `docker ps` 或 `docker inspect` 可查看容器健康状态。

### 自愈重启机制

系统内置 **watchdog 自愈线程**，持续监控关键健康指标（数据库、调度器、扫描任务、扫描超时）。当关键故障持续超过阈值时，进程主动以非零退出码退出，由 Docker 的 `restart: unless-stopped` 策略自动重启容器，形成完整恢复闭环。

| 配置项 | 说明 |
|--------|------|
| `restart: unless-stopped` | 容器非正常退出时自动重启（`docker-compose.yml`） |
| watchdog 检查周期 | 扫描间隔的一半，最低 15 秒 |
| 退出阈值 | max(300 秒, 5 × 扫描间隔)，采用保守策略避免误杀 |
| 启动缓冲 | watchdog 启动后等待 60 秒再开始检查 |
| 故障恢复 | healthy 恢复后自动清零累计状态，支持瞬时抖动 |

**不会触发退出的情况：**
- SSH 单次采集失败（局部问题，不影响整体健康判定）
- 瞬时网络抖动导致 1-2 次检查失败
- `/healthz` 返回 HTTP 503 但持续时间未达阈值

**会触发退出的关键故障：**
1. 调度器未运行
2. 周期扫描任务丢失
3. 最近扫描超时超过阈值
4. 数据库不可访问

容器重启后，Docker 日志中可见明确退出原因：
```
[WATCHDOG] 关键 unhealthy 已持续 360s，超过阈值 300s，主动退出进程
```

---

## 许可说明

本系统支持使用 MaxMind 的 `GeoLite2-City.mmdb` 进行城市级 IP 归属地解析。该文件不再随镜像分发，用户需自行从 MaxMind 下载并遵循 [GeoLite2 EULA](https://www.maxmind.com/en/geolite2/eula)。未经授权不得用于商业用途，使用者需自行确认合规性。
