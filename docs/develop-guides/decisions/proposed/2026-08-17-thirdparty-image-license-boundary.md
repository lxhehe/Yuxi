# 第三方镜像许可证边界与版本锁定

状态：proposed
类型：process
Owner：docker-compose.yml

Neo4j Community 与 MinIO 已从默认 shipping 拓扑删除，见 [2026-09-07-shipping-middleware-simplification](../implemented/2026-09-07-shipping-middleware-simplification.md)。本记录只覆盖仍在 Compose 中的第三方镜像许可证说明和 Redis 版本锁定。

## 问题

仓库通过 Compose、`docker/save_docker_images.*` 与 `scripts/init.*` 拉取并导出第三方镜像，Yuxi 本体是 MIT。缺少书面边界时，部署者与再分发者无法判断第三方许可证义务是否触发。`redis:7-alpine` 曾是浮动标签；Redis 自 7.4 起许可证由 BSD-3-Clause 变更为 RSALv2/SSPLv1（非 OSI）。浮动引用意味着部署取得的版本和许可证取决于拉取时间。

## 提案

把主要组件许可证、镜像内其他软件的独立许可和再分发义务写入 [deployment.md](../../../advanced/deployment.md) 的「第三方组件与许可证」章节，README 许可证节指向该章节。Redis 镜像引用统一锁定 `redis:7.4.10-alpine`。后续补丁升级必须显式修改对应引用。对象存储默认使用 RustFS Apache-2.0，见 2026-09-07 记录；本记录不再保留 Neo4j 或 MinIO。

## 替代方案

- 默认使用商业订阅镜像：需要商业协议与凭据，不应成为开源默认值。
- 锁定镜像 digest 而非版本 tag：可复现性最强，但可读性差且无法表达补丁升级意图，作为后续可选强化。
- 引入 CI 依赖与许可证审计：由独立事项承接。

## 验收标准

| 验收主张 | 失败面 | 语义 Owner | 直接证据 / 命令 | 负向案例 | 当前结果 |
|---|---|---|---|---|---|
| Redis 锁到包含 7.4.10 安全修复的版本 | 陈旧本地 tag 令验收错误选择 7.4.9 | `docker-compose.yml` | Redis 7.4.10 release；`docker buildx imagetools inspect redis:7.4.10-alpine` | 恢复 7.4.9 后，版本检查必须拒绝缺少安全修复的镜像 | Inspected |
| 全部 Redis shipping 引用保持一致 | Compose、初始化或离线导出脚本仍拉取旧版本 | `docker-compose.yml` 与对应脚本 | 精确搜索 Redis 引用；`docker compose config -q`（dev/prod） | 在任一脚本恢复旧版本后，残留搜索必须检出 | Passed |
| 许可证文档覆盖当前 Compose 镜像与再分发义务 | 把完整镜像统称为宽松许可证 | `docs/advanced/deployment.md` | 对照实际 Compose/导出清单 | 恢复“其余镜像均为宽松许可证”后，语义 Review 必须拒绝 | Inspected |
| 文档构建与工程契约检查不回归 | 决策生命周期、相对链接或文档构建失效 | `docs/` 与工程契约脚本 | docs `pnpm build`；`python3 scripts/verify_engineering_contracts.py` | 删除 proposed 的六字段矩阵后，工程契约检查必须失败 | Passed |

## 风险

精确补丁升级从隐式浮动变为显式提交评审。许可证章节只提供工程侧整理，不替代法务判断。
