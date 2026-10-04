# V1：Creator Ops Workbench

本文介绍第一版的固定工作流。跨平台安装与两个项目的对比请先读[仓库首页](README.md#快速启动)；第二版“创作者调研 Agent”见 [README_AGENT_V2.md](README_AGENT_V2.md)。两版共享底层模块，使用不同入口与默认数据库。

一个面向海外创作者营销团队的 AI 工作台演示项目：从项目 Brief、创作者数据清洗和可解释匹配，到英文外联草稿、人工审批、交付内容审核，再到模型日志与固定评测。

项目使用 FastAPI、SQLite、原生 HTML/CSS/JS。默认 `mock` 模式不需要 API Key，也不会联网；切换到 `deepseek` 后，才会调用真实模型。全部人物、品牌、邮箱和业务数据均为虚构内容。

## 五分钟启动

需要 Python 3.11 或更高版本。在项目根目录运行：

```bash
LLM_PROVIDER=mock bash ./run.sh
```

浏览器打开 `http://127.0.0.1:8000`。第一次演示按以下顺序操作：

上面的显式 `mock` 不会被已保存的 `.env` 改回真实模式；首次安装依赖可能联网，但不会调用模型。只运行 `./run.sh` 则仍按已有 `.env` 的模式启动，可能是 `deepseek`。命令行的 `LLM_PROVIDER` 和 `DB_PATH` 优先于配置文件。

1. 在“项目 Brief”确认目标与限制；
2. 在“创作者库”导入 `data/creators.csv`；
3. 在“智能匹配”运行规则筛选和 AI 解释排序；
4. 选择创作者，在“沟通与交付”生成英文外联草稿并人工批准；
5. 粘贴一段交付文案，运行内容审核；
6. 在“日志与评测”运行 20 个固定案例。

测试命令：

```bash
.venv/bin/python -m pytest -q
```

## 接入 DeepSeek

先复制配置文件：

```bash
cp -n .env.example .env
```

`-n` 保留已有文件，不覆盖已经填写的Key。编辑 `.env`：

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DB_PATH=data/app.db
```

然后重新运行 `bash ./run.sh`。此脚本适用于 macOS / Linux，Windows 参见首页的手动环境变量启动方式。`.env` 及其私有变体已被 Git 忽略；不要把 Key 写进代码、截图或提交记录。示例模型名请按服务商当前文档确认。

开发时曾抽样检查候选人评分解释、英文外联和内容审核三个真实 API 入口的接口与输出格式，不代表业务判断准确，也不代表当前服务商模型始终兼容。请求默认关闭思考模式，审核标签采用固定枚举。历史测试记录见 [`docs/DEEPSEEK_TEST_CN.md`](docs/DEEPSEEK_TEST_CN.md)。公开仓库不包含密钥和运行数据库。

本项目按输入 `$0.30 / 1M tokens`、输出 `$1.20 / 1M tokens` 的配置单价估算，重试各次已返回的用量会累计；未返回或异常的用量标记 `usage_unknown`，不能当作免费。模型名与价格可能变化，演示前查看[官方定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)和[Chat Completion 文档](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)。模型配置在 `.env`，估算单价目前在 `app/config.py`。导入示例后有 20 名合格候选，全量解释会调用 20 次；再做一份外联与审核，共 22 次，不含重试。排练优先用 mock，真实扣费以控制台为准。

## 为什么不是“套一层 API”

- 硬条件由确定性规则处理；修改输入会清除旧选择与评分，使旧草稿失效，模型返回后也复核输入是否变化；
- FTS5 只检索最多 3 条相关业务依据，降低无关上下文和成本；
- Pydantic 校验每个模型 JSON，失败时只重试一次；
- 外联只生成草稿，必须人工批准，演示版永不自动发信；
- 日志记录 Token、耗时、成本与安全错误类型，不保存异常原文、Key、完整 Prompt 或正文；
- 20 个固定案例检查 Top-1、标签召回/精确率和完全一致率；回归通过不代表真实业务准确率。

## 目录

```text
app/                       FastAPI 路由、业务逻辑、模板与静态资源
data/creators.csv          虚构创作者演示数据
data/knowledge.json        产品事实与合规知识
data/evaluation_cases.json 10 个匹配 + 10 个审核案例
docs/                      项目讲解、演示稿、面试问答与简历材料
tests/                     核心规则、API、模型、工作流与页面测试
```

## 安全边界

- 不抓取真实社媒数据；
- 不发送真实邮件；
- 不包含真实个人信息；
- 上传只接受不超过 1 MiB 的 CSV；预算必须有限，粉丝数必须能存入SQLite整数；过长CSV字段返回输入错误而不是服务器错误；
- 模型调用与批准前核对当前硬条件；输入修改后旧草稿保留为失效历史，不可再批准；
- 所有高影响动作保留人工确认点。

## 修复与剩余限制（2026-10-03）

本轮已修复旧状态、AI 重排、CSV 非有限数字/空值合并、重试用量、来源成员校验、异常脱敏、风险计数和评测盲点。验证记录见 [`docs/FIXES_CN.md`](docs/FIXES_CN.md)。

- 来源属于检索资料不代表资料支持结论；schema 通过也不证明事实。
- 审核只读取文字和链接字符串，不检查视频或链接内容；旧审核不会随 Brief 修改自动重新审核。
- mock 的医疗词、电池和首五秒政策仍是示例规则；改品牌名称不会替换知识库的产品事实。
- 尚无累计总预算控制、币种换算、登录权限和真实发信；评测仍是 20 个虚构案例。
- 以前的日志不会追溯补齐旧用量，真实模型完整评测尚未运行。

当前项目是本地演示，不是生产就绪系统。

2026-10-04的后续复查已修正输入溢出、异常Token用量和启动配置优先级，最新回归116项通过（V1 84项、V2 32项）。详见 [全套复查记录](docs/RECHECK_2026-10-04_CN.md)。历史交付记录保留原日期与当时数量。

## 常见问题

| 现象 | 原因与处理 |
|---|---|
| 提示缺少 `DEEPSEEK_API_KEY` | 当前是 `deepseek` 模式但未配置 Key；填写 `.env`，或改回 `LLM_PROVIDER=mock`。 |
| 返回余额不足或 402 | 到服务商控制台充值；面试前先用 mock 完整排练。 |
| 请求超时 | 检查网络，或提高 `DEEPSEEK_TIMEOUT_SECONDS`；应用会记录安全错误摘要。 |
| 模型返回格式错误 | 客户端会自动重试一次；仍失败则返回 502，不写入伪成功结果。 |
| 8000 端口被占用 | 免费练习运行 `LLM_PROVIDER=mock DB_PATH=data/practice.db .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8001`，再访问8001。 |
| 想恢复干净演示 | 停止练习服务后选一个尚未使用的数据库路径，例如 `LLM_PROVIDER=mock DB_PATH=data/practice-02.db ./run.sh`；不要删除原库。若该路径已有文件，会继续保留其历史，不是清空。 |

更完整的设计说明见 [`docs/PROJECT_GUIDE_CN.md`](docs/PROJECT_GUIDE_CN.md)，演示前直接照读 [`docs/DEMO_SCRIPT_CN.md`](docs/DEMO_SCRIPT_CN.md)。
