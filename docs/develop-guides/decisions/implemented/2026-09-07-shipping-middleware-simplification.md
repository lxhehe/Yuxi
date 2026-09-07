# 收缩 shipping 中间件：删除知识图谱并默认改用 RustFS

状态：implemented
类型：simplification
Owner：docker-compose.yml

本记录吸收并取代 `2026-09-07-remove-knowledge-graph.md`。知识导图（`mindmap` / `get_mindmap` / markmap）和 LangGraph Agent 运行时不在删除范围。对象存储客户端 Owner 是 `backend/package/yuxi/storage/s3/client.py`；知识库详情 Owner 是 `web/src/views/DataBaseInfoView.vue`。

## 问题

当前默认 Compose 曾为两条不再值得维持的中间件付钱：知识图谱（Neo4j、G6、图谱表与图检索）和 MinIO（AGPL、停更镜像）。只藏入口或继续跑 MinIO，许可证、镜像清单、启动依赖和认知负担都不会下降。

## 决策

一次改造完成两件事，不留开关、不留双跑、不留空路由：

- 删除知识图谱产品面及其全部支撑栈。
- 默认对象存储改为 RustFS（Apache 2.0，S3，钉死 `rustfs/rustfs:1.0.0-rc.5`），Yuxi 与 Milvus 共用这一个进程。

保留：知识导图；vector / keyword / hybrid / rerank；评估的向量构建；`knowledge-base` 文本工具；PostgreSQL、Redis、Milvus、etcd、沙盒。

应用进程使用 `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_PUBLIC_BASE_URL`。Milvus 仍使用上游变量名 `MINIO_ADDRESS=rustfs:9000`。Python `minio` 包只作为 S3 SDK。新建内部 URL 使用 `s3://`；读取同时接受历史 `minio://` 与 `http(s)://host/bucket/key`。对外 HTTP 路径 `/minio/public/` 保持为已发布的只读代理合同。旧 MinIO 数据目录不能挂到 RustFS；已有部署用 `scripts/copy_object_store.py` 复制对象后再切流量。

## 替代方案

- 只删图谱、继续 MinIO：AGPL 与停更镜像仍在默认拓扑。拒绝。
- 默认 SeaweedFS：与当前 S3 客户端差得更远。拒绝；RC 无法通过主链路时另开决策。
- Garage：仍是 AGPL。拒绝。
- Ceph：超出单机 Compose。拒绝。
- RustFS 与 MinIO 双跑或 feature flag：半残拓扑。拒绝。
- 把旧 MinIO 卷直接挂给 RustFS：磁盘格式不兼容。拒绝。
- 改公开 URL 前缀 `/minio/public/`：无必要破坏已存 Markdown 与头像。拒绝。

## 后果

shipping 不能构建或检索知识图谱。默认拓扑无 Neo4j、无 MinIO 进程/镜像。`d3` 仍作为 `markmap-view` 的传递依赖保留，因为知识导图需要它；`@antv/g6` 已从直接依赖和 lock 中删除。RustFS 钉在 `1.0.0-rc.5`，单盘 SNSD 无纠删。容器 UID 10001，bind mount 必须可写。图谱 DROP 与对象 URL 改写不可回滚。

重新引入条件：图谱或 MinIO 只能由新的 `feature` 决策接回，不得以默认关闭开关复活。

## 验证

旧能力不存在：shipping 不能构建或检索知识图谱；默认拓扑无 Neo4j、无 MinIO 进程/镜像；图谱专用 Python/前端直接依赖不在 lock 中。

重新引入条件：图谱或 MinIO 只能由新的 `feature` 决策接回，不得以默认关闭开关复活。

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| 详情无图谱页；评估拒绝 `graph_enhanced` | 只藏 UI | `DataBaseInfoView.vue`；eval service | web unit 无 `panel-graph`；unit 拒绝该 mode | 恢复 graph tab 或接受该 mode 后失败 | Passed |
| `/api/graph/*` 与 `graph-build/*` 未注册；导图仍在 | 仍 include_router | `routers/__init__.py` | `test_graph_routes_removed.py` | 重新挂载后失败 | Passed |
| 检索无图融合；`knowledge-base` 仍含 `get_mindmap` | 误删导图或仍 PPR | `MilvusKB.aquery`；kbs tools | retrieval config unit；tools unit | 去掉 `get_mindmap` 不得算成功 | Passed |
| knowledge v3：无图谱表/列；`minio://` 改 `s3://` | 只改 ORM | `storage_migration.py` | schema unit；`KNOWLEDGE_SCHEMA_VERSION == 3` | 版本改回 2 后启动拒绝失败 | Passed |
| Compose 无 `graph`/`minio` 服务，有 `rustfs/rustfs:1.0.0-rc.5`；API 用 `S3_ENDPOINT`；Milvus `MINIO_ADDRESS=rustfs:9000` | 文档改了 compose 仍在 | `docker-compose.yml` | compose unit | 恢复 `minio:` 服务块后失败 | Passed |
| lock 无 `neo4j`/`networkx`/`@antv/g6`；镜像清单无 `neo4j:`/`minio/minio:` | pyproject 删了 lock 仍钉住 | uv.lock；pnpm-lock；init/save 脚本 | compose/lock unit | 加回 minio 镜像行后失败 | Passed |
| 上传知识库文件、解析、私有图鉴权、`/minio/public/` 头像、前缀删除、重启后 Milvus 检索均成功 | 只测了 bucket 创建 | `ObjectStoreClient`；Milvus | 真实 HTTP + 重启 Milvus 后 query | 切到空 RustFS 且不拷对象后检索失败必须被测到 | Not run：当前环境无 Compose 进程 |
| 架构与部署文档：shipping 无图谱/MinIO/Neo4j，有 RustFS Apache-2.0 与导图 | 代码删了许可证表仍列 MinIO | `ARCHITECTURE.md`；`deployment.md` | `verify_engineering_contracts.py`；`docs` `pnpm run build` | 恢复 MinIO AGPL 行后失败 | Passed |
