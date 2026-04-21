from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4
from urllib.parse import urlparse

from jingyantai.cli import _default_budget, _persist_final_artifacts, build_controller
from jingyantai.config import Settings, hydrate_runtime_secret
from jingyantai.runtime.reporting import CitationAgent, Synthesizer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8091
PUBLIC_HOST = "0.0.0.0"

PHASE_LABELS = {
    "initialize": "初始化研究",
    "expand": "扩展候选",
    "deepen": "深入分析",
    "challenge": "交叉质疑",
    "decide": "判断是否继续",
    "stop": "结束",
    "queued": "排队中",
    "error": "运行出错",
}

STAGE_LABELS = {
    "start": "开始",
    "end": "完成",
}


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>竞研台 - 智能竞争调研</title>
  <style>
    :root {
      --bg: #eef3ef;
      --panel: #ffffff;
      --line: #d7dfd7;
      --text: #193226;
      --muted: #607364;
      --brand: #245f45;
      --brand-2: #3f8b63;
      --accent: #245f45;
      --accent-2: #3f8b63;
      --paper: #ffffff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
      background: radial-gradient(circle at top left, #f6fbf7, var(--bg));
      color: var(--text);
      line-height: 1.6;
    }
    .wrap {
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 24px 60px;
    }
    .hero {
      background: linear-gradient(145deg, #1f4f3a, #2d7454);
      color: #f3fbf5;
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 32px;
      box-shadow: 0 12px 40px rgba(22, 49, 35, 0.1);
      margin-bottom: 24px;
    }
    h1 {
      margin: 0 0 12px;
      font-size: 32px;
      line-height: 1.2;
    }
    .lede {
      margin: 0;
      color: rgba(243, 251, 245, 0.85);
      font-size: 16px;
    }
    .panel {
      margin-top: 24px;
      background: rgba(255, 255, 255, 0.15);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 20px;
      padding: 24px;
      backdrop-filter: blur(10px);
    }
    label {
      display: block;
      margin-bottom: 12px;
      font-size: 14px;
      color: rgba(243, 251, 245, 0.8);
      font-weight: 600;
      letter-spacing: 0.05em;
    }
    input {
      width: 100%;
      padding: 16px 20px;
      border-radius: 16px;
      border: 1px solid rgba(255, 255, 255, 0.3);
      background: rgba(255, 255, 255, 0.95);
      color: var(--text);
      font-size: 18px;
      outline: none;
      transition: all 0.2s;
    }
    input:focus {
      border-color: #fff;
      box-shadow: 0 0 0 4px rgba(255, 255, 255, 0.2);
    }
    .row {
      display: flex;
      gap: 12px;
      margin-top: 18px;
      flex-wrap: wrap;
    }
    button {
      border: 0;
      border-radius: 999px;
      padding: 12px 24px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }
    .primary {
      background: #ffffff;
      color: var(--brand);
      box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .primary:hover {
      transform: translateY(-2px);
      box-shadow: 0 6px 16px rgba(0,0,0,0.15);
    }
    .secondary {
      background: rgba(255, 255, 255, 0.1);
      color: #ffffff;
      border: 1px solid rgba(255, 255, 255, 0.4);
    }
    .secondary:hover {
      background: rgba(255, 255, 255, 0.2);
    }
    .ghost {
      background: transparent;
      color: rgba(243, 251, 245, 0.9);
      border: 1px solid rgba(255, 255, 255, 0.3);
    }
    .ghost:hover {
      background: rgba(255, 255, 255, 0.1);
    }
    .grid {
      display: grid;
      gap: 20px;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 24px;
      box-shadow: 0 12px 30px rgba(22, 49, 35, 0.04);
      transition: transform 0.2s;
    }
    .card h2 {
      margin: 0 0 16px;
      font-size: 18px;
      color: var(--brand);
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .card h2::before {
      content: "";
      display: inline-block;
      width: 4px;
      height: 18px;
      background: var(--brand-2);
      border-radius: 2px;
    }
    .meta {
      color: var(--text);
      font-size: 15px;
      line-height: 1.7;
    }
    .empty { color: var(--muted); font-style: italic; }
    .log {
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .log-item {
      margin-bottom: 12px;
      padding-bottom: 12px;
      border-bottom: 1px dashed var(--line);
      display: flex;
      align-items: flex-start;
      gap: 12px;
    }
    .log-item:last-child { border-bottom: 0; margin-bottom: 0; }
    .log-time {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      padding-top: 2px;
    }
    .log-phase {
      display: inline-block;
      padding: 2px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      color: #fff;
      background: var(--brand-2);
      white-space: nowrap;
    }
    .phase-expand { background: #3f8b63; }
    .phase-deepen { background: #2d7454; }
    .phase-challenge { background: #1f4f3a; }
    .phase-decide { background: #5a8e7a; }
    .phase-stop { background: #607364; }
    .phase-initialize { background: #88a896; }
    .log-message {
      color: var(--text);
      font-size: 14px;
      word-break: break-all;
    }
    .pill {
      display: inline-block;
      padding: 6px 12px;
      border-radius: 12px;
      background: #e2f0e6;
      color: #1f6a45;
      margin: 0 8px 8px 0;
      font-size: 13px;
      font-weight: 600;
      border: 1px solid #cce3d2;
    }
    pre {
      background: #10231a;
      color: #d5efe0;
      padding: 16px;
      border-radius: 14px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 13px;
      overflow-x: auto;
    }
    @media (max-width: 700px) {
      h1 { font-size: 26px; }
      .wrap { padding: 16px 16px 40px; }
      .hero, .card { padding: 20px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>竞研台</h1>
      <p class="lede">基于智能 Agent 的竞争调研分析系统。输入研究目标，系统将自动进行多轮深度检索、交叉质疑与综合研判。</p>
      <div class="panel">
        <label for="target">研究目标 (如：Claude Code)</label>
        <input id="target" value="Claude Code" placeholder="输入要调研的产品或公司名称..." />
        <div class="row">
          <button class="primary" id="startBtn">启动研究</button>
          <button class="secondary" id="refreshBtn">刷新状态</button>
          <button class="ghost" id="loadBtn">读取报告</button>
          <button class="ghost" id="rawReportBtn">最终报告</button>
          <button class="ghost" id="rawStateBtn">运行状态</button>
          <button class="ghost" id="rawProgressBtn">进度日志</button>
        </div>
      </div>
    </section>

    <section class="grid">
      <article class="card">
        <h2>运行状态</h2>
        <div id="status" class="meta empty">等待任务启动...</div>
      </article>
      <article class="card">
        <h2>当前阶段</h2>
        <div id="progress" class="meta empty">暂无进度。</div>
      </article>
      <article class="card">
        <h2>识别到的竞品</h2>
        <div id="competitors" class="empty">暂无结果。</div>
      </article>
      <article class="card">
        <h2>调研摘要与风险</h2>
        <div id="summary" class="meta empty">暂无报告摘要。</div>
      </article>
      <article class="card">
        <h2>系统判读结论</h2>
        <div id="outcome" class="meta empty">暂无诊断。</div>
      </article>
      <article class="card" style="grid-column: 1 / -1; min-height: 260px;">
        <h2>执行日志 (当前轮次)</h2>
        <ol id="roundLog" class="log"></ol>
      </article>
      <article class="card" style="grid-column: 1 / -1; min-height: 300px;">
        <h2>原始数据视图</h2>
        <div id="rawTitle" class="meta empty" style="margin-bottom: 12px;">点击上方按钮查看详细数据原文。</div>
        <pre id="rawData" style="white-space: pre-wrap; word-break: break-word;"></pre>
      </article>
    </section>
  </div>

  <script>
    let currentRunId = "";
    let poller = null;
    const PHASE_CLASS = {
      "初始化研究": "phase-initialize",
      "扩展候选": "phase-expand",
      "深入分析": "phase-deepen",
      "交叉质疑": "phase-challenge",
      "判断是否继续": "phase-decide",
      "结束": "phase-stop",
    };

    function setText(id, text, isHtml = false) {
      const node = document.getElementById(id);
      if (isHtml) node.innerHTML = text;
      else node.textContent = text;
      if (text) node.classList.remove("empty");
      else node.classList.add("empty");
    }

    function renderStatus(data) {
      if (!data) return;
      currentRunId = data.run_id || currentRunId;
      const lines = [
        `ID: ${data.run_id || "-"}`,
        `目标: ${data.target || "-"}`,
        `阶段: ${data.phase || "-"}`,
        `轮次: ${data.round_index ?? "-"}`,
        `状态: ${data.stop_reason || "深度执行中..."}`,
      ];
      setText("status", lines.join("\\n"));
    }

    function renderProgress(events) {
      const progressNode = document.getElementById("progress");
      const logNode = document.getElementById("roundLog");
      logNode.innerHTML = "";
      if (!events || events.length === 0) {
        progressNode.textContent = "暂无进度。";
        progressNode.classList.add("empty");
        logNode.innerHTML = '<li class="empty">暂无日志内容。</li>';
        return;
      }
      progressNode.classList.remove("empty");
      const currentEvent = events[events.length - 1];
      progressNode.textContent = `${currentEvent.phase_label || currentEvent.phase} ➔ ${currentEvent.stage_label || currentEvent.stage} ➔ ${currentEvent.message}`;
      
      const currentRound = currentEvent.round_index ?? 0;
      const roundEvents = events.filter(event => (event.round_index ?? 0) === currentRound);
      const seen = new Set();
      for (const event of roundEvents) {
        const signature = `${event.phase_label}|${event.stage_label}|${event.message}`;
        if (seen.has(signature)) continue;
        seen.add(signature);
        const li = document.createElement("li");
        li.className = "log-item";
        const phase = event.phase_label || event.phase;
        const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
        const badgeClass = PHASE_CLASS[phase] || "";
        li.innerHTML = `
          <span class="log-time">${time}</span>
          <span class="log-phase ${badgeClass}">${phase}</span>
          <span class="log-message"><strong>${event.stage_label || event.stage}</strong>：${event.message}</span>
        `;
        logNode.appendChild(li);
      }
    }

    function renderReport(report) {
      if (!report) return;
      const competitors = document.getElementById("competitors");
      competitors.innerHTML = "";
      const confirmed = report.confirmed_competitors || [];
      if (confirmed.length === 0) {
        competitors.textContent = "暂无结果。";
        competitors.classList.add("empty");
      } else {
        competitors.classList.remove("empty");
        for (const item of confirmed) {
          const span = document.createElement("span");
          span.className = "pill";
          span.textContent = item;
          competitors.appendChild(span);
        }
      }

      const uncertainty = report.key_uncertainties || [];
      const uncertaintyText = uncertainty.length === 0
        ? ""
        : "\\n\\n【关键不确定项】\\n" + uncertainty.map(item => typeof item === "string" ? "• " + item : JSON.stringify(item)).join("\\n");
      setText("summary", (report.target_summary || "暂无报告内容。") + uncertaintyText);
    }

    function renderOutcome(outcome) {
      if (!outcome) return;
      const lines = [
        `系统状态: ${outcome.status || "-"}`,
        `确认竞品数: ${outcome.confirmed_count ?? 0}`,
        `最后停留阶段: ${outcome.latest_phase || "-"}`,
        `停止因子: ${outcome.stop_reason || "执行中"}`,
        "",
        `核心决策路径: ${outcome.latest_plan || "无"}`,
      ];
      const diagnostics = outcome.recent_diagnostics || [];
      if (diagnostics.length > 0) {
        lines.push("", "最近系统诊断:");
        diagnostics.forEach((item, index) => lines.push(`${index + 1}. ${item}`));
      }
      setText("outcome", lines.join("\\n"));
    }

    async function postJson(url, payload) {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    async function getJson(url) {
      const response = await fetch(url);
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    async function startRun() {
      const target = document.getElementById("target").value.trim();
      if (!target) return;
      const result = await postJson("/api/run", { target });
      renderStatus(result.status);
      renderProgress(result.progress || []);
      renderReport(result.report || null);
      renderOutcome(result.outcome || null);
      if (poller) clearInterval(poller);
      poller = setInterval(refreshStatus, 2000);
    }

    async function refreshStatus() {
      if (!currentRunId) return;
      const result = await getJson(`/api/run/${encodeURIComponent(currentRunId)}`);
      renderStatus(result.status);
      renderProgress(result.progress || []);
      renderReport(result.report || null);
      renderOutcome(result.outcome || null);
      if (result.status && result.status.stop_reason && poller) {
        clearInterval(poller);
        poller = null;
      }
    }

    async function loadReport() {
      if (!currentRunId) return;
      const result = await getJson(`/api/report/${encodeURIComponent(currentRunId)}`);
      renderReport(result);
    }

    async function loadRaw(kind, title) {
      if (!currentRunId) return;
      const result = await getJson(`/api/raw/${encodeURIComponent(currentRunId)}?kind=${encodeURIComponent(kind)}`);
      setText("rawTitle", title);
      setText("rawData", result.content || "");
    }

    document.getElementById("startBtn").addEventListener("click", () => startRun().catch(err => alert(err.message)));
    document.getElementById("refreshBtn").addEventListener("click", () => refreshStatus().catch(err => alert(err.message)));
    document.getElementById("loadBtn").addEventListener("click", () => loadReport().catch(err => alert(err.message)));
    document.getElementById("rawReportBtn").addEventListener("click", () => loadRaw("report", "最终报告 (JSON)").catch(err => alert(err.message)));
    document.getElementById("rawStateBtn").addEventListener("click", () => loadRaw("state", "运行状态 (JSON)").catch(err => alert(err.message)));
    document.getElementById("rawProgressBtn").addEventListener("click", () => loadRaw("progress", "进度日志 (JSONL)").catch(err => alert(err.message)));
  </script>
</body>
</html>
"""


@dataclass
class JsonResponse:
    status: str
    body: bytes
    content_type: str = "application/json; charset=utf-8"


class WebApp:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress: dict[str, list[dict[str, Any]]] = {}
        self._status: dict[str, dict[str, Any]] = {}

    def get_response(self, path: str) -> JsonResponse:
        if path == "/":
            return JsonResponse(
                status="200 OK",
                body=INDEX_HTML.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )
        return self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def handle_request(self, method: str, path: str, body: bytes) -> JsonResponse:
        parsed = urlparse(path)
        if method == "GET" and parsed.path == "/":
            return self.get_response("/")
        if method == "HEAD" and parsed.path == "/":
            return JsonResponse(
                status="200 OK",
                body=b"",
                content_type="text/html; charset=utf-8",
            )
        if method == "POST" and parsed.path == "/api/run":
            payload = json.loads(body.decode("utf-8") or "{}")
            return self._start_run(str(payload.get("target", "")).strip())
        if method == "GET" and parsed.path.startswith("/api/run/"):
            run_id = parsed.path.rsplit("/", 1)[-1]
            return self._json_response(self._run_payload(run_id))
        if method == "GET" and parsed.path.startswith("/api/report/"):
            run_id = parsed.path.rsplit("/", 1)[-1]
            return self._json_response(load_report_summary(Settings().runs_dir, run_id))
        if method == "GET" and parsed.path.startswith("/api/raw/"):
            run_id = parsed.path.rsplit("/", 1)[-1]
            query = urlparse(path).query
            kind = "report"
            if "kind=" in query:
                kind = query.split("kind=", 1)[1].split("&", 1)[0]
            return self._json_response({"content": load_raw_artifact(Settings().runs_dir, run_id, kind)})
        return self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _start_run(self, target: str) -> JsonResponse:
        if not target:
            return self._json_response({"error": "target is required"}, status=HTTPStatus.BAD_REQUEST)
        run_id = self._spawn_run(target)
        with self._lock:
            status = dict(self._status[run_id])
        return self._json_response(
            {
                "status": status,
                "progress": [],
                "report": load_report_summary(Settings().runs_dir, run_id),
                "outcome": explain_status(status),
            }
        )

    def _run_payload(self, run_id: str) -> dict[str, Any]:
        settings = Settings()
        with self._lock:
            status = dict(self._status.get(run_id, {}))
            progress = list(self._progress.get(run_id, []))
        if not status:
            store = build_controller(settings).store
            state = store.load_state(run_id)
            status = summarize_state(state)
        return {
            "status": status,
            "progress": progress,
            "report": load_report_summary(settings.runs_dir, run_id),
            "outcome": explain_run_outcome(state) if "state" in locals() else explain_status(status),
        }

    def _spawn_run(self, target: str) -> str:
        run_id = f"web-{uuid4().hex[:8]}"
        with self._lock:
            self._status[run_id] = {
                "run_id": run_id,
                "target": target,
                "phase": "queued",
                "round_index": 0,
                "stop_reason": None,
            }
            self._progress[run_id] = []
        thread = threading.Thread(
            target=self._run_research,
            args=(run_id, target),
            daemon=True,
        )
        thread.start()
        return run_id

    def _run_research(self, run_id: str, target: str) -> None:
        settings = Settings()
        hydrate_runtime_secret(settings.api_key_env)

        def reporter(event: Any) -> None:
            payload = event.model_dump(mode="json")
            payload["phase_label"] = _label_phase(payload.get("phase"))
            payload["stage_label"] = _label_stage(payload.get("stage"))
            with self._lock:
                self._progress.setdefault(run_id, []).append(payload)
                self._status[run_id] = {
                    "run_id": run_id,
                    "target": target,
                    "phase": _label_phase(payload.get("phase")),
                    "round_index": payload.get("round_index", 0),
                    "stop_reason": payload.get("stop_reason"),
                }

        controller = build_controller(settings)
        controller.progress_reporter = reporter
        try:
            state = controller.run(target=target, budget=_default_budget())
            state.run_id = run_id
            if state.final_report is None:
                draft = Synthesizer().run(state)
                state.final_report = CitationAgent().run(state, draft)
            _persist_final_artifacts(controller, state)
            with self._lock:
                self._status[run_id] = summarize_state(state)
        except Exception as exc:
            with self._lock:
                self._status[run_id] = {
                    "run_id": run_id,
                    "target": target,
                    "phase": _label_phase("error"),
                    "round_index": 0,
                    "stop_reason": str(exc),
                }

    def _json_response(self, payload: Any, *, status: HTTPStatus = HTTPStatus.OK) -> JsonResponse:
        return JsonResponse(
            status=f"{status.value} {status.phrase}",
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )


def summarize_state(state: Any) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "target": state.target,
        "phase": _label_phase(getattr(state.current_phase, "value", state.current_phase)),
        "round_index": state.round_index,
        "stop_reason": state.stop_reason,
    }


def load_report_summary(runs_dir: Path, run_id: str) -> dict[str, Any]:
    report_path = Path(runs_dir) / run_id / "artifacts" / "final-report.json"
    if not report_path.exists():
        return {
            "run_id": run_id,
            "target_summary": "",
            "confirmed_competitors": [],
            "key_uncertainties": [],
            "citations": {},
        }
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    return {
        "run_id": run_id,
        "target_summary": payload.get("target_summary", ""),
        "confirmed_competitors": payload.get("confirmed_competitors", []),
        "key_uncertainties": payload.get("key_uncertainties", []),
        "citations": payload.get("citations", {}),
    }


def load_raw_artifact(runs_dir: Path, run_id: str, kind: str) -> str:
    base = Path(runs_dir) / run_id
    mapping = {
        "report": base / "artifacts" / "final-report.json",
        "state": base / "state.json",
        "progress": base / "artifacts" / "progress-log.jsonl",
    }
    path = mapping.get(kind)
    if path is None or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").rstrip()


def explain_status(status: dict[str, Any]) -> dict[str, Any]:
    if status.get("stop_reason"):
        return {
            "status": "已停止",
            "confirmed_count": 0,
            "latest_phase": status.get("phase"),
            "latest_plan": "",
            "stop_reason": status.get("stop_reason"),
            "recent_diagnostics": [],
        }
    return {
        "status": "运行中",
        "confirmed_count": 0,
        "latest_phase": status.get("phase"),
        "latest_plan": "",
        "stop_reason": None,
        "recent_diagnostics": [],
    }


def explain_run_outcome(state: Any) -> dict[str, Any]:
    confirmed = getattr(state, "final_report", None)
    confirmed_competitors = []
    if confirmed is not None:
        confirmed_competitors = list(getattr(confirmed, "confirmed_competitors", []) or [])
    latest_trace = state.traces[-1] if getattr(state, "traces", None) else None
    if state.stop_reason and not confirmed_competitors:
        status = "已停止，仍未确认出有效竞品"
    elif state.stop_reason:
        status = "已停止，已有可展示结果"
    else:
        status = "运行中"
    return {
        "status": status,
        "confirmed_count": len(confirmed_competitors),
        "latest_phase": _label_phase(getattr(getattr(latest_trace, "phase", None), "value", None)),
        "latest_plan": getattr(latest_trace, "planner_output", ""),
        "stop_reason": state.stop_reason,
        "recent_diagnostics": list(getattr(latest_trace, "diagnostics", [])[-4:]) if latest_trace else [],
    }


def _label_phase(phase: str | None) -> str:
    if phase is None:
        return "-"
    return PHASE_LABELS.get(str(phase), str(phase))


def _label_stage(stage: str | None) -> str:
    if stage is None:
        return "-"
    return STAGE_LABELS.get(str(stage), str(stage))


def make_app() -> WebApp:
    return WebApp()


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    app = make_app()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            response = app.handle_request("GET", self.path, b"")
            self._write_response(response)

        def do_HEAD(self) -> None:  # noqa: N802
            response = app.handle_request("HEAD", self.path, b"")
            self._write_response(response)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            response = app.handle_request("POST", self.path, body)
            self._write_response(response)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _write_response(self, response: JsonResponse) -> None:
            self.send_response(int(response.status.split(" ", 1)[0]))
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"jingyantai web ui: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def server_bind_address_from_env() -> tuple[str, int]:
    host = os.getenv("JINGYANTAI_WEB_HOST")
    port = os.getenv("JINGYANTAI_WEB_PORT")
    render_port = os.getenv("PORT")
    if render_port and not host:
        host = PUBLIC_HOST
    return host or DEFAULT_HOST, int(port or render_port or DEFAULT_PORT)


if __name__ == "__main__":
    host, port = server_bind_address_from_env()
    run_server(host=host, port=port)
