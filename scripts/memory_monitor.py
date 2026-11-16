# -*- coding: utf-8 -*-
"""REQ-002 内存采样脚本：按 PID 采样 RSS，输出峰值/增长与 JSON。

用法：
  python scripts/memory_monitor.py --pid 1234 --duration 60 --interval 1 \
      --json memory_report.json --max-growth-mb 50

退出码：0 = 采样完成且增长未超过阈值；1 = 超过阈值/目标退出；2 = 参数或平台错误。
不依赖 psutil：Windows 用 GetProcessMemoryInfo，Linux 读 /proc/<pid>/status，macOS 用 ps。
"""
import argparse
import ctypes
import json
import os
import platform
import statistics
import subprocess
import sys
import time


def read_rss_bytes(pid):
    system = platform.system().lower()
    if system == 'windows':
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD),
                ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t),
            ]

        k32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        handle = k32.OpenProcess(0x0400 | 0x0010, False, int(pid))  # QUERY_INFORMATION | VM_READ
        if not handle:
            return None
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return None
            return int(counters.WorkingSetSize)
        finally:
            k32.CloseHandle(handle)
    if system == 'linux':
        try:
            with open('/proc/%d/status' % int(pid), encoding='utf-8') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        return int(line.split()[1]) * 1024
        except OSError:
            return None
        return None
    if system == 'darwin':
        try:
            out = subprocess.check_output(['ps', '-o', 'rss=', '-p', str(int(pid))],
                                          text=True).strip()
            return int(out) * 1024 if out else None
        except Exception:
            return None
    return None


def pid_exists(pid):
    if platform.system().lower() == 'windows':
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(pid))
        if handle:
            k32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--duration', type=float, default=60.0)
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--json', default='')
    parser.add_argument('--max-growth-mb', type=float, default=50.0)
    args = parser.parse_args()
    if args.interval <= 0 or args.duration <= 0:
        print('duration/interval 必须大于 0', file=sys.stderr)
        return 2

    samples = []
    start = time.time()
    missing_since = None
    while time.time() - start < args.duration:
        rss = read_rss_bytes(args.pid)
        if rss is None:
            if not pid_exists(args.pid):
                break
            missing_since = missing_since or time.time()
        else:
            missing_since = None
            samples.append({'t': round(time.time() - start, 3), 'rss_mb': round(rss / 1048576.0, 3)})
        time.sleep(args.interval)

    if len(samples) < 2:
        report = {'pid': args.pid, 'pass': False, 'reason': 'samples < 2',
                  'samples': samples}
    else:
        rs = [s['rss_mb'] for s in samples]
        baseline_n = max(1, min(5, len(rs) // 5 or 1))
        baseline = statistics.mean(rs[:baseline_n])
        final = statistics.mean(rs[-baseline_n:])
        growth = final - baseline
        peak = max(rs)
        report = {
            'pid': args.pid,
            'duration_seconds': round(time.time() - start, 2),
            'sample_count': len(samples),
            'baseline_mb': round(baseline, 3),
            'final_mb': round(final, 3),
            'growth_mb': round(growth, 3),
            'peak_mb': round(peak, 3),
            'max_growth_mb': args.max_growth_mb,
            'pass': growth <= args.max_growth_mb,
            'samples': samples,
        }
    if args.json:
        out_dir = os.path.dirname(os.path.abspath(args.json))
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir, exist_ok=True)
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'samples'},
                     ensure_ascii=False, indent=2))
    return 0 if report.get('pass') else 1


if __name__ == '__main__':
    sys.exit(main())
