# 号码隐私保护系统 - 客户侧部署手册（FreeSWITCH版）

**版本：** 1.0

---

## 架构总览

```
外呼服务商 FreeSWITCH
      │
      │  SIP INVITE sip:tok_a3f9c2b1...@客户FS:5080
      ▼
┌─────────────────────────────────────────────────────────┐
│  客户服务器                                               │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  FreeSWITCH                                     │    │
│  │                                                 │    │
│  │  inbound-masked profile（:5080）                │    │
│  │       ↓ ACL 白名单校验                           │    │
│  │  masked-inbound context                         │    │
│  │       ↓ lua unmask.lua                          │    │
│  │       ↓ HTTP GET /unmask?token=tok_xxx          │    │
│  │       ↓ 得到真实号                               │    │
│  │  bridge → carrier-outbound gateway              │    │
│  └──────────────────┬──────────────────────────────┘    │
│                     │ HTTP 127.0.0.1:8080               │
│  ┌──────────────────▼──────────────────────────────┐    │
│  │  映射服务（Docker）                               │    │
│  │  /unmask → 查本地DB → 返回真实号                  │    │
│  │  /mask   → CRM调用，写入映射                      │    │
│  └─────────────────────────────────────────────────┘    │
│                     │                                   │
└─────────────────────┼───────────────────────────────────┘
                      ↓ SIP + RTP
                   线路商 → 真实用户
```

**媒体路径**（两种模式）：
- `bypass-media=true`（默认配置）：RTP 直连，不过本机，节省带宽
- 注释掉 bypass_media：RTP 过本机，可录音/质检

---

## 一、服务器要求

| 项目 | 要求 |
|------|------|
| OS | Ubuntu 22.04 LTS（推荐） |
| FreeSWITCH | 1.10.x |
| Docker | 24.x+ |
| 内存 | ≥ 4 GB |
| 公网 IP | 需要，或与外呼服务商网络可达 |
| 开放端口 | 5080/udp+tcp（SIP收话）、RTP端口范围（16384-32768/udp） |
| 禁止对外 | 8080/tcp（映射服务，仅本机） |

---

## 二、安装 FreeSWITCH

```bash
# Ubuntu 22.04
apt-get update && apt-get install -y gnupg2 wget lsb-release

wget -O /usr/share/keyrings/freeswitch.gpg \
  https://files.freeswitch.org/repo/deb/debian-release/fsstretch-archive-keyring.gpg

echo "deb [signed-by=/usr/share/keyrings/freeswitch.gpg] \
  https://files.freeswitch.org/repo/deb/debian-release/ $(lsb_release -sc) main" \
  > /etc/apt/sources.list.d/freeswitch.list

apt-get update
apt-get install -y freeswitch-meta-bare freeswitch-conf-vanilla \
  freeswitch-mod-sofia freeswitch-mod-lua \
  freeswitch-mod-commands freeswitch-mod-dptools \
  freeswitch-mod-logfile freeswitch-mod-console

# 安装 LuaSocket（Lua HTTP库）
apt-get install -y lua5.2 lua-socket

# 验证
fs_cli -x "version"
```

---

## 三、安装 Docker（映射服务用）

```bash
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

---

## 四、部署映射服务

```bash
cd /opt/phone-mask-fs/deploy
cp .env.example .env
vim .env
```

**必须修改：**
```bash
# 生成两个随机Key
python3 -c "import secrets; print(secrets.token_hex(32))"  # 执行两次

INTERNAL_API_KEY=<第一个key>   # CRM调用 /mask 用
GATEWAY_API_KEY=<第二个key>    # FreeSWITCH Lua 脚本用
```

启动：
```bash
docker compose up -d --build
docker compose ps   # 确认 healthy
```

---

## 五、部署 FreeSWITCH 配置文件

### 5.1 Lua 脚本

```bash
cp freeswitch/scripts/unmask.lua /etc/freeswitch/scripts/
cp freeswitch/scripts/check_mask_service.lua /etc/freeswitch/scripts/
```

### 5.2 Dialplan

```bash
cp freeswitch/dialplan/masked-inbound.xml /etc/freeswitch/dialplan/
```

### 5.3 SIP Profile

```bash
cp freeswitch/sip_profiles/inbound-masked.xml /etc/freeswitch/sip_profiles/
```

### 5.4 ACL 白名单

编辑 `/etc/freeswitch/autoload_configs/acl.conf.xml`，在 `<network_lists>` 里追加：

```xml
<list name="aidialer-acl" default="deny">
  <!-- !! 改为外呼服务商实际出口IP !! -->
  <node type="allow" cidr="外呼服务商IP/32"/>
</list>
```

### 5.5 线路商 Gateway

编辑 `/etc/freeswitch/sip_profiles/external.xml`（或新建），添加 gateway：

```xml
<gateway name="carrier-outbound">
  <param name="username" value="线路商账号"/>
  <param name="password" value="线路商密码"/>
  <param name="proxy"    value="线路商SIP地址"/>
  <param name="register" value="true"/>
  <param name="codec-prefs" value="PCMA,PCMU"/>
</gateway>
```

### 5.6 注入环境变量

编辑 `/etc/freeswitch/vars.xml`，末尾追加：

```xml
<X-PRE-PROCESS cmd="exec-set" data="MASK_SERVICE_URL=echo -n ${MASK_SERVICE_URL:-http://127.0.0.1:8080}"/>
<X-PRE-PROCESS cmd="exec-set" data="GATEWAY_API_KEY=echo -n ${GATEWAY_API_KEY}"/>
```

编辑 FreeSWITCH 的 systemd 服务，注入环境变量：

```bash
systemctl edit freeswitch
```

添加内容：
```ini
[Service]
EnvironmentFile=/opt/phone-mask-fs/deploy/.env
```

---

## 六、重载配置

```bash
# 重载 ACL
fs_cli -x "reloadacl"

# 重载 XML（dialplan + vars）
fs_cli -x "reloadxml"

# 重启 sofia profile（加载新 profile）
fs_cli -x "sofia profile inbound-masked start"
fs_cli -x "sofia profile external rescan"

# 验证 profile 已启动
fs_cli -x "sofia status"
# 应看到 inbound-masked  RUNNING (0)  port 5080

# 验证 gateway 已注册
fs_cli -x "sofia status gateway carrier-outbound"

# 检查映射服务连通性
fs_cli -x "luarun check_mask_service.lua"
```

---

## 七、验证测试

### 7.1 先用 curl 测试映射服务

```bash
# 生成 Token
curl -s -X POST http://127.0.0.1:8080/mask \
  -H "Content-Type: application/json" \
  -H "X-Internal-Key: 你的INTERNAL_API_KEY" \
  -d '{"phone":"13800138000"}'
# 返回：{"token":"tok_a3f9c2b1...","expires_at":null}

# 反查
curl -s "http://127.0.0.1:8080/unmask?token=tok_a3f9c2b1..." \
  -H "X-Gateway-Key: 你的GATEWAY_API_KEY"
# 返回：{"phone":"13800138000"}
```

### 7.2 用 SIPp 测试端到端

```bash
# 安装 sipp
apt-get install -y sipp

# 发一个测试 INVITE（将 IP 和 token 改为实际值）
sipp -sn uac 客户服务器IP:5080 \
  -s "tok_a3f9c2b1d4e8f012a3f9c2b1d4e8f012" \
  -l 1 -m 1
```

### 7.3 查看 FreeSWITCH 日志

```bash
# 实时日志
fs_cli -x "console loglevel debug"
tail -f /var/log/freeswitch/freeswitch.log | grep -E "\[unmask\]|masked"
```

---

## 八、媒体模式选择

编辑 `/etc/freeswitch/dialplan/masked-inbound.xml`：

**节省带宽（RTP直连）：**
```xml
<action application="set" data="bypass_media=true"/>
```

**可录音/质检（RTP过本机）：**
```xml
<!-- 注释掉 bypass_media 那行，或改为： -->
<action application="set" data="proxy_media=true"/>
```

修改后执行 `fs_cli -x "reloadxml"` 生效。

---

## 九、告知外呼服务商

部署完成后提供：

| 信息 | 内容 |
|------|------|
| 网关地址 | `服务器公网IP:5080` |
| 协议 | SIP/UDP |
| 被叫格式 | `tok_<32位小写hex>`（共36字符） |

**不需要告知**：INTERNAL_API_KEY、GATEWAY_API_KEY、数据库内容。

---

## 十、安全核查清单

- [ ] `INTERNAL_API_KEY` 和 `GATEWAY_API_KEY` 已改为随机强密码
- [ ] 防火墙已屏蔽 8080 对外（`ufw deny 8080`）
- [ ] ACL 已配置外呼服务商 IP 白名单
- [ ] FreeSWITCH 5080 端口只对外呼服务商 IP 开放
- [ ] 已验证 `/unmask` 从外网返回 403/拒绝连接
- [ ] 日志中真实号码仅显示末4位（`***xxxx`）
- [ ] 数据库文件定期备份

---

## 十一、常见问题

**Q：FreeSWITCH 日志显示 "LuaSocket 不可用"？**
```bash
apt-get install -y lua-socket
# 或
luarocks install luasocket
```

**Q：ACL 拒绝了合法 IP？**
```bash
fs_cli -x "reloadacl"
fs_cli -x "acl 外呼服务商IP aidialer-acl"
# 返回 true 表示在白名单内
```

**Q：Gateway 注册失败？**
```bash
fs_cli -x "sofia status gateway carrier-outbound"
# 查看 State 字段，REGED=注册成功，NOREG=不需要注册，FAILED=失败
```

**Q：bypass_media 下录音不工作？**
RTP 不过本机，无法录音。需要录音必须去掉 bypass_media，RTP 过本机后用：
```xml
<action application="record_session" data="/var/recordings/${uuid}.wav"/>
```
