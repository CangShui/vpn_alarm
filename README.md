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
- **geo_file_path**: GeoIP 数据库路径（镜像内置 `GeoLite2-City.mmdb`）

> 注意: 如需使用 SSH 密钥认证，请将密钥文件放在部署目录并通过 volumes 挂载到容器内。

## 数据库与日志

首次 `docker compose up -d` 启动后，以下文件/目录将在宿主机部署目录自动生成：

- `vpn_alarm.db` — SQLite 数据库文件（表结构自动初始化，初始无历史数据）
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

---

## 许可说明

本仓库包含 `GeoLite2-City.mmdb`，该文件来自 MaxMind，需遵循 [GeoLite2 EULA](https://www.maxmind.com/en/geolite2/eula)。未经授权不得用于商业用途，使用者需自行确认合规性。
