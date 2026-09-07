# 知识导图

本页说明 Milvus 知识库的导图和示例问题。它面向管理员和需要查看结果的用户；文档导入和 API 见[文档导入与查询 API](./knowledge-base-api.md)，状态和存储边界见[知识库机制](../mechanisms/knowledge-base.md)。

知识图谱能力已经从 shipping 拓扑中删除。知识导图（`mindmap` / `get_mindmap` / markmap）仍保留。

## 知识导图

在知识库详情页的“知识导图”中生成或查看层次化导图。系统根据文件列表和元数据组织分类，最多使用 200 个文件；结果保存到知识库的 `mindmap` 字段，Agent 可以通过 `get_mindmap` 读取。

新增文件时可以执行增量更新；纯删除可以直接移除对应叶子节点，不需要再次调用模型。导图只说明文件的组织关系，不代表系统已经阅读或总结全部正文。要回答内容问题，仍需检索 chunk 或打开原文。

只读用户可以查看已经生成的导图。生成、增量更新和重置属于写操作，需要知识库管理权限。

## 示例问题

知识库详情页可以根据文件列表生成 `sample_questions`，供检索测试选择。示例问题适合快速检查入口是否可用，但不等于经过人工审核的评估基准。需要可比较的检索分数时，请使用[知识库评估](../intro/evaluation.md)并检查参考 chunk 和答案。

## API 入口

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/knowledge/databases/{kb_id}/mindmap` | 读取导图 |
| `GET` | `/api/knowledge/databases/{kb_id}/mindmap/diff` | 检查导图文件变更 |
| `POST` | `/api/knowledge/databases/{kb_id}/mindmap/generate` | 生成或更新导图 |

接口字段和权限以部署实例的 Swagger 页面为准。只读用户可以调用读取接口，不能通过改 URL 绕过管理权限。

## 源码和测试

- [知识库路由](https://github.com/xerrors/Yuxi/blob/main/backend/server/routers/knowledge_router.py)
- [导图工具](https://github.com/xerrors/Yuxi/blob/main/backend/package/yuxi/knowledge/utils/mindmap_utils.py)
- [知识库 unit tests](https://github.com/xerrors/Yuxi/tree/main/backend/test/unit/knowledge)
- [知识库 integration](https://github.com/xerrors/Yuxi/tree/main/backend/test/integration/api)
