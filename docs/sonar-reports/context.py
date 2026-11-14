# -*- coding: utf-8 -*-
"""打印指定文件若干行区间，带行号；用于修复前的上下文核对。"""
import sys

path = sys.argv[1]
ranges = []
for spec in sys.argv[2:]:
    if '-' in spec:
        a, b = spec.split('-')
        ranges.append((int(a), int(b)))
    else:
        n = int(spec)
        ranges.append((n, n))

lines = open(path, encoding='utf-8').read().splitlines()
for a, b in ranges:
    print(f"===== {a}-{b} =====")
    for n in range(max(1, a), min(len(lines), b) + 1):
        print(f"{n:5d}| {lines[n-1]}")
    print()
