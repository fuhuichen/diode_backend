# Diode Backend

FastAPI 後端服務，管理節點、連線、租戶與應用程式，提供 Admin Web UI。

## 專案結構

```
diode_backend/
├── app/                        # 主應用程式
│   ├── api/
│   │   ├── client.py           # Client API（nodes/connect/keepalive/disconnect）
│   │   ├── admin.py            # Admin API + Web UI 路由
│   │   ├── agent.py            # Agent API（register/heartbeat/deregister）
│   │   └── deps.py             # 認證依賴（JWT / API Key / Node Token）
│   ├── models/
│   │   ├── node.py             # 節點（status: online/unhealthy/offline）
│   │   ├── connection.py       # 連線（bytes_up/bytes_down 流量追蹤）
│   │   ├── application.py      # 應用程式（API key + usage 限制）
│   │   ├── tenant.py           # 租戶
│   │   └── app_region.py       # 應用程式 ↔ 區域關聯
│   ├── services/
│   │   ├── node_service.py
│   │   ├── connection_service.py
│   │   ├── app_service.py
│   │   └── tenant_service.py
│   ├── schemas/                # Pydantic schemas
│   ├── templates/              # Jinja2 Web UI（dashboard, nodes, apps, tenants, connections）
│   ├── background/
│   │   └── stale_cleanup.py    # 背景清理任務
│   ├── config.py               # Pydantic Settings
│   ├── database.py             # SQLAlchemy async engine
│   └── main.py                 # FastAPI app（含 lifespan）
├── infra/                      # AWS CDK 基礎設施
│   ├── lib/
│   │   ├── diode-node-stack.ts       # Lightsail CDK stack
│   │   ├── diode-node-ec2-stack.ts   # EC2 CDK stack
│   │   └── user-data-helper.ts       # User data 模板替換
│   ├── scripts/
│   │   ├── deploy-node.sh      # 節點部署（登入 → 建立節點 → CDK deploy）
│   │   ├── destroy-node.sh
│   │   └── verify-node.sh
│   ├── cdk.json                # CDK 配置（region, bundle, diode version）
│   └── package.json
├── deploy/                     # 後端部署
│   ├── deploy_backend.sh       # rsync → Docker Compose → nginx 配置
│   ├── docker-compose.production.yml
│   ├── nginx-diode.conf
│   └── .env.production
├── agent/
│   └── agent.py                # 節點 Agent（register → heartbeat 30s → deregister）
├── alembic/                    # 資料庫遷移
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── run.py                      # 本地開發（uvicorn reload）
```

## 技術棧

- **Web 框架**: FastAPI 0.115 + Uvicorn
- **ORM**: SQLAlchemy 2.0 async + asyncpg
- **資料庫**: PostgreSQL 16
- **遷移**: Alembic
- **模板**: Jinja2（Admin Web UI）
- **認證**: JWT（Admin）、HMAC-SHA256 API Key（Client）、Node Token（Agent）
- **基礎設施**: AWS CDK（TypeScript）
- **容器化**: Docker Compose + nginx reverse proxy

## API 架構

### Client API（`/api/v1/`）
認證：`X-API-Key` + `X-API-Secret`（HMAC-SHA256）

| 端點 | 說明 |
|------|------|
| `POST /nodes` | 取得可用節點清單（支援 region 過濾） |
| `POST /connect` | 建立連線（回傳 session_id） |
| `POST /keepalive` | 保持連線 + 回報 bytes_up / bytes_down |
| `POST /disconnect` | 斷開連線 |

### Admin API（`/api/admin/`）
認證：Bearer JWT token

- 登入、Dashboard 統計
- 租戶管理（CRUD）
- 應用程式管理（CRUD + region 設定）
- 節點管理（CRUD）

### Agent API（`/api/agent/`）
認證：`X-Node-Token`

| 端點 | 說明 |
|------|------|
| `POST /register` | 節點註冊（回傳 node_id） |
| `POST /heartbeat` | 心跳（每 30 秒，含 client_address） |
| `POST /deregister` | 節點下線 |

## 背景任務（stale_cleanup.py）

每 **10 秒**執行一次：

1. **cleanup_stale_connections**：keepalive 超過 **2 分鐘**（120s）→ 標記連線為 closed
2. **check_node_health**：
   - heartbeat 超過 90 秒 → unhealthy
   - heartbeat 超過 300 秒 → offline

## 部署

### 後端部署

```bash
# rsync 到伺服器 → Docker Compose up → nginx 配置
./deploy/deploy_backend.sh
```

流程：rsync 檔案 → Docker Compose build & up → 等待 PostgreSQL → init_db → 設定 nginx（`/diode/` → `localhost:8000`）

### 節點部署

```bash
# 登入後端 → 建立節點 → CDK deploy（Lightsail 或 EC2）
./infra/scripts/deploy-node.sh
```

支援兩種 provider：
- `lightsail`（預設）：輕量管理實例
- `ec2`：完整 VPC/SG 控制，支援所有 AWS 區域

## 成本分析：Lightsail vs EC2

### 比較表（單節點）

| 項目 | Lightsail (nano_3_0) | EC2 (t3a.nano) |
|------|---------------------|----------------|
| **香港區支援** | 不支援（ap-east-1 無 Lightsail） | 支援 |
| **月費** | ~$3.50/月 | ~$3.37/月（on-demand） |
| **IP** | 內建靜態 IP（免費） | Elastic IP（使用中免費） |
| **管理** | 簡化介面 | 完整 VPC/SG 控制 |
| **流量** | 含 1 TB/月 | 按量計費（$0.09/GB） |
| **適用場景** | 有支援的區域（如 ap-southeast-1） | 所有區域（尤其 ap-east-1 香港） |

### 結論

- **成本相近**：Lightsail $3.50 vs EC2 $3.37，差異不大
- **香港區（ap-east-1）只能用 EC2**：AWS Lightsail 不支援香港區域
- **建議**：
  - 有 Lightsail 的區域（如新加坡 ap-southeast-1）→ 用 Lightsail（管理簡單、流量含免費額度）
  - 香港或其他無 Lightsail 的區域 → 用 EC2（CDK 已支援 `diode-node-ec2-stack.ts`）
