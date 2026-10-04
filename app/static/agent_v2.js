"use strict";

(() => {
  const config = JSON.parse(document.getElementById("agent-config").textContent);
  const byId = (id) => document.getElementById(id);
  const limits = config.limits;
  const statusNames = { running: "执行中", completed: "已完成", failed: "执行失败", stopped: "已停止", interrupted: "重启中断" };
  const kindNames = { model: "模型请求", tool: "工具执行", guard: "边界校验", final: "报告校验" };
  const toolNames = { search_creators: "筛选创作者", quote_stats: "统计报价", search_knowledge: "检索知识", decision: "选择下一步", report: "最终报告", restart: "服务重启", stop: "停止执行" };
  const categories = { fitness: "健身", tech: "科技", lifestyle: "生活方式", all: "全部类别" };
  const markets = { US: "美国", UK: "英国", CA: "加拿大" };
  const fieldNames = { id: "创作者 ID", source_id: "来源 ID", name: "姓名", handle: "账号", platform: "平台", country: "市场", category: "类别", followers: "粉丝数", estimated_fee: "参考报价", currency: "币种", rule_score: "规则分", source_updated_at: "资料更新时间", source_label: "资料来源", count: "样本人数", min: "最低报价", max: "最高报价", median: "中位报价" };
  const defaultExamples = [
    "寻找适合健身新品合作的创作者，说明推荐依据、证据和需要核实的风险，并写一份英文沟通草稿。",
    "统计符合当前筛选条件的创作者报价，报告样本人数、最低价、最高价和中位数，并说明数据局限。",
    "检索创作者合作中广告披露与内容验收的知识资料，整理可执行的检查要点并引用来源。"
  ];
  let busy = false;
  let activeRun = null;
  let runs = [];
  let evidenceTargets = new Map();
  let savedRunVersion = 0;

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }

  function dateText(value) {
    if (!value) return "时间未提供";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function numberText(value) {
    return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN", { maximumFractionDigits: 2 }) : "未提供";
  }

  function valueText(key, value, currency = "USD") {
    if (value === undefined || value === null) return "未提供";
    if (key === "category") return categories[value] || String(value);
    if (key === "country") return markets[value] ? `${markets[value]} · ${value}` : String(value);
    if (["estimated_fee", "min", "max", "median"].includes(key)) return `${numberText(value)} ${currency}`;
    if (["followers", "rule_score", "count"].includes(key)) return numberText(value);
    if (typeof value === "object") return JSON.stringify(value, null, 2);
    return String(value);
  }

  function constraintText(constraints = {}) {
    return `${markets[constraints.market] || constraints.market || "未知市场"} · ${categories[constraints.category] || constraints.category || "未知类别"} · 单人预算 ≤ ${numberText(constraints.max_fee)} USD · 最多 ${numberText(constraints.count)} 位候选`;
  }

  function setBusy(value, message = "") {
    busy = value;
    byId("task-fields").disabled = value;
    byId("refresh-history").disabled = value;
    byId("approve-button").disabled = value || !activeRun || activeRun.status !== "completed" || activeRun.approved;
    document.querySelectorAll(".history-button").forEach((button) => { button.disabled = value; });
    byId("task-form").setAttribute("aria-busy", String(value));
    byId("run-button").textContent = value ? "请求处理中…" : "运行调研 →";
    byId("activity-message").hidden = !message;
    byId("activity-message").textContent = message;
  }

  function requestError(message) {
    byId("request-error").textContent = message;
    byId("request-error").hidden = !message;
  }

  async function request(url, options = {}) {
    const response = await fetch(url, options);
    let body;
    try { body = await response.json(); } catch { throw new Error(`服务返回无法读取的内容（HTTP ${response.status}）。任务输入已保留。`); }
    if (!response.ok) {
      const detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? "输入条件未通过校验，请检查任务、预算和人数。" : body.error || "请稍后重试。";
      throw new Error(`请求失败（HTTP ${response.status}）：${detail}`);
    }
    return body;
  }

  function errorText(error) {
    return error instanceof TypeError ? "无法连接服务。任务输入已保留；请检查服务状态后重试。" : error.message || "请求未成功。任务输入已保留，请稍后重试。";
  }

  function facts(data, keys) {
    const list = el("dl", undefined, "fact-grid");
    keys.forEach((key) => {
      if (data[key] === undefined) return;
      const item = el("div");
      item.append(el("dt", fieldNames[key] || key), el("dd", valueText(key, data[key], data.currency || "USD")));
      list.append(item);
    });
    return list;
  }

  function sources(refs) {
    const row = el("div", undefined, "source-row");
    row.append(el("span", "证据", "source-label"));
    if (!Array.isArray(refs) || !refs.length) row.append(el("span", "未提供引用", "source-label"));
    (Array.isArray(refs) ? refs : []).forEach((ref) => {
      const target = evidenceTargets.get(ref);
      if (!target) { row.append(el("span", `${ref}（本次无证据）`, "source-missing")); return; }
      const link = el("a", ref, "source-link");
      link.href = `#${target.id}`;
      link.setAttribute("aria-label", `查看证据 ${ref}`);
      link.addEventListener("click", () => { target.open = true; target.querySelector("summary").focus(); });
      row.append(link);
    });
    return row;
  }

  function renderEvidence(run) {
    const list = byId("evidence-list");
    list.replaceChildren();
    evidenceTargets = new Map();
    const entries = Object.entries(run.evidence || {});
    byId("evidence-count").textContent = `${entries.length} 条证据`;
    entries.forEach(([ref, data], index) => {
      const item = el("details", undefined, "evidence-item");
      item.id = `evidence-${run.id}-${index}`;
      const summary = el("summary");
      summary.append(el("span", ref, "evidence-code"), el("span", data.title || data.name || "证据记录"));
      item.append(summary);
      if (data.text) item.append(el("p", data.text, "evidence-text"));
      item.append(facts(data, Object.keys(data).filter((key) => !["title", "text", "constraints"].includes(key))));
      if (data.constraints) item.append(el("p", `查询边界：${constraintText(data.constraints)}`, "field-hint"));
      list.append(item);
      evidenceTargets.set(ref, item);
    });
    if (!entries.length) list.append(el("p", "本次尚未取得证据。", "field-hint"));
  }

  function reportSection(title) {
    const section = el("section", undefined, "report-section");
    section.append(el("h3", title));
    return section;
  }

  function renderReport(run) {
    const report = run.report;
    const complete = run.status === "completed" && !!report;
    byId("report-panel").hidden = !complete;
    byId("no-report-panel").hidden = complete;
    byId("report-content").replaceChildren();
    if (!complete) {
      byId("no-report-message").textContent = run.status === "running" ? "任务仍在执行。刷新历史记录可查看已保存的轨迹。" : "任务失败或停止，未形成经过校验的完整报告。下方保留已保存的轨迹与取得的证据；手动重跑将新建任务。";
      return;
    }
    const content = byId("report-content");
    content.append(el("p", report.summary, "report-summary"));
    const candidateSection = reportSection("候选创作者");
    (report.candidates || []).forEach((candidate) => {
      const data = (run.evidence || {})[`C${candidate.creator_id}`];
      const card = el("article", undefined, "candidate-card");
      const heading = el("div", undefined, "candidate-heading");
      heading.append(el("h4", data?.name || `创作者 #${candidate.creator_id}`));
      if (data?.handle) heading.append(el("span", data.handle, "creator-handle"));
      card.append(heading);
      if (data) card.append(facts(data, ["platform", "country", "category", "followers", "estimated_fee", "rule_score", "source_updated_at"]));
      else card.append(el("p", "本次证据缺少该候选的事实，请核对报告。", "error-message"));
      card.append(el("p", candidate.reason, "candidate-reason"), sources(candidate.sources));
      candidateSection.append(card);
    });
    if (!report.candidates?.length) candidateSection.append(el("p", "本次报告未推荐候选创作者。", "field-hint"));
    content.append(candidateSection);
    const findingSection = reportSection("调研发现");
    (report.findings || []).forEach((finding) => {
      const item = el("article", undefined, "finding-item");
      item.append(el("p", finding.claim), sources(finding.sources));
      findingSection.append(item);
    });
    if (!report.findings?.length) findingSection.append(el("p", "本次没有额外调研发现。", "field-hint"));
    content.append(findingSection);
    const riskSection = reportSection("需要人工核实");
    const risks = el("ul", undefined, "risk-list");
    (report.risks || []).forEach((risk) => { risks.append(el("li", risk)); });
    if (risks.childElementCount) riskSection.append(risks);
    else riskSection.append(el("p", "报告未列出风险；仍需人工核对事实与资料时效。", "field-hint"));
    content.append(riskSection);
    if (report.draft) {
      const draftSection = reportSection("沟通草稿 · 未发送");
      draftSection.append(el("pre", report.draft, "draft-text"));
      content.append(draftSection);
    }
    byId("approval-status").textContent = run.approved ? `已人工确认（未发送）${run.approved_at ? ` · ${dateText(run.approved_at)}` : ""}` : "报告待人工确认";
    byId("approve-button").hidden = !!run.approved;
    byId("approve-button").disabled = busy || !!run.approved;
  }

  function renderTrace(run) {
    const list = byId("trace-list");
    list.replaceChildren();
    const trace = run.trace || [];
    byId("trace-count").textContent = `${trace.length} 个已保存步骤`;
    trace.forEach((step, index) => {
      const item = el("li");
      const detail = el("details", undefined, "trace-step");
      const summary = el("summary");
      summary.append(el("span", `${step.step ?? index + 1}. ${kindNames[step.kind] || "执行步骤"} · ${toolNames[step.name] || step.name || "记录"}`, "trace-title"));
      const stepStatus = { success: "成功", completed: "完成", failed: "失败", error: "失败", stopped: "停止", running: "执行中", ok: "通过", pending: "待处理", rejected: "已拒绝" }[step.status] || "已记录";
      summary.append(el("span", stepStatus, `status-tag ${["failed", "error", "rejected"].includes(step.status) ? "status-failed" : ""}`));
      if (step.summary) summary.append(el("span", step.summary, "trace-description"));
      const body = el("div", undefined, "trace-detail");
      [["参数", step.arguments], ["结果", step.result]].forEach(([label, value]) => {
        body.append(el("h4", label), el("pre", value === undefined || value === null ? "无" : typeof value === "string" ? value : JSON.stringify(value, null, 2)));
      });
      detail.append(summary, body);
      item.append(detail);
      list.append(item);
    });
    if (!trace.length) list.append(el("li", "本次尚无已保存的执行步骤。", "field-hint"));
  }

  function renderUsage(run) {
    const list = byId("run-usage");
    list.replaceChildren();
    const usage = [
      ["模型请求", `${numberText(run.model_calls)} / ${limits.max_model_calls}`],
      ["工具执行", `${numberText(run.tool_calls)} / ${limits.max_tool_calls}`],
      ["耗时", typeof run.elapsed_ms === "number" ? `${numberText(run.elapsed_ms / 1000)} 秒` : "未提供"],
      ["输入 Token", `${numberText(run.input_tokens)}${run.usage_unknown ? "（未完整核实）" : ""}`],
      ["输出 Token", `${numberText(run.output_tokens)}${run.usage_unknown ? "（未完整核实）" : ""}`],
      [run.usage_unknown ? "已知部分估算费用" : "估算费用", run.provider === "mock" ? "模拟 · 无模型费用" : typeof run.cost_usd === "number" ? `${run.cost_usd.toFixed(6)} USD` : "未提供"]
    ];
    usage.forEach(([name, value]) => {
      const item = el("dl", undefined, "usage-item");
      item.append(el("dt", name), el("dd", value));
      list.append(item);
    });
    byId("usage-warning").hidden = !run.usage_unknown && !(run.provider !== "mock" && run.cost_usd === null);
    byId("usage-warning").textContent = "服务商未提供完整用量或费用；显示的计数不能证明账户实际支出。单次执行限额不是账户费用上限。";
  }

  function renderRun(run, moveFocus = false) {
    activeRun = run;
    byId("empty-state").hidden = true;
    byId("run-view").hidden = false;
    byId("run-title").textContent = `任务 #${run.id}`;
    byId("run-task").textContent = run.task;
    byId("run-constraints").textContent = constraintText(run.constraints);
    byId("run-meta").textContent = `${dateText(run.created_at)} · ${run.provider === "mock" ? "确定性模拟" : "DeepSeek 真实模型"}`;
    byId("run-status").textContent = statusNames[run.status] || "未知状态";
    byId("run-status").className = `status-tag status-${Object.hasOwn(statusNames, run.status) ? run.status : "unknown"}`;
    byId("run-error").hidden = !run.error;
    byId("run-error").textContent = run.error ? `执行说明：${run.error}` : "";
    renderUsage(run);
    renderEvidence(run);
    renderReport(run);
    renderTrace(run);
    renderHistory();
    if (moveFocus) byId("run-title").focus();
  }

  function renderHistory() {
    const list = byId("history-list");
    list.replaceChildren();
    runs.forEach((run) => {
      const item = el("li");
      const button = el("button", undefined, "history-button");
      button.type = "button";
      button.disabled = busy;
      if (activeRun?.id === run.id) button.setAttribute("aria-current", "true");
      button.append(el("span", run.task, "history-task"));
      const meta = el("span", undefined, "history-meta");
      meta.append(el("span", `#${run.id} · ${dateText(run.created_at)}`), el("span", `${statusNames[run.status] || "未知状态"}${run.approved ? " · 已确认" : ""}`));
      button.append(meta);
      button.addEventListener("click", () => { if (!busy) { requestError(""); renderRun(run, true); } });
      item.append(button);
      list.append(item);
    });
  }

  async function loadHistory() {
    const version = savedRunVersion;
    byId("refresh-history").disabled = true;
    try {
      const data = await request("/api/runs");
      if (!Array.isArray(data)) throw new Error("历史记录格式无法读取，请刷新后重试。");
      if (version !== savedRunVersion) return;
      runs = data;
      renderHistory();
      byId("history-message").textContent = runs.length ? "" : "还没有任务记录。运行第一个任务开始。";
      if (activeRun) {
        const latest = runs.find((run) => run.id === activeRun.id);
        if (latest) renderRun(latest);
      }
    } catch (error) {
      byId("history-message").textContent = `历史记录读取失败：${errorText(error)}`;
    } finally { byId("refresh-history").disabled = busy; }
  }

  function saveRun(run) {
    savedRunVersion += 1;
    runs = [run, ...runs.filter((item) => item.id !== run.id)].slice(0, 20);
    byId("history-message").textContent = "";
    renderRun(run, true);
  }

  document.querySelectorAll("[data-example]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.example);
      const example = config.examples?.[index];
      byId("task").value = (typeof example === "string" ? example : example?.task) || defaultExamples[index];
      byId("task").dispatchEvent(new Event("input"));
      byId("task").focus();
    });
  });
  byId("task").addEventListener("input", () => { byId("task-length").textContent = `${byId("task").value.length} / 2000`; });
  byId("refresh-history").addEventListener("click", () => { if (!busy) loadHistory(); });
  byId("task-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || !byId("task-form").reportValidity()) return;
    const task = byId("task").value.trim();
    if (!task) { requestError("请先填写具体任务，不能只输入空格。"); byId("task").focus(); return; }
    const payload = { task, market: byId("market").value, category: byId("category").value, max_fee: Number(byId("max-fee").value), count: Number(byId("count").value) };
    if (!Number.isFinite(payload.max_fee) || payload.max_fee < 0 || payload.max_fee > 10000 || !Number.isInteger(payload.count) || payload.count < 1 || payload.count > 5) { requestError("请输入有效的预算（0–10,000 USD）和候选人数（1–5）。"); return; }
    requestError("");
    setBusy(true, "任务执行中，请等待请求返回。完成或停止后显示已保存轨迹；期间请勿重复提交。");
    try { saveRun(await request("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })); }
    catch (error) { requestError(errorText(error)); }
    finally { setBusy(false); }
  });
  byId("approve-button").addEventListener("click", async () => {
    if (busy || !activeRun || activeRun.status !== "completed" || activeRun.approved) return;
    requestError("");
    setBusy(true, "正在记录人工确认；不会发送邮件。");
    try { saveRun(await request(`/api/runs/${activeRun.id}/approve`, { method: "POST" })); }
    catch (error) { requestError(errorText(error)); }
    finally { setBusy(false); }
  });
  loadHistory();
})();
