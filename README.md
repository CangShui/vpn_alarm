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

---

## 许可说明

本仓库包含 `GeoLite2-City.mmdb`，该文件来自 MaxMind，需遵循 [GeoLite2 EULA](https://www.maxmind.com/en/geolite2/eula)。未经授权不得用于商业用途，使用者需自行确认合规性。
