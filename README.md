# 实验室设备校准追溯服务

基于 **Python / FastAPI + PostgreSQL** 的设备校准证书与测量记录追溯服务。

## 业务规则

- **证书**：记录证书号、设备、有效期起止时刻。
  - 时刻**必须带时区**（请求中的无时区时间会被拒绝，返回 422）。
  - 起点必须严格早于终点。
  - 有效期按**左闭右开** `[valid_from, valid_to)` 判定，因此相邻证书
    （一张 `…07-01` 到期、另一张 `07-01…` 生效）**不算重叠**。
  - 同一设备的证书有效期**不得重叠**：由 PostgreSQL 的
    `EXCLUDE USING gist (... tstzrange ... WITH &&)` 约束在数据库层保证，
    并发登记时**只有一份成功**，冲突方得到 409。
- **幂等登记**：证书登记接口必须带 `Idempotency-Key` 请求头。
  - 同键 + 同内容重试：返回首次的原始响应（状态码与报头均一致）。
  - 同键 + 不同内容：返回 **409 Conflict**。
- **测量记录**：写入设备、测量时刻、证书号（及可选数值/备注）。
  - 只有证书**覆盖该时刻且未被撤销**才接受，否则 422。
  - 记录一经写入**不可修改、不可删除**（数据库触发器拒绝 `UPDATE`/`DELETE`）。
- **撤销证书**：`POST /certificates/{cert_no}/revoke`，不删除任何历史测量。
- **即时有效性查询**：每次查询实时联表计算，每条记录返回
  `validity.is_valid` 与原因（`reason_code` / `reason`）：

  | reason_code | 含义 |
  |---|---|
  | `VALID` | 证书未撤销且覆盖测量时刻 |
  | `CERTIFICATE_REVOKED` | 证书已被撤销（历史记录保留，仅失效） |
  | `CERTIFICATE_NOT_COVERING` | 证书有效期不覆盖测量时刻 |

## 一键启动

需要 Docker 与 Docker Compose v2：

```bash
docker compose up --build
```

启动时会自动：

1. 启动 PostgreSQL 16 并创建数据库/账号；
2. 执行 [`db/init/01_init.sql`](db/init/01_init.sql) 建表、创建扩展
   `btree_gist`、排他约束与防改写触发器（仅在数据卷首次初始化时执行）；
3. 等待数据库就绪后启动 API。

停止：`docker compose down`；同时清除数据卷：`docker compose down -v`。

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `APP_DATABASE_URL` | `postgresql+psycopg2://calib:calib@db:5432/calibration` | 数据库连接串 |
| `APP_DB_CONNECT_TIMEOUT` | `60` | 启动时等待数据库就绪的秒数 |
| `APP_DB_POOL_SIZE` | `10` | 连接池大小 |
| `APP_MAX_OVERFLOW` | `20` | 连接池溢出连接数 |

PostgreSQL 容器的账号/密码/库名在 `docker-compose.yml` 中配置
（`calib / calib / calibration`）。生产环境请修改并同步调整 `APP_DATABASE_URL`。

## 地址与端口

- API 服务：`http://localhost:8000`
- Swagger UI（交互文档）：`http://localhost:8000/docs`
- OpenAPI JSON：`http://localhost:8000/openapi.json`
- 健康检查：`http://localhost:8000/health`
- PostgreSQL：`localhost:5432`

## HTTP API

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/equipment` | 登记设备 |
| `GET` | `/equipment/{code}` | 查询设备 |
| `POST` | `/certificates` | 幂等登记证书（需 `Idempotency-Key` 头） |
| `GET` | `/certificates` | 证书列表（可按 `?equipment_code=` 过滤） |
| `GET` | `/certificates/{cert_no}` | 查询证书 |
| `POST` | `/certificates/{cert_no}/revoke` | 撤销证书（重复调用幂等） |
| `POST` | `/measurements` | 写入测量记录（仅接受有效覆盖的证书） |
| `GET` | `/measurements` | 查询记录及当前有效性（可按 `equipment_code`、`is_valid` 过滤，`limit/offset` 分页） |
| `GET` | `/measurements/{id}` | 查询单条记录及当前有效性 |

## 调用示例（curl）

```bash
# 1. 登记设备
curl -X POST http://localhost:8000/equipment \
  -H 'Content-Type: application/json' \
  -d '{"code":"SCALE-001","name":"Analytical balance #1"}'

# 2. 幂等登记证书（注意 Idempotency-Key，时间带时区，左闭右开）
curl -X POST http://localhost:8000/certificates \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: 7b2f91ae-0c5e-4d3a-9f0a-2e4c6b8a1d77' \
  -d '{
    "cert_no": "CNAS-2026-0001",
    "equipment_code": "SCALE-001",
    "valid_from": "2026-01-01T00:00:00+00:00",
    "valid_to":   "2026-07-01T00:00:00+00:00"
  }'

# 3. 同键重试（原样返回）；换内容同键 -> 409

# 4. 写入测量记录
curl -X POST http://localhost:8000/measurements \
  -H 'Content-Type: application/json' \
  -d '{
    "equipment_code": "SCALE-001",
    "cert_no": "CNAS-2026-0001",
    "measured_at": "2026-06-15T08:30:00+08:00",
    "value": 1.2345,
    "note": "sample A"
  }'
# 响应内含实时有效性：
# {"id":1, ..., "validity":{"is_valid":true,"reason_code":"VALID",
#  "reason":"Certificate is not revoked and covers the measurement time."}}

# 5. 撤销证书（历史测量保留）
curl -X POST http://localhost:8000/certificates/CNAS-2026-0001/revoke

# 6. 再查：记录仍在，但立即变为失效
curl 'http://localhost:8000/measurements/1'
# validity: {"is_valid":false,"reason_code":"CERTIFICATE_REVOKED", ...}
```

完整演示脚本（含边界时刻、幂等冲突、并发重叠、撤销前后查询）：

```bash
scripts/demo.sh            # 默认 BASE=http://localhost:8000
BASE=http://127.0.0.1:8000 scripts/demo.sh
```

## 并发冲突说明

- 证书重叠：`cert_no_overlap` 排他约束是数据库级判定，两个事务同时登记
  重叠区间时，一个提交成功，另一个收到 `23P01 exclusion_violation`，
  服务转为 **409 Conflict**。
- 证书号重复：唯一约束保证并发下仅一份成功，另一份 409。
- 撤销 vs. 测量写入：撤销与写测量都对证书行加 `SELECT ... FOR UPDATE`
  行锁，二者串行化——撤销已提交后到达的测量不会被接受。
- 幂等键并发：`idempotency_records` 主键先插入占位行，同键并发请求在
  行锁上排队后统一回放首次结果。

## 本地非容器开发

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# 对自建 PostgreSQL 执行 db/init/01_init.sql，然后：
export APP_DATABASE_URL='postgresql+psycopg2://calib:calib@localhost:5432/calibration'
uvicorn app.main:app --reload
```
