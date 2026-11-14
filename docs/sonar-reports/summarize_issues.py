# -*- coding: utf-8 -*-
"""汇总 SonarQube issues JSON，输出按严重度/规则/文件的统计与明细。"""
import json
import sys
from collections import Counter, defaultdict

path = sys.argv[1] if len(sys.argv) > 1 else 'issues-before.json'
with open(path, encoding='utf-8-sig') as f:
    data = json.load(f)

issues = data.get('issues', [])
print(f"total={data.get('total')} returned={len(issues)}")

by_sev = Counter(i['severity'] for i in issues)
print('severity:', dict(by_sev))
by_type = Counter(i['type'] for i in issues)
print('type:', dict(by_type))

by_rule = Counter(i['rule'] for i in issues)
print('\n--- by rule ---')
for rule, n in by_rule.most_common():
    sample = next(i for i in issues if i['rule'] == rule)
    print(f"{n:3d}  {rule:16s} {sample['severity']:8s} {sample['type']:14s} {sample['message'][:100]}")

print('\n--- detail ---')
for i in sorted(issues, key=lambda x: ({'BLOCKER': 0, 'CRITICAL': 1, 'MAJOR': 2, 'MINOR': 3, 'INFO': 4}.get(x['severity'], 9), x['component'], x.get('line', 0))):
    comp = i['component'].split(':')[-1]
    print(f"{i['severity']:8s} {i['type']:14s} {i['rule']:14s} {comp}:{i.get('line', '?')}  {i['message']}")
    if i.get('line'):
        pass
print('\n--- files ---')
for comp, n in Counter(i['component'].split(':')[-1] for i in issues).most_common():
    print(f"{n:3d}  {comp}")
