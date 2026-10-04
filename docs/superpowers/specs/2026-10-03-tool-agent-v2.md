# 创作者调研 Agent V2：已授权设计

用户授权直接完成成品与完整使用/学习文档，不再等待设计审批。

## 目的与范围

独立入口 app.agent_main:app，默认 8010 端口和 data/agent_v2.db。第一版入口、私有 .env、data/app.db 和已有修改不动。复用 FastAPI、SQLite、Pydantic、httpx、CSV清洗、硬规则评分、FTS5；不新增依赖。

自然语言任务搭配明确的市场、类别、单人 USD 预算和最多候选人数。结构化条件是强制边界，模型不得放宽。三个白名单只读工具：search_creators（查询符合条件的候选）；quote_stats（全体符合条件候选的报价统计）；search_knowledge(query)（最多三条资料）。模型选择工具和顺序，再输出经过结构校验、候选资格校验和证据ID成员校验的报告。没有自动邮件、真实抓取、任意SQL、任意文件或网页访问。

mock 是明确标记的确定性模拟编排；DeepSeek 按官方 tools/tool_calls/tool_call_id 协议执行真实模型选择，非思考模式。每次任务最多5次模型请求、8个工具执行，60秒总截止时间；不自动重试模型请求，用户手动重跑是新任务，可能再次收费。限额不是服务商账户总费用上限。

执行轨迹逐步存盘，不保存Key、HTTP原始异常或隐藏思考。状态 running/completed/failed/stopped；异常/超限保留轨迹与已取得的证据，不展示伪完成报告。重启将未完成 running 任务标为 interrupted（显示为 stopped），不能假装继续执行。只对 completed 报告提供“人工确认（未发送）”；不建立生产身份权限。

## 页面/API契约

- GET /：模板 agent_v2.html；context provider、model、examples、creators_count、limits。
- GET /health：status、llm_provider。
- POST /api/runs：TaskRequest JSON：task（1..2000字符）、market（US/UK/CA）、category（fitness/tech/lifestyle/all）、max_fee（有限非负数，USD，最多10000）、count（1..5）。默认US/fitness/1000/3。
- GET /api/runs：最近20个完整 RunView，JSON数组。
- GET /api/runs/{id}：完整 RunView。
- POST /api/runs/{id}/approve：仅completed，返回新 RunView；只是确认报告，不发送、不自动选人。
- RunView：id,task,constraints,provider,status,error,model_calls,tool_calls,input_tokens,output_tokens,usage_unknown,cost_usd,elapsed_ms,trace,evidence,report,approved,approved_at,created_at。
- trace元素：step,kind（model/tool/guard/final）,name,status,summary,arguments,result。
- report：summary,candidates（creator_id,reason,sources字符串数组）,findings（claim,sources）,risks字符串数组,draft字符串；错误时null。
- evidence：以C{创作者ID}/K{知识ID}/Q1为key的对象；各值含title、source_id及可见事实。创作者含name,handle,platform,country,category,followers,estimated_fee,currency,rule_score,source_updated_at；知识含text,source_label；报价含count,min,max,median,currency和constraints。

## 验收

三个典型任务走不同工具路径；名单满足代码硬条件，引用存在且来自本次执行。拒绝非法/未知工具与字段；重复调用有界停止；超时、协议错误、失败与服务重启可见。伪造ID、候选、放宽预算无法得到completed。API与UI不执行模型返回HTML/脚本。第一版测试保持通过。默认mock流程、5步学习练习、失败/恢复示例、真实API启动说明和诚实的面试讲法必须在文档中。
