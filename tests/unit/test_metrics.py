"""Whole-host CPU percent for compare (design-rag.md §4.4.5 "Metrics")."""

from __future__ import annotations

from collections import namedtuple

from app.services.rag.metrics import cpu_percent

Linux = namedtuple("Linux", "user nice system idle iowait irq softirq steal")
Mac = namedtuple("Mac", "user nice system idle")


def linux(user, idle, iowait=0.0, system=0.0):
    return Linux(user, 0.0, system, idle, iowait, 0.0, 0.0, 0.0)


def test_one_window():
    a, b = linux(10, 100), linux(13, 101)  # 3 busy of 4
    assert cpu_percent([(a, b)]) == 75.0


def test_windows_are_summed_not_averaged():
    w1 = (linux(0, 0), linux(1, 0))  # 1 busy of 1
    w2 = (linux(0, 0), linux(1, 3))  # 1 busy of 4
    assert cpu_percent([w1, w2]) == 40.0  # 2 of 5, not mean(100, 25)


def test_iowait_counts_as_idle():
    a, b = linux(0, 0, iowait=0), linux(1, 1, iowait=2)
    assert cpu_percent([(a, b)]) == 25.0


def test_no_iowait_field():
    a, b = Mac(0, 0, 0, 0), Mac(1, 0, 1, 2)
    assert cpu_percent([(a, b)]) == 50.0


def test_zero_elapsed_is_zero():
    a = linux(5, 5)
    assert cpu_percent([(a, a)]) == 0.0
    assert cpu_percent([]) == 0.0


def test_one_decimal_and_clamped():
    a, b = linux(0, 0), linux(1, 2)
    assert cpu_percent([(a, b)]) == 33.3
    # A counter that went backwards must not produce a value outside 0-100
    assert 0.0 <= cpu_percent([(linux(5, 0), linux(0, 1))]) <= 100.0
