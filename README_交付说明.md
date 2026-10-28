# MyMultiAgent 教学项目 · 最终补全版源码交付说明

此包包含原始 42 个文件，并新增 `import_agent_logs_v2.py` 和 `setup_project.py`；`make_release.py` 更新为严格白名单打包器。无数据库、密钥、真实企业知识库、任务记录和日志。

## 在新 Mac 上安装（Python 3.12）

```bash
cd MyMultiAgent
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# 在本地编辑 .env，填写 API_KEY、BASE_URL、MODEL_NAME；不要上传真实 .env
python setup_project.py
python final_acceptance.py --json
python run_platform.py
```

若 Python 3.12 命令不可用，使用已安装的 Python 3.12 解释器路径创建虚拟环境。

## 知识库

将自己的 `.txt`、`.md` 文件放入 `knowledge_docs/`，然后运行：

```bash
python rag_kb.py index
```

需要 PDF/DOCX 时再安装：`python -m pip install -r requirements-optional.txt`。

## Token 费用估算

将 `token_prices.example.json` 复制为 `token_prices.json`，按真实模型名和计费单价填写。未配置时仍可记录 Token 用量，但费用可能为空。

## Agent 日志同步与性能页面

新补全的 `import_agent_logs_v2.py` 提供日志读取、执行实例去重、V2 数据库字段迁移和增量导入。`setup_project.py` 会先备份已存在的数据库，再初始化相关表。启动平台后 `agent_log_sync.py` 自动调用 V2 模块同步日志。可手动运行 `python import_agent_logs_v2.py` 检查导入。

## 注意

- 这是教学原型，不提供公网生产部署所需的认证、权限控制、网络隔离或多用户数据隔离。
- 没有 `.env` 和真实知识库时，不能完成依赖模型或 RAG 的端到端业务测试。
- 规则化评分不等于事实核验，安全规则过滤也不等于完整防注入防护。
- `quality_revision_attempts` 和 `rag_security_events` 可能在首次产生对应事件时才建表；没有记录时出现 WARN 不一定是错误。
- 源码打包器无法识别所有硬编码秘密；分享前需再次人工审查。
