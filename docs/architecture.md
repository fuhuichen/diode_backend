# Diode Cloud 技術架構文件

> **文件用途**：供技術主管理解系統架構、安全模型與擴展策略
> **更新日期**：2026 年 2 月

---

## 1. 系統總覽

Diode Cloud 是一套端對端加密的代理隧道服務，由三個核心元件組成：

```
┌─────────────────────────────────────────────────────────────────────┐
│                      終端用戶裝置（Android / iOS）                    │
│                    SOCKS5 → secp256k1 E2E 加密隧道                   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ 加密連線（port 41046）
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       全球節點層（Node Layer）                        │
│                                                                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐   │
│  │ 新加坡節點  │  │  東京節點   │  │  美東節點   │  │  香港節點   │   │
│  │ Lightsail  │  │ Lightsail  │  │ Lightsail  │  │  EC2 only  │   │
│  │ (Agent)    │  │ (Agent)    │  │ (Agent)    │  │ (Agent)    │   │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘   │
│        └───────────────┼───────────────┼───────────────┘           │
│                        │ HTTPS（心跳 30s / 註冊 / 下線）             │
└────────────────────────┼───────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Diode 管理後台（Backend）                          │
│                                                                     │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐          │
│  │  FastAPI     │  │  商業邏輯層    │  │  背景排程服務      │          │
│  │  API 路由    │  │  (Services)   │  │  (stale_cleanup)  │          │
│  │  + Web UI   │  │              │  │  每 10 秒執行      │          │
│  └──────┬──────┘  └──────┬───────┘  └────────┬──────────┘          │
│         └────────────────┼──────────────────┘                      │
│                          ▼                                         │
│              ┌──────────────────────┐                              │
│              │  PostgreSQL 16       │                              │
│              │  (async + asyncpg)   │                              │
│              └──────────────────────┘                              │
└─────────────────────────────────────────────────────────────────────┘
                         ▲
                         │ HTTPS（API Key + Secret）
┌────────────────────────┼───────────────────────────────────────────┐
│                 客戶的 App（API 整合）                                │
│         nodes → connect → keepalive(25s) → disconnect              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 元件架構

### 2.1 管理後台（diode_backend）

| 層級 | 技術 | 說明 |
|------|------|------|
| Web 框架 | FastAPI 0.115 + Uvicorn | 非同步高效能，自動產生 OpenAPI 文件 |
| ORM | SQLAlchemy 2.0 async + asyncpg | 非同步資料庫操作，支援行鎖 |
| 資料庫 | PostgreSQL 16 | 關聯式儲存，索引最佳化 |
| 遷移 | Alembic | 版本化 schema 管理 |
| Web UI | Jinja2 + TailwindCSS | 伺服器端渲染的管理介面 |
| 容器化 | Docker Compose + nginx | 反向代理 + 自動 TLS |

**目錄結構**：

```
app/
├── api/
│   ├── client.py    → Client API（/api/v1/nodes, connect, keepalive, disconnect）
│   ├── admin.py     → Admin API + Web UI（/api/admin/, /dashboard, /nodes ...）
│   ├── agent.py     → Agent API（/api/agent/register, heartbeat, deregister）
│   └── deps.py      → 三層認證依賴
├── models/          → SQLAlchemy 模型（Node, Connection, Application, Tenant, AppRegion）
├── services/        → 商業邏輯（node, connection, app, tenant）
├── schemas/         → Pydantic 請求/回應 schema
├── background/
│   └── stale_cleanup.py → 連線逾時清理 + 節點健康檢查
├── templates/       → Jinja2 Web UI 模板
├── config.py        → Pydantic Settings
├── database.py      → async engine 設定
└── main.py          → FastAPI lifespan（啟動背景任務）
```

### 2.2 Android 客戶端（diode_android）

| 層級 | 技術 | 說明 |
|------|------|------|
| 應用層 | Kotlin + Material Components | 原生 Android |
| 代理引擎 | Go Mobile (gomobile bind) | Diode SOCKS5 + E2E 加密 |
| 加密 | secp256k1 + OpenSSL 1.1.1k | 區塊鏈等級橢圓曲線加密 |

**Flavor 設定**（多品牌 APK）：

| Flavor | Application ID | SOCKS Port | Proxy Port | 預設 URL |
|--------|---------------|------------|------------|----------|
| UB | `com.diode.ub` | 9080 | 8080 | ubet88.io |
| K7 | `com.diode.k7` | 9081 | 8081 | zc83641fun.shop |

### 2.3 節點 Agent

- **語言**：Python asyncio + httpx
- **部署方式**：嵌入 EC2/Lightsail user-data，開機即啟動
- **生命週期**：register → heartbeat (30s) → deregister（SIGTERM）
- **回報資訊**：client_address（公網 IP:port）、運作狀態

---

## 3. 資料模型

```
Tenant（租戶/客戶公司）
 │
 ├── name（唯一）
 ├── password（SHA256）
 ├── is_active
 │
 └── 1:N ─── Application（應用程式/API 金鑰）
              │
              ├── api_key（唯一，如 dk_xxx）
              ├── api_secret（SHA256 雜湊儲存）
              ├── max_concurrent（同時連線上限，預設 10）
              ├── usage_limit（流量上限，預設 1 GB）
              ├── usage_bytes（累計已用流量）
              ├── is_active
              │
              ├── N:M ─── AppRegion（允許的區域）
              │            └── region（如 ap-southeast-1）
              │
              └── 1:N ─── Connection（連線紀錄）
                           │
                           ├── session_id（唯一）
                           ├── node_id → FK Node
                           ├── status（active / closed）
                           ├── bytes_up, bytes_down（BigInteger）
                           ├── last_keepalive
                           └── connected_at, disconnected_at

Node（代理節點）
 │
 ├── node_token（唯一，部署時產生）
 ├── region
 ├── client_address（公網 IP:port，Agent 回報更新）
 ├── status（online / unhealthy / offline）
 └── last_heartbeat
```

**關鍵索引**：
- `Connection(app_id, status='active')` — 快速查詢活躍連線數
- `Connection(last_keepalive, status='active')` — 逾時清理掃描
- `Node(region, status)` — 區域節點查詢

---

## 4. 三層認證機制

| 認證層 | 對象 | 機制 | 細節 |
|--------|------|------|------|
| **Client API** | App 開發者 | API Key + Secret | `X-API-Key` + `X-API-Secret`，Secret 以 HMAC-SHA256 驗證，固定時間比對防計時攻擊 |
| **Admin API** | 系統管理員 | JWT Bearer Token | 24 小時有效期，HS256 簽名，cookie + header 雙支援 |
| **Agent API** | 節點主機 | Node Token | `X-Node-Token`，每節點獨立，可即時撤銷 |

**安全設計重點**：
- API Secret 以 SHA256 雜湊儲存，不可逆
- E2E 加密（secp256k1）：後台與節點**都無法解密**用戶流量
- App 層級資料隔離：不同 App 的連線紀錄完全分離
- 節點 Token 被盜可立即撤銷，不影響其他節點

---

## 5. 核心流程

### 5.1 連線生命週期

```
App 請求連線
     │
     ▼
後台檢查 ─┬── 活躍連線 < max_concurrent？
          │     └── 否 → HTTP 429「max_concurrent_reached」
          │
          ├── usage_bytes < usage_limit × 1.2？
          │     └── 否 → HTTP 429「usage_limit_exceeded」
          │
          └── 通過 → 建立 Connection 紀錄，回傳 session_id
                        │
                        ▼
               App 透過 Diode 建立加密連線
                        │
                        ├── 每 25 秒 keepalive
                        │    └── 回報 bytes_up / bytes_down
                        │    └── 後台原子累加 usage_bytes
                        │    └── 回傳 warning: true（接近上限時）
                        │
                        ├── 正常斷線 → disconnect API → 釋放名額
                        │
                        └── 異常斷線 → 超過 2 分鐘無 keepalive
                                       → 背景任務自動標記 closed
```

### 5.2 節點健康監控

```
Agent 啟動 → POST /api/agent/register → 取得 node_id
     │
     ├── 每 30 秒 → POST /api/agent/heartbeat
     │               └── 更新 client_address、last_heartbeat
     │               └── 狀態設為 online
     │
     └── 關機 → POST /api/agent/deregister → 狀態設為 offline

後台背景排程（每 10 秒）：
  · last_heartbeat > 90 秒  → 狀態：unhealthy（不分配新連線）
  · last_heartbeat > 300 秒 → 狀態：offline（移出可用清單）
```

### 5.3 Android 連線流程

```
LoadingActivity
  → 啟動 DiodeForegroundService（SOCKS5 on port 9080/9081）
  → 等待 Diode ready（輪詢，最多 45 秒）
  → NodeConnectionManager.connectToNode()
      → getNodes()（取得節點清單，按連線數排序）
      → connect(nodeId, sessionId)
      → setBinds("<PROXY_PORT>:<client_address>:1080:tcp")
  → 成功 → WebViewActivity（proxy override → SOCKS5）
  → keepalive 每 25 秒（Go 原子計數器 → bytes_up/down）
```

---

## 6. 基礎設施與部署

### 6.1 後端部署

```bash
./deploy/deploy_backend.sh
```

流程：rsync → Docker Compose（PostgreSQL + FastAPI）→ nginx 反向代理（`/diode/` → `localhost:8000`）

### 6.2 節點部署

```bash
./infra/scripts/deploy-node.sh
```

流程：Admin 登入 → 建立 Node（取得 token）→ AWS CDK deploy → user-data 自動啟動 Agent

**CDK 支援兩種 Stack**：

| Stack | 檔案 | 適用場景 |
|-------|------|---------|
| Lightsail | `diode-node-stack.ts` | 有支援的區域（新加坡、東京、美東等） |
| EC2 | `diode-node-ec2-stack.ts` | 所有區域（尤其香港 ap-east-1） |

### 6.3 Lightsail vs EC2 比較

| 項目 | Lightsail (nano_3_0) | EC2 (t3a.nano) |
|------|---------------------|----------------|
| **香港區支援** | 不支援（ap-east-1 無 Lightsail） | 支援 |
| **月費** | ~$3.50/月 | ~$3.37/月（on-demand） |
| **IP** | 內建靜態 IP（免費） | Elastic IP（使用中免費） |
| **流量** | 含 1 TB/月 | 按量計費（$0.09/GB） |
| **管理** | 簡化介面，開箱即用 | 完整 VPC/SG 控制 |
| **CDK 整合** | 已實作 | 已實作 |

> **結論**：成本相近。有 Lightsail 的區域優先使用 Lightsail（流量含免費額度）；香港區或其他無 Lightsail 的區域使用 EC2。

### 6.4 節點開放端口

| Port | 協議 | 用途 |
|------|------|------|
| 22 | TCP | SSH 管理 |
| 3300 | TCP/UDP | SOCKS5 代理 |
| 41046 | TCP/UDP | Diode P2P 通訊 |

---

## 7. 擴展策略

| 瓶頸 | 現況容量 | 擴展方式 |
|------|---------|---------|
| 單節點連線數 | ~200 同時 | 同區域新增節點（水平擴展） |
| 單區域流量 | 1-2 TB/節點/月 | 加開節點，自動分散 |
| 後台 API | ~1,000 req/s | 升級主機 或 多台 + 負載平衡 |
| 資料庫 | ~10,000 筆/s | 升級 DB 規格 或 遷移 RDS |
| 節點部署 | CDK 手動觸發 | 未來可整合自動擴容（負載 >80% 自動加機器） |

> 架構設計從 3 台到 100+ 台節點無需重構，只需「加機器 + CDK deploy」。

---

## 8. 監控與可觀測性

### Admin Dashboard 即時指標

| 指標 | 來源 |
|------|------|
| 在線節點數 / 總節點數 | Node.status = online |
| 活躍連線數 | Connection.status = active |
| 各區域節點狀態 | Node.region + status 分群 |
| 應用流量使用率 | Application.usage_bytes / usage_limit |
| 最近連線清單 | Connection 依 connected_at 排序 |

### 自動化健康維護

| 機制 | 間隔 | 動作 |
|------|------|------|
| 節點心跳 | 30 秒 | Agent → Backend，更新 last_heartbeat |
| 客戶端 keepalive | 25 秒 | App → Backend，回報流量 + 維持連線 |
| 逾時清理 | 10 秒 | Backend 背景任務，清理斷線 + 節點降級 |
