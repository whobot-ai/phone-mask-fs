# phone-mask-fs

号码隐私保护系统 - FreeSWITCH 版

## 目录结构

```
phone-mask-fs/
├── mask-service/               # 号码映射HTTP服务（Python/FastAPI，与Kamailio版相同）
│   ├── app/
│   │   ├── main.py             # API路由：/mask /unmask /health
│   │   ├── database.py         # SQLite / PostgreSQL 双支持
│   │   ├── config.py           # 环境变量配置
│   │   └── auth.py             # 双密钥鉴权
│   ├── tests/test_api.py
│   ├── run.py
│   ├── requirements.txt
│   └── Dockerfile
│
├── freeswitch/
│   ├── scripts/
│   │   ├── unmask.lua          # ★ 核心：Token → 真实号，HTTP查询映射服务
│   │   └── check_mask_service.lua  # 启动检查脚本
│   ├── dialplan/
│   │   └── masked-inbound.xml  # ★ dialplan：收Token→调lua→bridge线路商
│   ├── sip_profiles/
│   │   └── inbound-masked.xml  # SIP Profile：5080端口，IP白名单
│   └── autoload_configs/
│       ├── acl.conf.xml        # ACL白名单定义
│       ├── sofia-carrier.xml   # Gateway定义
│       └── vars-mask.xml       # 环境变量注入
│
├── deploy/
│   ├── docker-compose.yml      # 只启动映射服务（FS装宿主机）
│   └── .env.example
│
└── docs/
    └── 部署手册-FreeSWITCH版.md
```

## 核心文件说明

### unmask.lua
- 优先用 LuaSocket（纯Lua，无子进程开销）
- LuaSocket不可用时自动回退到系统 `curl` 命令
- Token格式校验，防止非法请求
- 日志只打真实号末4位，不泄露完整号码
- 错误原因写入 `unmask_error` channel variable，dialplan按原因分类处理

### masked-inbound.xml
- 正则匹配 `tok_[a-f0-9]{32}` 格式
- 按 unmask_error 分类挂断（404/410/503/401各自对应的SIP原因码）
- 支持 bypass_media（注释切换）

## 快速开始

```bash
# 1. 启动映射服务
cd deploy
cp .env.example .env && vim .env   # 填写Key
docker compose up -d --build

# 2. 部署FS配置
cp freeswitch/scripts/*.lua /etc/freeswitch/scripts/
cp freeswitch/dialplan/masked-inbound.xml /etc/freeswitch/dialplan/
cp freeswitch/sip_profiles/inbound-masked.xml /etc/freeswitch/sip_profiles/
# 参考部署手册完成ACL和Gateway配置

# 3. 重载
fs_cli -x "reloadacl && reloadxml"
fs_cli -x "sofia profile inbound-masked start"

# 4. 验证
fs_cli -x "luarun check_mask_service.lua"
```

## 接口速查

| 接口 | 调用方 | 功能 |
|------|--------|------|
| `POST /mask` | 客户CRM（内网） | 手机号→Token |
| `GET /unmask?token=tok_xxx` | FS Lua脚本（本机） | Token→手机号 |
| `DELETE /mask/:token` | 客户CRM（内网） | 注销Token |
| `GET /health` | 监控 | 健康检查 |
