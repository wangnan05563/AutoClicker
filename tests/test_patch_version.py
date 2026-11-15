# -*- coding: utf-8 -*-
"""scripts/patch_version.py 构建版本号生成器单元测试。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import patch_version as pv

DAY1 = '20261115'
DAY2 = '20261116'


class PatchVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ac-patch-')
        os.makedirs(os.path.join(self.tmp, 'scripts'), exist_ok=True)
        self.pkg = os.path.join(self.tmp, 'package.json')
        self.state = os.path.join(self.tmp, 'scripts', '.build-version-state.json')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read_pkg(self):
        with open(self.pkg, encoding='utf-8') as f:
            return json.load(f)

    def _read_state(self):
        with open(self.state, encoding='utf-8') as f:
            return json.load(f)

    def test_creates_min_package_when_missing(self):
        result = pv.allocate_version(self.tmp, today=DAY1)
        self.assertEqual(result['version'], '20261115-001')
        self.assertTrue(result['created'])
        self.assertTrue(os.path.isfile(self.pkg))
        pkg = self._read_pkg()
        self.assertEqual(pkg['version'], '20261115-001')
        self.assertTrue(pkg['private'])
        self.assertIn('name', pkg)
        self.assertEqual(self._read_state(), {'date': DAY1, 'seq': 1})

    def test_increments_same_day(self):
        first = pv.allocate_version(self.tmp, today=DAY1)
        second = pv.allocate_version(self.tmp, today=DAY1)
        third = pv.allocate_version(self.tmp, today=DAY1)
        self.assertEqual(first['version'], '20261115-001')
        self.assertEqual(second['version'], '20261115-002')
        self.assertEqual(third['version'], '20261115-003')
        self.assertEqual(self._read_pkg()['version'], '20261115-003')
        self.assertEqual(self._read_state()['seq'], 3)

    def test_resets_next_day(self):
        pv.allocate_version(self.tmp, today=DAY1)
        pv.allocate_version(self.tmp, today=DAY1)
        result = pv.allocate_version(self.tmp, today=DAY2)
        self.assertEqual(result['version'], '20261116-001')
        self.assertEqual(self._read_state(), {'date': DAY2, 'seq': 1})

    def test_preserves_other_fields_and_indent(self):
        original = {
            'name': 'autoclicker',
            'version': '2.0.2',
            'scripts': {'test': 'python -m unittest'},
            'dependencies': {'left': '1.0.0'},
        }
        with open(self.pkg, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(original, ensure_ascii=False, indent=4) + '\n')
        pv.allocate_version(self.tmp, today=DAY1)
        pkg = self._read_pkg()
        self.assertEqual(pkg['version'], '20261115-001')
        self.assertEqual(pkg['scripts'], original['scripts'])
        self.assertEqual(pkg['dependencies'], original['dependencies'])
        with open(self.pkg, encoding='utf-8') as f:
            lines = f.read().splitlines()
        self.assertTrue(lines[1].startswith('    "'), '应保持 4 空格缩进')
        self.assertEqual(self._read_state(), {'date': DAY1, 'seq': 1})

    def test_recovers_from_missing_state(self):
        with open(self.pkg, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps({'name': 'x', 'version': '20261115-007'}, indent=2) + '\n')
        result = pv.allocate_version(self.tmp, today=DAY1)
        self.assertEqual(result['version'], '20261115-008')

    def test_dry_run_does_not_write(self):
        with open(self.pkg, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps({'name': 'x', 'version': '20261115-001'}, indent=2) + '\n')
        result = pv.allocate_version(self.tmp, today=DAY1, dry_run=True)
        self.assertEqual(result['version'], '20261115-002')
        self.assertEqual(self._read_pkg()['version'], '20261115-001')
        self.assertFalse(os.path.exists(self.state))

    def test_invalid_package_json_raises(self):
        with open(self.pkg, 'w', encoding='utf-8') as f:
            f.write('{ not json ')
        with self.assertRaises(ValueError):
            pv.allocate_version(self.tmp, today=DAY1)

    def test_sequence_zero_padding(self):
        versions = [pv.allocate_version(self.tmp, today=DAY1)['version'] for _ in range(10)]
        self.assertEqual(versions[8], '20261115-009')
        self.assertEqual(versions[9], '20261115-010')


class FormatTests(unittest.TestCase):
    def test_format_uses_three_digit_padding(self):
        self.assertEqual(pv._format_version('20261115', 1), '20261115-001')
        self.assertEqual(pv._format_version('20261115', 42), '20261115-042')
        self.assertEqual(pv._format_version('20261115', 1000), '20261115-1000')

    def test_version_pattern_is_strict_8_digits(self):
        self.assertTrue(pv.re.fullmatch(r'\d{8}-\d{3,}', pv._format_version('20261115', 5)))

    def test_random_uniqueness_within_day(self):
        """随机 50 次分配，版本号必须两两不同且保持递增。"""
        tmp = tempfile.mkdtemp(prefix='ac-patch-uniq-')
        try:
            os.makedirs(os.path.join(tmp, 'scripts'), exist_ok=True)
            seen = set()
            expected = 0
            for _ in range(50):
                result = pv.allocate_version(tmp, today=DAY1)
                self.assertNotIn(result['version'], seen)
                seen.add(result['version'])
                expected += 1
                self.assertEqual(result['seq'], expected)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
