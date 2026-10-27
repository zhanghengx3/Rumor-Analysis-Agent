# -*- coding: utf-8 -*-
"""
agent.log 日志分析脚本
自动汇总每次请求的 Token 消耗、LLM 调用次数、响应时间
"""
import re
import sys
from collections import defaultdict
from datetime import datetime

LOG_FILE = "agent.log"


def parse_log(path: str):
    """解析日志，按 session_id 聚合每次请求的数据"""
    requests = defaultdict(lambda: {
        "start_time": None,
        "end_time": None,
        "llm_calls": 0,
        "total_tokens": 0,
        "tool_calls": 0,
        "llm_durations": [],
    })

    # 匹配模式
    # [请求完成] session=xxx | 总Token=xxx   （/chat 路由）
    # [Agent完成] session=xxx | 耗时=xxx | LLM调用次数=xxx | 总Token=xxx   （/api/analyze 路由）
    # [LLM] 开始调用 | 第N次
    # [LLM] 完成 | 耗时: X.XXs | Token: XXX | 累计: XXX
    # [Tool] 调用: xxx
    pat_request_done = re.compile(
        r"\[(?:请求完成|Agent完成)\].*?session=(\S+).*?(?:耗时[=:]\s*([\d.]+)s)?.*?LLM调用(?:次数)?[=:]\s*(\d+).*?总Token[=:]\s*(\d+)"
    )
    pat_llm_start = re.compile(r"\[LLM\] 开始调用")
    pat_llm_end = re.compile(r"\[LLM\] 完成 \| 耗时:\s*([\d.]+)s \| Token:\s*(\d+)")
    pat_tool = re.compile(r"\[Tool\] 调用:")
    pat_timestamp = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

    current_session = None  # 用于追踪当前正在处理的请求（按时间顺序）

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 第一遍：提取所有带 session 的汇总行
    summary_lines = []
    for line in lines:
        m = pat_request_done.search(line)
        if m:
            ts_m = pat_timestamp.match(line)
            ts = ts_m.group(1) if ts_m else None
            session_id = m.group(1)
            duration = float(m.group(2)) if m.group(2) else None
            llm_calls = int(m.group(3))
            total_tokens = int(m.group(4))
            summary_lines.append({
                "timestamp": ts,
                "session_id": session_id,
                "duration": duration,
                "llm_calls": llm_calls,
                "total_tokens": total_tokens,
            })

    # 第二遍：按时间顺序统计 LLM 调用和工具调用，分配给最近的 summary
    session_idx = 0  # 当前正在填充哪个 summary
    for line in lines:
        ts_m = pat_timestamp.match(line)
        line_ts = ts_m.group(1) if ts_m else None

        # 遇到汇总行，跳到下一个 summary
        if any(pat_request_done.search(line) and m for m in [pat_request_done.search(line)] if m):
            if session_idx < len(summary_lines):
                session_idx += 1
            continue

        if session_idx >= len(summary_lines):
            break

        cur = summary_lines[session_idx]

        if pat_llm_start.search(line):
            cur.setdefault("llm_start_count", 0)
            cur["llm_start_count"] += 1

        if pat_tool.search(line):
            cur.setdefault("tool_call_count", 0)
            cur["tool_call_count"] += 1

    return summary_lines


def print_report(data: list):
    """打印汇总报表"""
    if not data:
        print("❌ 未在日志中找到任何请求记录，请确认 agent.log 路径正确且已有请求日志。")
        return

    print("=" * 80)
    print("📊 谣言分析智能体 - 请求性能报表")
    print("=" * 80)
    print(f"{'序号':<5} {'时间':<20} {'Session':<28} {'耗时(s)':<10} {'LLM调用':<8} {'Token':<8} {'工具调用':<8}")
    print("-" * 80)

    total_duration = 0
    total_tokens = 0
    total_llm_calls = 0
    valid_count = 0

    for i, row in enumerate(data, 1):
        duration = row["duration"] or 0
        tokens = row["total_tokens"]
        llm_calls = row["llm_calls"]
        tool_calls = row.get("tool_call_count", 0)
        ts = row["timestamp"] or "N/A"

        print(f"{i:<5} {ts:<20} {row['session_id']:<28} {duration:<10.2f} {llm_calls:<8} {tokens:<8} {tool_calls:<8}")

        if duration > 0:
            total_duration += duration
            valid_count += 1
        total_tokens += tokens
        total_llm_calls += llm_calls

    print("-" * 80)
    avg_duration = total_duration / valid_count if valid_count else 0
    avg_tokens = total_tokens / len(data) if data else 0
    avg_llm_calls = total_llm_calls / len(data) if data else 0

    print(f"\n📈 汇总统计（共 {len(data)} 次请求）")
    print(f"  平均响应时间:   {avg_duration:.2f} s")
    print(f"  平均 Token 消耗: {avg_tokens:.0f} tokens/请求")
    print(f"  平均 LLM 调用:   {avg_llm_calls:.1f} 次/请求")
    print(f"  累计 Token:      {total_tokens} tokens")
    print(f"  累计 LLM 调用:   {total_llm_calls} 次")
    print("=" * 80)


if __name__ == "__main__":
    log_path = sys.argv[1] if len(sys.argv) > 1 else LOG_FILE
    data = parse_log(log_path)
    print_report(data)