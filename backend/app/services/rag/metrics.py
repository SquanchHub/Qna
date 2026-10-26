"""Whole-host CPU busy percent for compare (design-rag.md §4.4.5 "Metrics").

psutil.cpu_times() reads /proc/stat, which Docker doesn't namespace, so the
figure includes Ollama's and Infinity's work (and any unrelated load).
"""

from __future__ import annotations

import psutil


def cpu_snapshot():
    return psutil.cpu_times()


def _idle(times) -> float:
    return times.idle + getattr(times, "iowait", 0.0)


def cpu_percent(windows) -> float:
    """100 × Σ(Δtotal − Δidle − Δiowait) / ΣΔtotal over (before, after) pairs,
    to 1 decimal and within 0–100; 0.0 when no time elapsed on the counters."""
    total = busy = 0.0
    for before, after in windows:
        d_total = sum(after) - sum(before)
        total += d_total
        busy += d_total - (_idle(after) - _idle(before))
    if total <= 0:
        return 0.0
    return round(min(max(100.0 * busy / total, 0.0), 100.0), 1)
