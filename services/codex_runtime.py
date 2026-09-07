"""Codex SDK 运行时封装。

本模块只负责普通 LLM 调用所需的基础设施：
1. 整个 Python 进程共享一个 Codex SDK 客户端；
2. 每次普通调用创建独立的临时线程，避免上下文串扰；
3. 强制 ChatGPT 登录、只读沙箱，并关闭联网搜索和本地 Shell；
4. 不设置硬超时，只定期输出已运行时间；
5. 仅对明确的 SDK、网络或子进程错误执行有限重试。

Preview 的联网搜索与逐电影多轮线程会在后续独立板块接入。
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import json
import tempfile
import threading
import time
from typing import Any

import config


class CodexRuntimeError(RuntimeError):
    """Codex SDK 运行时无法完成调用。"""


class CodexSDKUnavailableError(CodexRuntimeError):
    """当前 Python 环境没有可用的 Codex Python SDK。"""


class _ElapsedStatusReporter:
    """在调用阻塞期间定期打印耗时，不对任务施加硬超时。"""

    def __init__(self, interval_seconds: int):
        self.interval_seconds = max(1, int(interval_seconds))
        self._started_at = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=self._report_loop,
            name="codex-sdk-status",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _report_loop(self):
        while not self._stop_event.wait(self.interval_seconds):
            elapsed = int(time.monotonic() - self._started_at)
            print(f"   ⏳ Codex SDK 仍在处理中，已运行 {elapsed} 秒...")


@dataclass(frozen=True)
class CodexSearchTurn:
    """Preview 单轮搜索结果及工具使用证明。"""

    data: dict[str, Any]
    web_search_used: bool


class CodexRuntime:
    """进程级 Codex SDK 客户端及普通单轮调用入口。"""

    def __init__(self):
        self._client: Any | None = None
        self._sdk: dict[str, Any] | None = None
        self._temp_workspace: tempfile.TemporaryDirectory[str] | None = None
        self._client_lock = threading.RLock()
        # 首版业务流程为串行；锁同时防止未来多个 Agent 意外并发复用客户端。
        self._call_lock = threading.Lock()

    def think(self, prompt: str, system_prompt: str) -> str | None:
        """在全新临时线程中执行一次普通、不可联网的 LLM 调用。"""
        model, effort, max_retries, status_interval = self._resolve_settings()

        with self._call_lock:
            for attempt in range(max_retries + 1):
                try:
                    print(f"   🧠 Codex SDK ({model}, {effort}) 正在思考中...")
                    with _ElapsedStatusReporter(status_interval):
                        client = self._ensure_client()
                        sdk = self._load_sdk()
                        thread = client.thread_start(
                            approval_mode=sdk["ApprovalMode"].deny_all,
                            cwd=self._temp_workspace.name,
                            developer_instructions=self._build_developer_instructions(system_prompt),
                            ephemeral=True,
                            model=model,
                            sandbox=sdk["Sandbox"].read_only,
                        )
                        result = thread.run(
                            str(prompt),
                            effort=sdk["ReasoningEffort"](effort),
                        )

                    response = result.final_response
                    if isinstance(response, str) and response.strip():
                        return response

                    # 空响应属于模型结果问题，不属于 SDK/网络/进程异常，因此不自动重试。
                    print("❌ Codex SDK 调用失败: 返回内容为空")
                    return None
                except CodexSDKUnavailableError:
                    raise
                except Exception as exc:
                    if not self._is_retryable_error(exc):
                        raise CodexRuntimeError(str(exc)) from exc

                    if attempt >= max_retries:
                        raise CodexRuntimeError(
                            f"Codex SDK 调用失败，已重试 {max_retries} 次: {exc}"
                        ) from exc

                    retry_number = attempt + 1
                    print(
                        f"⚠️ Codex SDK 发生可重试错误: {exc}；"
                        f"正在进行第 {retry_number}/{max_retries} 次重试..."
                    )
                    if self._is_transport_error(exc):
                        self._reset_client()

        return None

    def create_preview_session(self, max_search_rounds: int = 3) -> "CodexPreviewSession":
        """为单部 Preview 电影创建一个可复用的 Live Web Search 线程。"""
        return CodexPreviewSession(self, max_search_rounds=max_search_rounds)

    def close(self):
        """关闭 App Server 子进程并清理隔离用的临时目录。"""
        with self._client_lock:
            client = self._client
            self._client = None
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

            workspace = self._temp_workspace
            self._temp_workspace = None
            if workspace is not None:
                workspace.cleanup()

    def _ensure_client(self):
        with self._client_lock:
            if self._client is not None:
                return self._client

            sdk = self._load_sdk()
            workspace = tempfile.TemporaryDirectory(prefix="little-red-codex-")
            try:
                # 关闭普通调用不需要的工具，从运行时层面落实“只生成文本、不碰项目文件”。
                codex_config = sdk["CodexConfig"](
                    cwd=workspace.name,
                    config_overrides=(
                        'forced_login_method="chatgpt"',
                        'web_search="disabled"',
                        'agents.enabled=false',
                        'features.apps=false',
                        'features.multi_agent=false',
                        'features.remote_plugin=false',
                        'features.shell_tool=false',
                        'features.unified_exec=false',
                        'tools.view_image=false',
                        'history.persistence="none"',
                    ),
                )
                client = sdk["Codex"](codex_config)
            except Exception:
                workspace.cleanup()
                raise

            self._temp_workspace = workspace
            self._client = client
            return client

    def _reset_client(self):
        """仅在传输/子进程故障后重建共享客户端。"""
        self.close()

    def _load_sdk(self) -> dict[str, Any]:
        if self._sdk is not None:
            return self._sdk

        try:
            from openai_codex import Codex, CodexConfig, Sandbox
            from openai_codex.api import ApprovalMode, ReasoningEffort
            from openai_codex.errors import CodexError, TransportClosedError
        except ModuleNotFoundError as exc:
            raise CodexSDKUnavailableError(
                "当前环境未安装 openai-codex，请先执行: pip install openai-codex"
            ) from exc

        self._sdk = {
            "Codex": Codex,
            "CodexConfig": CodexConfig,
            "Sandbox": Sandbox,
            "ApprovalMode": ApprovalMode,
            "ReasoningEffort": ReasoningEffort,
            "CodexError": CodexError,
            "TransportClosedError": TransportClosedError,
        }
        return self._sdk

    def _resolve_settings(self) -> tuple[str, str, int, int]:
        system_config = config.Strategy.System
        model = str(getattr(system_config, "CODEX_MODEL", "gpt-5.6-terra")).strip()
        effort = str(getattr(system_config, "CODEX_REASONING_EFFORT", "high")).strip().lower()
        max_retries = max(0, int(getattr(system_config, "CODEX_MAX_RETRIES", 2)))
        status_interval = max(
            1,
            int(getattr(system_config, "CODEX_STATUS_INTERVAL_SECONDS", 30)),
        )

        if not model:
            raise CodexRuntimeError("CODEX_MODEL 不能为空")

        allowed_efforts = {"none", "minimal", "low", "medium", "high", "xhigh"}
        if effort not in allowed_efforts:
            raise CodexRuntimeError(
                f"CODEX_REASONING_EFFORT 配置非法: {effort}；"
                f"可选值为 {sorted(allowed_efforts)}"
            )
        return model, effort, max_retries, status_interval

    def _build_developer_instructions(self, system_prompt: str) -> str:
        return (
            f"{str(system_prompt).strip()}\n\n"
            "运行约束：这是嵌入业务程序的纯文本生成调用。"
            "不得访问或修改文件，不得调用 Shell、图片工具、外部连接器或联网搜索；"
            "只根据用户提示中提供的信息完成任务，并直接返回最终答案。"
        )

    def _is_retryable_error(self, exc: Exception) -> bool:
        sdk = self._load_sdk()
        return isinstance(
            exc,
            (
                sdk["CodexError"],
                RuntimeError,  # SDK 会用 RuntimeError 表示明确的 turn failed 状态。
                ConnectionError,
                TimeoutError,
                ChildProcessError,
                OSError,
            ),
        )

    def _is_transport_error(self, exc: Exception) -> bool:
        sdk = self._load_sdk()
        return isinstance(
            exc,
            (
                sdk["TransportClosedError"],
                ConnectionError,
                ChildProcessError,
                BrokenPipeError,
                OSError,
            ),
        )


class CodexPreviewSession:
    """单部电影专用的 Codex Live Web Search 多轮会话。"""

    def __init__(self, runtime: CodexRuntime, max_search_rounds: int = 3):
        self._runtime = runtime
        self.max_search_rounds = max(1, int(max_search_rounds))
        self.rounds_used = 0
        self._thread: Any | None = None

    def search_json(self, prompt: str, output_schema: dict[str, Any]) -> CodexSearchTurn:
        """在同一电影线程中执行一轮搜索，并返回结构化结果。"""
        if self.rounds_used >= self.max_search_rounds:
            raise CodexRuntimeError(
                f"Preview 搜索轮次已达上限: {self.rounds_used}/{self.max_search_rounds}"
            )

        self.rounds_used += 1
        # 与普通 think() 共用同一把调用锁，保证首版严格串行访问 App Server。
        with self._runtime._call_lock:
            result = self._run_turn(str(prompt), output_schema)
        item_types = {
            str(getattr(getattr(item, "root", item), "type", ""))
            for item in result.items
        }
        web_search_used = "webSearch" in item_types
        data = self._parse_json_response(result.final_response)
        return CodexSearchTurn(data=data, web_search_used=web_search_used)

    def _run_turn(self, prompt: str, output_schema: dict[str, Any]):
        model, effort, max_retries, status_interval = self._runtime._resolve_settings()

        for attempt in range(max_retries + 1):
            try:
                print(
                    f"      🌐 [Codex-Web] 搜索第 {self.rounds_used}/{self.max_search_rounds} 轮 "
                    f"({model}, {effort})..."
                )
                with _ElapsedStatusReporter(status_interval):
                    thread = self._ensure_thread()
                    sdk = self._runtime._load_sdk()
                    return thread.run(
                        prompt,
                        effort=sdk["ReasoningEffort"](effort),
                        output_schema=output_schema,
                        sandbox=sdk["Sandbox"].read_only,
                    )
            except CodexSDKUnavailableError:
                raise
            except Exception as exc:
                if not self._runtime._is_retryable_error(exc):
                    raise CodexRuntimeError(str(exc)) from exc
                if attempt >= max_retries:
                    raise CodexRuntimeError(
                        f"Codex Preview 搜索失败，已重试 {max_retries} 次: {exc}"
                    ) from exc

                retry_number = attempt + 1
                print(
                    f"      ⚠️ [Codex-Web] 发生可重试错误: {exc}；"
                    f"正在进行第 {retry_number}/{max_retries} 次重试..."
                )
                if self._runtime._is_transport_error(exc):
                    # App Server 传输中断后只能重建客户端；当前电影的后续提示会携带完整已知字段。
                    self._runtime._reset_client()
                    self._thread = None

        raise CodexRuntimeError("Codex Preview 搜索未返回结果")

    def _ensure_thread(self):
        if self._thread is not None:
            return self._thread

        client = self._runtime._ensure_client()
        sdk = self._runtime._load_sdk()
        workspace = self._runtime._temp_workspace
        if workspace is None:
            raise CodexRuntimeError("Codex 临时工作目录未初始化")

        self._thread = client.thread_start(
            approval_mode=sdk["ApprovalMode"].deny_all,
            config={
                "web_search": "live",
                "tools": {"web_search": {"context_size": "high"}},
            },
            cwd=workspace.name,
            developer_instructions=(
                "你是 Preview 电影事实核查员。每一轮都必须使用 Codex 原生 Live Web Search；"
                "只能使用原生 Web Search，不得调用 Shell、文件、图片、应用、连接器、MCP、技能或子代理。"
                "优先采用片方、发行方、院线和其他一手来源；没有硬性域名白名单。"
                "所有非空事实都必须有来源 URL 支持；无法确认的字段必须返回空字符串，严禁猜测。"
                "只返回符合调用方 JSON Schema 的结果。"
            ),
            ephemeral=True,
            model=str(config.Strategy.System.CODEX_MODEL).strip(),
            sandbox=sdk["Sandbox"].read_only,
        )
        return self._thread

    def _parse_json_response(self, raw: str | None) -> dict[str, Any]:
        text = str(raw or "").strip()
        if not text:
            return {}
        clean = text.replace("```json", "").replace("```", "").strip()
        try:
            parsed = json.loads(clean)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


_shared_runtime: CodexRuntime | None = None
_shared_runtime_lock = threading.Lock()


def get_codex_runtime() -> CodexRuntime:
    """返回当前 Python 进程唯一的 CodexRuntime 实例。"""
    global _shared_runtime
    with _shared_runtime_lock:
        if _shared_runtime is None:
            _shared_runtime = CodexRuntime()
        return _shared_runtime


def close_codex_runtime():
    """供程序退出及测试显式释放 Codex App Server。"""
    global _shared_runtime
    with _shared_runtime_lock:
        runtime = _shared_runtime
        _shared_runtime = None
    if runtime is not None:
        runtime.close()


atexit.register(close_codex_runtime)
