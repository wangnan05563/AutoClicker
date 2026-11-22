# -*- coding: utf-8 -*-
"""构建脚本配置驱动逻辑的单元测试。"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import build_exe


class MergeTests(unittest.TestCase):
    def test_nested_dict_is_merged(self):
        base = {'build': {'clean_paths': ['release'], 'exe_name': 'A.exe'}}
        override = {'build': {'exe_name': 'B.exe'}}
        merged = build_exe._merge_section(base, override)
        self.assertEqual(merged['build']['clean_paths'], ['release'])
        self.assertEqual(merged['build']['exe_name'], 'B.exe')

    def test_scalar_is_overridden(self):
        self.assertEqual(build_exe._merge_section({'a': 1}, {'a': 2})['a'], 2)


class ConfigTests(unittest.TestCase):
    def test_load_build_config_has_required_sections(self):
        cfg = build_exe.load_build_config()
        self.assertIn('project', cfg)
        self.assertIn('build', cfg)
        self.assertIn('main_script', cfg['project'])
        self.assertIn('pyinstaller', cfg['build'])

    def test_abs_from_root(self):
        path = build_exe.abs_from_root('release')
        self.assertTrue(os.path.isabs(path))
        self.assertIn('AutoClicker', path)

    def test_resolve_icon_missing_returns_none(self):
        self.assertIsNone(build_exe._resolve_icon({'icon': 'icons/not-exist.ico'}))

    def test_resolve_icon_existing(self):
        icon = build_exe._resolve_icon({'icon': 'icons/autoclicker.ico'})
        self.assertIsNotNone(icon)
        self.assertTrue(os.path.isfile(icon))


class CommandTests(unittest.TestCase):
    def test_build_command_contains_required_flags(self):
        cfg = build_exe.load_build_config()
        pyi = cfg['build']['pyinstaller']
        cmd = build_exe._build_command(
            pyi, cfg['build'], cfg['project'], None, ['pyautogui'])
        self.assertIn('--name=AutoClicker', cmd)
        self.assertIn('--distpath', cmd)
        self.assertIn('--hidden-import', cmd)
        self.assertEqual(cmd[-1], cfg['project']['main_script'])

    def test_build_command_with_icon_and_data(self):
        pyi = {
            'module': 'PyInstaller',
            'flags': ['--onefile'],
            'add_data': [{'source': 'auto_clicker_py3.py', 'target': '.'}],
            'exclude_modules': ['tkinter'],
            'optional_hidden_imports': [],
        }
        cmd = build_exe._build_command(
            pyi, {'exe_name': 'AutoClicker.exe', 'dist_dir': 'release/dist',
                  'build_dir': 'release/build', 'spec_dir': 'scripts'},
            {'main_script': 'auto_clicker_py3.py'}, 'C:/icon.ico', [])
        self.assertIn('--icon', cmd)
        self.assertIn('--add-data', cmd)
        self.assertIn('--exclude-module', cmd)

    def test_collect_hidden_imports_keeps_declared(self):
        pyi = {'hidden_imports': ['pyautogui'], 'optional_hidden_imports': ['not_a_real_module_xyz']}
        hidden = build_exe._collect_hidden_imports(pyi)
        self.assertIn('pyautogui', hidden)
        self.assertNotIn('not_a_real_module_xyz', hidden)


class BuildVersionTests(unittest.TestCase):
    """打包入口必须先分配唯一版本号并写回根 package.json。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='ac-buildver-')
        self._old_root = build_exe.ROOT_DIR
        build_exe.ROOT_DIR = self.tmp

    def tearDown(self):
        build_exe.ROOT_DIR = self._old_root
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_apply_build_version_creates_package_json(self):
        version = build_exe.apply_build_version()
        self.assertRegex(version or '', r'^\d{8}-\d{3}$')
        with open(os.path.join(self.tmp, 'package.json'), encoding='utf-8') as f:
            pkg = json.load(f)
        self.assertEqual(pkg['version'], version)

    def test_apply_build_version_fails_on_invalid_package_json(self):
        with open(os.path.join(self.tmp, 'package.json'), 'w', encoding='utf-8') as f:
            f.write('{ broken json ')
        self.assertIsNone(build_exe.apply_build_version())

    def test_write_runtime_version_generates_importable_module(self):
        os.makedirs(os.path.join(self.tmp, 'auto_clicker_layers'), exist_ok=True)
        cfg = {'release': {'version': '2.0.2'}}
        build_exe._write_runtime_version(cfg, '20261122-007')
        path = os.path.join(self.tmp, 'auto_clicker_layers', 'version.py')
        self.assertTrue(os.path.isfile(path))
        ns = {}
        with open(path, encoding='utf-8') as f:
            exec(f.read(), ns)
        self.assertEqual(ns['APP_VERSION'], '2.0.2')
        self.assertEqual(ns['BUILD_ID'], '20261122-007')


if __name__ == '__main__':
    unittest.main(verbosity=2)
