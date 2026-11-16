#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成/校验离线升级清单（T05250）。

用法：
    python scripts/release_manifest.py --exe release/dist/AutoClicker.exe
    python scripts/release_manifest.py --exe release/dist/AutoClicker.exe --verify

输出 release/manifest.json：版本号（package.json）、平台/架构、文件大小、SHA256、生成时间。
离线升级时，用户把新 exe 与清单一起拷入目标机，先 `--verify` 校验再替换。
"""

import argparse
import datetime
import hashlib
import json
import os
import platform
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_version(root=ROOT):
    path = os.path.join(root, 'package.json')
    try:
        with open(path, 'r', encoding='utf-8-sig') as f:
            return str((json.load(f) or {}).get('version') or '')
    except (OSError, ValueError) as exc:
        raise SystemExit('读取 package.json 失败: %s' % exc)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def make_manifest(exe_path, root=ROOT):
    if not os.path.isfile(exe_path):
        raise SystemExit('exe 不存在: %s' % exe_path)
    return {
        'schema': 1,
        'product': 'AutoClicker',
        'version': read_version(root),
        'platform': sys.platform,
        'arch': platform.machine(),
        'filename': os.path.basename(exe_path),
        'size': os.path.getsize(exe_path),
        'sha256': sha256_of(exe_path),
        'generated_at': datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
    }


def verify(manifest_path, exe_path):
    with open(manifest_path, 'r', encoding='utf-8-sig') as f:
        expected = json.load(f)
    actual = make_manifest(exe_path)
    errors = []
    for key in ('product', 'version', 'filename', 'size', 'sha256'):
        if expected.get(key) != actual.get(key):
            errors.append('%s: 期望 %r，实际 %r' % (key, expected.get(key), actual.get(key)))
    return errors


def main():
    parser = argparse.ArgumentParser(description='生成 AutoClicker 离线升级清单')
    parser.add_argument('--exe', required=True, help='待发布的 exe 路径')
    parser.add_argument('--out', default=os.path.join(ROOT, 'release', 'manifest.json'))
    parser.add_argument('--verify', action='store_true', help='按 --out 清单校验 --exe，不覆盖清单')
    args = parser.parse_args()
    exe = os.path.abspath(args.exe)
    if args.verify:
        errors = verify(os.path.abspath(args.out), exe)
        if errors:
            print('校验失败：')
            for e in errors:
                print(' -', e)
            raise SystemExit(1)
        print('校验通过：%s 与清单一致' % exe)
        return
    manifest = make_manifest(exe)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('已生成清单: %s' % os.path.abspath(args.out))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
