# 模型配置与验收

当前采用三个独立槽位，均通过 OpenAI 兼容的 `/chat/completions` 调用：

| 槽位 | 模型 | 用途 |
|---|---|---|
| `FAST_MODEL` | `agnes-3.0-flash` | 采集后的分类、标签、商业动态评估 |
| `ANALYSIS_MODEL` | `mimo-v2.6-pro` | 痛点分析、机会生成、问答 |
| `WRITING_MODEL` | `mimo-v2.6-pro` | 选题、大纲、初稿、改写、标题和平台版本 |

Agnes base URL 为 `https://api.agnes-ai.cn/v1`；MiMo 为 `https://token-plan-cn.xiaomimimo.com/v1`。
密钥仅配置在本地 `.env`，该文件已由 Git 忽略。`.env.example` 提供端点和模型 ID，密钥保持为空。
模型层直接读取 `.env`；同名进程环境变量优先，不需要额外执行 `load_dotenv`。

采集网络请求仍由 RSS/HTTP 适配器完成；模型负责对采集内容作评估，并没有新增浏览器采集 agent。
写作槽位未配置时才回退到分析槽位。向量模型保持本地哈希降级方案，后续可独立配置 `EMBEDDING_MODEL_*`。

2026-09-30 接口验收：Agnes Flash 与 MiMo Pro 返回 HTTP 200，支持项目的 JSON 请求；
该 MiMo 端点对 `mimo-v2.6` 返回 HTTP 400 / `Unsupported model`，因此分析也使用已验证可用的 Pro。
使用虚构素材和临时数据库跑通了真实改写 → 小红书版本 → HTML 导出，未修改已有稿件。
这验证接口与产品流程可用，不代表长文质量已完成验收。

修改配置后重启服务，在“设置”页面查看实际启用的模型。模型空内容会明确报错，
输出中素材未包含的数字会提示核实；该检查不能代替事实核查。

## Windows 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
cd frontend
npm ci
npm test
npm run build
cd ..
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\trendradar.exe serve
```

如果全局 npm 安装损坏，可直接运行 Node 安装目录中的 `npm.cmd`。
离线测试会隔离本地模型凭据，避免测试意外访问真实模型。
