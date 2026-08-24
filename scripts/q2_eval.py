"""并行运行 Q2 的固定 seed 与多 seed 本地评估。"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import multiprocessing
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Union

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITS_DIR = REPO_ROOT / "commits"
DEFAULT_SEEDS = "cs188,0,1,2,3,4"
EXPECTED_Q2_LAYOUTS = 12
OUTPUT_TAIL_LIMIT = 8_000

# This runtime alias must stay compatible with Python 3.9.
Seed = Union[int, str]
Result = dict[str, Any]


@dataclass(frozen=True)
class EvalCase:
    """一个可独立执行并可跨进程传输的评估 case。"""

    index: int
    layout: str
    seed: Seed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def _parse_seeds(raw: str) -> list[Seed]:
    seeds: list[Seed] = []
    seen = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            raise argparse.ArgumentTypeError("seed 列表不能包含空项")
        if token == "cs188":
            seed: Seed = token
        else:
            try:
                seed = int(token)
            except ValueError as exc:
                raise argparse.ArgumentTypeError(
                    "seed 只能是 cs188 或整数"
                ) from exc
        identity = (type(seed).__name__, seed)
        if identity in seen:
            raise argparse.ArgumentTypeError(f"seed 重复：{token}")
        seen.add(identity)
        seeds.append(seed)
    if not seeds:
        raise argparse.ArgumentTypeError("至少需要一个 seed")
    return seeds


def _parse_agent_args(raw: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    if not raw:
        return parsed
    for item in raw.split(","):
        item = item.strip()
        if not item:
            raise argparse.ArgumentTypeError("agent 参数不能包含空项")
        key, separator, value = item.partition("=")
        key = key.strip()
        value = value.strip() if separator else "1"
        if not key:
            raise argparse.ArgumentTypeError("agent 参数名不能为空")
        if not value:
            raise argparse.ArgumentTypeError(
                f"agent 参数 {key!r} 的值不能为空"
            )
        if key in parsed:
            raise argparse.ArgumentTypeError(f"agent 参数重复：{key}")
        parsed[key] = value
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "从 commits/ 目录并行运行 Q2，每个 layout/seed case 都重新构造 "
            "agent，并输出 JSON 数据与 Markdown 汇总。"
        )
    )
    parser.add_argument(
        "--seeds",
        default=DEFAULT_SEEDS,
        help="逗号分隔的 seed；仅接受 cs188 或整数（默认：%(default)s）",
    )
    parser.add_argument(
        "--agent-args",
        default="strategy=alphabeta",
        help=(
            "传给 Q2_Agent 的逗号分隔参数（默认：%(default)s）；"
            "例如 strategy=mcts,mctsMaxSims=200"
        ),
    )
    parser.add_argument(
        "--jobs",
        type=_positive_int,
        default=12,
        help="并行 worker 进程数（默认：%(default)s）",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_int,
        default=30,
        help="每局 agent 总计算预算，单位秒（默认：%(default)s）",
    )
    parser.add_argument(
        "--layouts",
        help=(
            "可选的逗号分隔 Q2 布局文件名；省略时使用全部 "
            "layouts/q2_*.lay"
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="逐 case 数据和汇总信息的 JSON 输出路径",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        help="Markdown 汇总路径；默认与 --out 同名但扩展名为 .md",
    )
    return parser


def _validate_commits_cwd(parser: argparse.ArgumentParser) -> None:
    current = Path.cwd().resolve()
    expected = COMMITS_DIR.resolve()
    if current != expected:
        parser.error(
            "必须从 starter 的 commits/ 目录运行；请先执行：\n"
            f"  cd {expected}"
        )
    required = (
        expected / "pacman.py",
        expected / "agents" / "q2Agent.py",
        expected / "agents" / "randomGhost.py",
        expected / "layouts",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        parser.error("starter 文件缺失：" + ", ".join(missing))


def _resolve_layouts(raw: str | None) -> list[str]:
    layout_dir = COMMITS_DIR / "layouts"
    if raw is None:
        layouts = sorted(path.name for path in layout_dir.glob("q2_*.lay"))
        if len(layouts) != EXPECTED_Q2_LAYOUTS:
            raise argparse.ArgumentTypeError(
                "默认完整评估预期找到 "
                f"{EXPECTED_Q2_LAYOUTS} 张 Q2 布局，实际找到 {len(layouts)} 张"
            )
        return layouts

    layouts = []
    seen = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            raise argparse.ArgumentTypeError("layout 列表不能包含空项")
        name = Path(token).name
        if not name.endswith(".lay"):
            name += ".lay"
        if not name.startswith("q2_"):
            raise argparse.ArgumentTypeError(f"不是 Q2 布局：{token}")
        if name in seen:
            raise argparse.ArgumentTypeError(f"layout 重复：{name}")
        if not (layout_dir / name).is_file():
            raise argparse.ArgumentTypeError(f"layout 不存在：{name}")
        seen.add(name)
        layouts.append(name)
    if not layouts:
        raise argparse.ArgumentTypeError("至少需要一个 layout")
    return layouts


def _tail(text: str) -> str:
    if len(text) <= OUTPUT_TAIL_LIMIT:
        return text
    return "...[仅保留末尾输出]...\n" + text[-OUTPUT_TAIL_LIMIT:]


def _base_result(case: EvalCase, duration: float) -> Result:
    return {
        "case_index": case.index,
        "case_id": f"{case.seed}::{case.layout}",
        "layout": case.layout,
        "seed": case.seed,
        "status": "error",
        "outcome": "error",
        "score": None,
        "win": False,
        "loss": False,
        "draw": False,
        "timeout": False,
        "error": True,
        "remaining_food": None,
        "total_moves": None,
        "pacman_moves": None,
        "agent_time_seconds": None,
        "duration_seconds": duration,
        "error_type": None,
        "error_message": None,
        "traceback": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _is_timeout_exception(exc: Exception) -> bool:
    description = f"{type(exc).__name__}: {exc}".lower()
    return "timeout" in description or "timed out" in description


def _run_case(
    case: EvalCase,
    agent_args: dict[str, str],
    timeout: int,
) -> Result:
    """在 worker 内运行一个 case，并将所有异常转换为结构化结果。"""

    started = time.perf_counter()
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    game_state_class = None
    game = None
    caught_exception: Exception | None = None
    caught_traceback: str | None = None
    cleanup_error: str | None = None

    with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(
        stderr_buffer
    ):
        try:
            if Path.cwd().resolve() != COMMITS_DIR.resolve():
                raise RuntimeError(
                    f"worker cwd 必须是 {COMMITS_DIR}，实际是 {Path.cwd()}"
                )

            commits_path = str(COMMITS_DIR)
            if commits_path not in sys.path:
                sys.path.insert(0, commits_path)

            from agents.q2Agent import Q2_Agent
            from agents.randomGhost import RandomGhost
            from layout import getLayout
            from pacman import GameState, runGames
            from textDisplay import NullGraphics

            game_state_class = GameState
            GameState.getAndResetExplored()

            loaded_layout = getLayout(case.layout)
            if loaded_layout is None:
                raise FileNotFoundError(f"无法加载布局：{case.layout}")

            pacman_agent = Q2_Agent(**agent_args)
            ghost_agents = [
                RandomGhost(index)
                for index in range(1, loaded_layout.getNumGhosts() + 1)
            ]

            # RandomGhost 使用模块级 random；每个 case 在 runGames 前重置。
            random.seed(case.seed)
            games = runGames(
                layout=case.layout,
                pacman=pacman_agent,
                ghosts=ghost_agents,
                display=NullGraphics(),
                numGames=1,
                record=False,
                numTraining=0,
                catchExceptions=True,
                timeout=timeout,
            )
            if len(games) != 1:
                raise RuntimeError(
                    f"runGames 应返回 1 局，实际返回 {len(games)} 局"
                )
            game = games[0]
        except Exception as exc:  # noqa: BLE001
            # worker 必须把 case 错误带回主进程。
            caught_exception = exc
            caught_traceback = traceback.format_exc()
        finally:
            if game_state_class is not None:
                try:
                    game_state_class.getAndResetExplored()
                except Exception as exc:  # noqa: BLE001
                    cleanup_error = f"{type(exc).__name__}: {exc}"

    duration = time.perf_counter() - started
    result = _base_result(case, duration)
    result["stdout_tail"] = _tail(stdout_buffer.getvalue())
    result["stderr_tail"] = _tail(stderr_buffer.getvalue())

    if caught_exception is not None:
        timed_out = _is_timeout_exception(caught_exception)
        result.update(
            {
                "status": "timeout" if timed_out else "error",
                "outcome": "timeout" if timed_out else "error",
                "timeout": timed_out,
                "error": not timed_out,
                "error_type": type(caught_exception).__name__,
                "error_message": str(caught_exception),
                "traceback": caught_traceback,
            }
        )
        if cleanup_error:
            result["error_message"] = (
                f"{result['error_message']}; explored 清理失败：{cleanup_error}"
            )
        return result

    if game is None:
        result["error_message"] = "worker 未返回 Game 对象"
        return result

    state = game.state
    remaining_food = state.getNumFood()
    raw_win = bool(state.isWin())
    draw = raw_win and remaining_food > 0
    win = raw_win and not draw
    loss = bool(state.isLose())
    timed_out = bool(game.agentTimeout)
    crashed = bool(game.agentCrashed)

    if timed_out:
        status = "timeout"
        outcome = "timeout"
        error_message = f"agent 超过 {timeout} 秒整局计算预算"
    elif crashed:
        status = "error"
        outcome = "error"
        error_message = "starter 捕获到 agent 崩溃"
    elif win:
        status = "ok"
        outcome = "win"
        error_message = None
    elif draw:
        status = "ok"
        outcome = "draw"
        error_message = None
    elif loss:
        status = "ok"
        outcome = "loss"
        error_message = None
    else:
        status = "error"
        outcome = "error"
        error_message = "游戏结束但最终状态既非 win 也非 lose"

    agent_time = None
    if game.totalAgentTimes:
        agent_time = float(game.totalAgentTimes[0])
    move_history = game.moveHistory
    result.update(
        {
            "status": status,
            "outcome": outcome,
            "score": state.getScore(),
            "win": win,
            "loss": loss,
            "draw": draw,
            "timeout": timed_out,
            "error": status == "error",
            "remaining_food": remaining_food,
            "total_moves": len(move_history),
            "pacman_moves": sum(
                1 for agent_index, _ in move_history if agent_index == 0
            ),
            "agent_time_seconds": agent_time,
            "error_message": error_message,
        }
    )

    if cleanup_error:
        result.update(
            {
                "status": "error",
                "outcome": "error",
                "error": True,
                "error_type": "ExploredCleanupError",
                "error_message": f"explored 清理失败：{cleanup_error}",
            }
        )

    if status == "ok" and not cleanup_error:
        # 成功 case 无需在 JSON 中复制 runGames 的大段 moveHistory 输出。
        result["stdout_tail"] = ""
        result["stderr_tail"] = ""
    return result


def _worker_failure_result(case: EvalCase, exc: Exception) -> Result:
    result = _base_result(case, 0.0)
    result.update(
        {
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
        }
    )
    return result


def _average(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _aggregate(results: Sequence[Result]) -> Result:
    completed = [result for result in results if result["status"] == "ok"]
    scores = [float(result["score"]) for result in completed]
    wins = sum(result["outcome"] == "win" for result in completed)
    losses = sum(result["outcome"] == "loss" for result in completed)
    draws = sum(result["outcome"] == "draw" for result in completed)
    total = len(results)
    return {
        "cases": total,
        "completed": len(completed),
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "win_rate": wins / total if total else 0.0,
        "completed_win_rate": wins / len(completed) if completed else 0.0,
        "score_sum": sum(scores) if scores else None,
        "average_score": _average(scores),
        "median_score": statistics.median(scores) if scores else None,
        "timeouts": sum(bool(result["timeout"]) for result in results),
        "errors": sum(bool(result["error"]) for result in results),
        "duration_seconds": sum(
            float(result["duration_seconds"]) for result in results
        ),
    }


def _group_summary(
    results: Sequence[Result],
    field: str,
    order: Iterable[str | Seed],
) -> list[Result]:
    grouped = []
    for value in order:
        members = [result for result in results if result[field] == value]
        row = {field: value}
        row.update(_aggregate(members))
        grouped.append(row)
    return grouped


def _build_summary(
    results: Sequence[Result],
    layouts: Sequence[str],
    seeds: Sequence[Seed],
    wall_seconds: float,
) -> Result:
    overall = _aggregate(results)
    overall["wall_seconds"] = wall_seconds
    fixed_results = [
        result for result in results if result["seed"] == "cs188"
    ]
    integer_results = [
        result
        for result in results
        if isinstance(result["seed"], int)
    ]
    return {
        "overall": overall,
        "by_layout": _group_summary(results, "layout", layouts),
        "by_seed": _group_summary(results, "seed", seeds),
        "fixed_seed": {
            "overall": _aggregate(fixed_results),
            "by_layout": _group_summary(
                fixed_results,
                "layout",
                layouts,
            ),
        },
        "integer_seeds": {
            "overall": _aggregate(integer_results),
            "by_layout": _group_summary(
                integer_results,
                "layout",
                layouts,
            ),
        },
    }


def _format_number(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _markdown_escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _append_protocol_summary(lines, title, protocol):
    """Append one evaluation protocol's total and per-layout tables."""
    overall = protocol["overall"]
    if overall["cases"] == 0:
        return

    lines.extend(
        [
            "",
            f"## {title}",
            "",
            "| Case | 完成 | 胜 | 负 | 平 | 胜率 | 总分 | 平均分 | Timeout | Error |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {overall['cases']} | {overall['completed']} "
                f"| {overall['wins']} | {overall['losses']} "
                f"| {overall['draws']} "
                f"| {100.0 * overall['win_rate']:.2f}% "
                f"| {_format_number(overall['score_sum'])} "
                f"| {_format_number(overall['average_score'])} "
                f"| {overall['timeouts']} | {overall['errors']} |"
            ),
            "",
            "### 按布局",
            "",
            "| 布局 | Case | 完成 | 胜 | 胜率 | 平均分 | Timeout | Error |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in protocol["by_layout"]:
        lines.append(
            f"| {_markdown_escape(row['layout'])} | {row['cases']} "
            f"| {row['completed']} | {row['wins']} "
            f"| {100.0 * row['win_rate']:.2f}% "
            f"| {_format_number(row['average_score'])} "
            f"| {row['timeouts']} | {row['errors']} |"
        )


def _render_markdown(
    metadata: Result,
    summary: Result,
    results: Sequence[Result],
) -> str:
    lines = [
        "# Q2 并行评估汇总",
        "",
        f"- 生成时间：{metadata['generated_at_utc']}",
        f"- Git 基础提交：{metadata['git_commit']}",
        f"- 工作树干净：{metadata['working_tree_clean']}",
        f"- Agent SHA-256：{metadata['file_sha256']['q2_agent']}",
        f"- 评估脚本 SHA-256：{metadata['file_sha256']['eval_script']}",
        f"- Agent 参数：{_markdown_escape(metadata['agent_args_raw'])}",
        f"- Seeds：{_markdown_escape(','.join(map(str, metadata['seeds'])))}",
        f"- 并发进程：{metadata['jobs']}",
        f"- 单局预算：{metadata['timeout_seconds']}s",
    ]
    _append_protocol_summary(
        lines,
        "固定 seed（cs188）",
        summary["fixed_seed"],
    )
    _append_protocol_summary(
        lines,
        "整数 seeds（0–4）",
        summary["integer_seeds"],
    )

    overall = summary["overall"]
    lines.extend(
        [
            "",
            "## 全部请求合并",
            "",
            (
                f"- {overall['cases']} 个 case，{overall['wins']} 胜，"
                f"平均分 {_format_number(overall['average_score'])}，"
                f"timeout={overall['timeouts']}，error={overall['errors']}。"
            ),
            f"- 总墙钟时间：{_format_number(overall['wall_seconds'], 3)}s。",
        ]
    )

    lines.extend(
        [
            "",
            "## 按 seed",
            "",
            "| Seed | Case | 完成 | 胜 | 胜率 | 平均分 | Timeout | Error |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary["by_seed"]:
        lines.append(
            f"| `{_markdown_escape(row['seed'])}` | {row['cases']} "
            f"| {row['completed']} | {row['wins']} "
            f"| {100.0 * row['win_rate']:.2f}% "
            f"| {_format_number(row['average_score'])} "
            f"| {row['timeouts']} | {row['errors']} |"
        )

    failures = [result for result in results if result["status"] != "ok"]
    if failures:
        lines.extend(
            [
                "",
                "## Timeout 与错误",
                "",
                "| Case | 状态 | 类型 | 信息 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for result in failures:
            lines.append(
                f"| `{_markdown_escape(result['case_id'])}` "
                f"| {result['status']} "
                f"| {_markdown_escape(result['error_type'] or '—')} "
                f"| {_markdown_escape(result['error_message'] or '—')} |"
            )

    lines.append("")
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temporary_name = handle.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _git_status_short() -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return ["unknown"]
    return completed.stdout.splitlines()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _uv_version() -> str:
    try:
        completed = subprocess.run(
            ["uv", "--version"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _hard_timeout_seconds(timeout: int) -> float:
    """Allow framework overhead while bounding a wedged case process."""
    return max(timeout + 15.0, timeout * 1.5)


def _hard_timeout_result(
    case: EvalCase,
    duration: float,
    hard_timeout: float,
) -> Result:
    result = _base_result(case, duration)
    result.update(
        {
            "status": "timeout",
            "outcome": "timeout",
            "timeout": True,
            "error": False,
            "error_type": "WorkerProcessTimeout",
            "error_message": (
                f"case 进程墙钟时间超过 {hard_timeout:.1f} 秒"
            ),
        }
    )
    return result


def _worker_exit_result(
    case: EvalCase,
    duration: float,
    exit_code: int | None,
    message: str,
) -> Result:
    result = _base_result(case, duration)
    result.update(
        {
            "error_type": "WorkerProcessError",
            "error_message": f"{message}；exit_code={exit_code}",
        }
    )
    return result


def _run_case_process(connection, case, agent_args, timeout):
    """Run one case in a dedicated process and send one structured result."""
    try:
        result = _run_case(case, agent_args, timeout)
    except BaseException as exc:  # noqa: BLE001
        result = _worker_failure_result(case, exc)
    try:
        connection.send((case.index, result))
    finally:
        connection.close()


def _run_parallel(
    cases: Sequence[EvalCase],
    agent_args: dict[str, str],
    timeout: int,
    jobs: int,
) -> list[Result]:
    worker_count = min(jobs, len(cases))
    context = multiprocessing.get_context("spawn")
    results: dict[int, Result] = {}
    active = {}
    next_case = 0
    completed_count = 0
    hard_timeout = _hard_timeout_seconds(timeout)

    while len(results) < len(cases):
        while next_case < len(cases) and len(active) < worker_count:
            case = cases[next_case]
            next_case += 1
            parent_connection, child_connection = context.Pipe(
                duplex=False
            )
            process = context.Process(
                target=_run_case_process,
                args=(
                    child_connection,
                    case,
                    agent_args,
                    timeout,
                ),
            )
            try:
                process.start()
            except Exception as exc:  # noqa: BLE001
                parent_connection.close()
                child_connection.close()
                result = _worker_failure_result(case, exc)
                results[case.index] = result
                completed_count += 1
                print(
                    f"[{completed_count}/{len(cases)}] "
                    f"seed={case.seed} layout={case.layout} "
                    f"status={result['status']} score={result['score']}",
                    file=sys.stderr,
                    flush=True,
                )
                continue
            child_connection.close()
            active[case.index] = (
                process,
                parent_connection,
                time.perf_counter(),
                case,
            )

        finished = []
        for case_index, (
            process,
            connection,
            case_start,
            case,
        ) in tuple(active.items()):
            duration = time.perf_counter() - case_start
            result = None
            if connection.poll():
                try:
                    received_index, result = connection.recv()
                    if received_index != case_index:
                        raise RuntimeError(
                            "worker 返回的 case index 不匹配"
                        )
                except (EOFError, OSError, RuntimeError) as exc:
                    result = _worker_exit_result(
                        case,
                        duration,
                        process.exitcode,
                        str(exc),
                    )
            elif duration >= hard_timeout:
                process.terminate()
                result = _hard_timeout_result(
                    case,
                    duration,
                    hard_timeout,
                )
            elif not process.is_alive():
                process.join()
                if connection.poll(0.1):
                    try:
                        received_index, result = connection.recv()
                        if received_index != case_index:
                            raise RuntimeError(
                                "worker 返回的 case index 不匹配"
                            )
                    except (EOFError, OSError, RuntimeError) as exc:
                        result = _worker_exit_result(
                            case,
                            duration,
                            process.exitcode,
                            str(exc),
                        )
                else:
                    result = _worker_exit_result(
                        case,
                        duration,
                        process.exitcode,
                        "worker 未返回结构化结果",
                    )

            if result is None:
                continue

            process.join(timeout=1.0)
            if process.is_alive():
                process.terminate()
                process.join()
            connection.close()
            process.close()
            finished.append(case_index)
            case = cases[case_index]
            results[case_index] = result
            completed_count += 1
            print(
                f"[{completed_count}/{len(cases)}] "
                f"seed={case.seed} layout={case.layout} "
                f"status={result['status']} score={result['score']}",
                file=sys.stderr,
                flush=True,
            )
        for case_index in finished:
            del active[case_index]
        if not finished and len(results) < len(cases):
            time.sleep(0.02)

    return [results[index] for index in range(len(cases))]


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_commits_cwd(parser)

    try:
        seeds = _parse_seeds(args.seeds)
        agent_args = _parse_agent_args(args.agent_args)
        layouts = _resolve_layouts(args.layouts)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    json_path = args.out.resolve()
    markdown_path = (
        args.markdown_out.resolve()
        if args.markdown_out is not None
        else json_path.with_suffix(".md")
    )
    if json_path == markdown_path:
        parser.error("--out 与 --markdown-out 不能是同一路径")

    cases = [
        EvalCase(index=index, layout=layout, seed=seed)
        for index, (seed, layout) in enumerate(
            (seed, layout) for seed in seeds for layout in layouts
        )
    ]
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    results = _run_parallel(
        cases=cases,
        agent_args=agent_args,
        timeout=args.timeout,
        jobs=args.jobs,
    )
    wall_seconds = time.perf_counter() - started

    git_status = _git_status_short()
    file_sha256 = {
        "q2_agent": _sha256(COMMITS_DIR / "agents" / "q2Agent.py"),
        "eval_script": _sha256(Path(__file__).resolve()),
        "uv_lock": _sha256(REPO_ROOT / "uv.lock"),
    }
    reproduction_command = [
        "uv",
        "run",
        "--no-project",
        "--python",
        "3.9",
        "python",
        "../scripts/q2_eval.py",
        *sys.argv[1:],
    ]
    metadata: Result = {
        "schema_version": 2,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "started_at_utc": started_at.isoformat(),
        "repository_root": str(REPO_ROOT),
        "working_directory": str(Path.cwd().resolve()),
        "git_commit": _git_commit(),
        "git_status_short": git_status,
        "working_tree_clean": not git_status,
        "file_sha256": file_sha256,
        "uv_version": _uv_version(),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "process_argv": [
            sys.executable,
            str(Path(__file__).resolve()),
            *sys.argv[1:],
        ],
        "reproduction_command": reproduction_command,
        "agent_args_raw": args.agent_args,
        "agent_args": agent_args,
        "seeds": seeds,
        "layouts": layouts,
        "jobs": min(args.jobs, len(cases)),
        "requested_jobs": args.jobs,
        "timeout_seconds": args.timeout,
        "hard_timeout_seconds": _hard_timeout_seconds(args.timeout),
        "case_count": len(cases),
        "json_output": str(json_path),
        "markdown_output": str(markdown_path),
    }
    summary = _build_summary(results, layouts, seeds, wall_seconds)
    document = {
        "metadata": metadata,
        "summary": summary,
        "results": results,
    }
    markdown = _render_markdown(metadata, summary, results)
    _atomic_write(
        json_path,
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
    )
    _atomic_write(markdown_path, markdown)

    print(markdown)
    print(f"JSON：{json_path}")
    print(f"Markdown：{markdown_path}")

    overall = summary["overall"]
    if overall["timeouts"] or overall["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
