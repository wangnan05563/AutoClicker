# -*- coding: utf-8 -*-
"""FR-03 诊断中心与脱敏诊断包纯逻辑测试。"""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clicker_layers import diagnostics


def base_context(home=None, crash_log=None):
    return {
        'home': home or os.path.expanduser('~'),
        'username': os.path.basename(os.path.normpath(home or os.path.expanduser('~'))),
        'app_version': '2.0.2',
        'build_id': '20261122-010',
        'python': '3.14.0',
        'platform': 'win32',
        'frozen': True,
        'executable': 'C:\\Users\\hspcadmin\\AppData\\Local\\Programs\\AutoClicker.exe',
        'input_ok': True,
        'input_session': 'windows',
        'input_backend': 'windows',
        'input_reason': '',
        'hotkeys': {
            'available': True, 'registered': True,
            'keys': ['f6', 'f8', 'esc'], 'start': 'f6',
            'emergency': 'f8', 'error': '',
        },
        'autostart': {
            'supported': True, 'enabled': False, 'registered': False,
            'path': '', 'path_exists': None, 'error': '',
        },
        'config_writable': True,
        'log_writable': True,
        'diag_writable': True,
        'config_dir': 'C:\\Users\\hspcadmin',
        'missing_resources': [],
        'icon_missing': False,
        'crash_log': crash_log or '',
        'dpi_scale': 1.25,
        'screen': '1920x1080',
        'config': {'hotkey_start': 'f6', 'hotkey_emergency': 'f8'},
    }


def check_map(report):
    return {item['id']: item for item in report['checks']}


class DiagnosticsChecksTests(unittest.TestCase):
    def test_healthy_context_all_ok(self):
        report = diagnostics.build_report(base_context(), now=None)
        self.assertEqual(report['schema'], diagnostics.SCHEMA)
        self.assertEqual(report['overall'], diagnostics.STATUS_OK)
        self.assertEqual(len(report['checks']), 8)
        self.assertEqual(check_map(report)['input']['status'], diagnostics.STATUS_OK)

    def test_wayland_guidance(self):
        ctx = base_context()
        ctx['platform'] = 'linux'
        ctx['input_ok'] = False
        ctx['input_session'] = 'wayland'
        ctx['input_reason'] = 'ydotool 未安装'
        report = diagnostics.build_report(ctx)
        item = check_map(report)['input']
        self.assertEqual(item['status'], diagnostics.STATUS_FAIL)
        self.assertIn('ydotool', item['fix'])
        self.assertIn('X11', item['fix'])

    def test_hotkey_conflict_guidance(self):
        ctx = base_context()
        ctx['hotkeys'] = {
            'available': True, 'registered': False,
            'keys': [], 'start': 'f6', 'emergency': 'f8',
            'error': 'failed to register hotkey',
        }
        item = check_map(diagnostics.build_report(ctx))['hotkey']
        self.assertEqual(item['status'], diagnostics.STATUS_FAIL)
        self.assertIn('F7', item['fix'])
        self.assertIn('冲突', item['fix'])

    def test_hotkey_same_key(self):
        ctx = base_context()
        ctx['hotkeys']['start'] = 'f6'
        ctx['hotkeys']['emergency'] = 'f6'
        item = check_map(diagnostics.build_report(ctx))['hotkey']
        self.assertEqual(item['status'], diagnostics.STATUS_FAIL)

    def test_autostart_enabled_but_missing(self):
        ctx = base_context()
        ctx['autostart'] = {
            'supported': True, 'enabled': True, 'registered': False,
            'path': '', 'path_exists': None, 'error': '',
        }
        item = check_map(diagnostics.build_report(ctx))['autostart']
        self.assertEqual(item['status'], diagnostics.STATUS_FAIL)
        self.assertIn('关闭', item['fix'])

    def test_autostart_points_missing_exe(self):
        ctx = base_context()
        ctx['autostart'] = {
            'supported': True, 'enabled': True, 'registered': True,
            'path': 'F:\\Program Files\\AutoClicker\\AutoClicker.exe',
            'path_exists': False, 'error': '',
        }
        item = check_map(diagnostics.build_report(ctx))['autostart']
        self.assertEqual(item['status'], diagnostics.STATUS_FAIL)
        self.assertIn('开启', item['fix'])

    def test_permission_failure(self):
        ctx = base_context()
        ctx['config_writable'] = False
        item = check_map(diagnostics.build_report(ctx))['permission']
        self.assertEqual(item['status'], diagnostics.STATUS_FAIL)
        self.assertIn('权限', item['fix'])

    def test_packaging_missing(self):
        ctx = base_context()
        ctx['missing_resources'] = ['pywin32 (win32api)']
        item = check_map(diagnostics.build_report(ctx))['packaging']
        self.assertEqual(item['status'], diagnostics.STATUS_FAIL)
        self.assertIn('_internal', item['fix'])

    def test_five_error_classes_all_have_fix(self):
        ctx = base_context()
        ctx['input_ok'] = False
        ctx['input_session'] = 'wayland'
        ctx['hotkeys']['error'] = 'conflict'
        ctx['hotkeys']['registered'] = False
        ctx['autostart'] = {
            'supported': True, 'enabled': True, 'registered': False,
            'path': '', 'path_exists': None, 'error': '',
        }
        ctx['config_writable'] = False
        ctx['missing_resources'] = ['pywin32']
        report = diagnostics.build_report(ctx)
        failed = {item['id'] for item in report['checks']
                  if item['status'] == diagnostics.STATUS_FAIL}
        expected = {'input', 'hotkey', 'autostart', 'permission', 'packaging'}
        self.assertEqual(failed, expected)
        self.assertEqual(report['overall'], diagnostics.STATUS_FAIL)
        for item in report['checks']:
            if item['id'] in expected:
                self.assertTrue(item['fix'], item['id'])

    def test_crash_log_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            crash = os.path.join(tmp, 'crash.log')
            with open(crash, 'w', encoding='utf-8') as fh:
                fh.write('boom')
            report = diagnostics.build_report(base_context(crash_log=crash))
            item = check_map(report)['crash']
            self.assertEqual(item['status'], diagnostics.STATUS_WARN)
            self.assertEqual(report['overall'], diagnostics.STATUS_WARN)
            self.assertIn('诊断包', item['fix'])


class RedactionTests(unittest.TestCase):
    def test_redact_home_user_and_secret(self):
        text = ('路径 C:\\Users\\hspcadmin\\AppData\\Roaming\\AutoClicker\\x.json\n'
                'home /home/hspcadmin/.auto_clicker/log.txt\n'
                'user=hspcadmin token=abc123\n')
        result = diagnostics.redact_text(
            text, home='C:\\Users\\hspcadmin', username='hspcadmin')
        self.assertNotIn('hspcadmin', result)
        self.assertNotIn('abc123', result)
        self.assertIn('<用户目录>', result)
        self.assertIn('<已隐藏>', result)

    def test_config_whitelist_excludes_sensitive_target(self):
        config = {
            'ui_mode': 'advanced',
            'interval_seconds': 10,
            'click_area': {'x': 123, 'y': 456, 'width': 2, 'height': 3},
            'target_window_keyword': 'SecretExcelTitle',
            'multi_points': [{'x': 1, 'y': 2}],
            'profiles': {'work': {'target_window_keyword': 'Secret'}},
            'hotkey_start': 'f6',
            'password': 'should-not-export',
        }
        safe = diagnostics.sanitize_config(config)
        self.assertEqual(safe['ui_mode'], 'advanced')
        self.assertEqual(safe['hotkey_start'], 'f6')
        for key in ('click_area', 'target_window_keyword', 'multi_points',
                    'profiles', 'password'):
            self.assertNotIn(key, safe)
        text = json.dumps(safe, ensure_ascii=False)
        self.assertNotIn('SecretExcelTitle', text)
        self.assertNotIn('should-not-export', text)

    def test_read_tail_redacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'app.log')
            with open(path, 'w', encoding='utf-8') as fh:
                for i in range(10):
                    fh.write('line %d user=hspcadmin\n' % i)
            tail = diagnostics.read_tail(
                path, max_lines=3, home=tmp, username='hspcadmin')
            self.assertNotIn('hspcadmin', tail)
            self.assertIn('line 7', tail)
            self.assertNotIn('line 6', tail)

    def test_directory_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(diagnostics.directory_writable(tmp))
            self.assertTrue(diagnostics.directory_writable(
                os.path.join(tmp, 'not-yet-created')))
            self.assertFalse(diagnostics.directory_writable(
                os.path.join(tmp, 'missing-parent', 'sub')))


class PackageTests(unittest.TestCase):
    def test_write_package_contents_and_sanitization(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = diagnostics.build_report(base_context(
                home='C:\\Users\\hspcadmin'), now=None)
            report['app']['executable'] = 'C:\\Users\\hspcadmin\\AppData\\AutoClicker.exe'
            path = os.path.join(tmp, 'diag.zip')
            diagnostics.write_package(
                path,
                report,
                {'app.log': '日志 C:\\Users\\hspcadmin\\x token=abc123\n',
                 'crash.log': '/home/hspcadmin/crash\n'},
                {'ui_mode': 'advanced', 'click_area': {'x': 1, 'y': 2},
                 'target_window_keyword': 'SecretTitle'},
            )
            self.assertTrue(os.path.isfile(path))
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                self.assertTrue({'diagnostics.json', 'summary.txt',
                                 'config.json', 'manifest.json'} <= names)
                self.assertIn('logs/app.log.tail.txt', names)
                self.assertIn('logs/crash.log.tail.txt', names)
                diagnostics_text = zf.read('diagnostics.json').decode('utf-8')
                config_text = zf.read('config.json').decode('utf-8')
                summary_text = zf.read('summary.txt').decode('utf-8')
                log_text = zf.read('logs/app.log.tail.txt').decode('utf-8')
                manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
            self.assertTrue(manifest['sanitized'])
            for text in (diagnostics_text, config_text, summary_text, log_text):
                self.assertNotIn('hspcadmin', text)
                self.assertNotIn('abc123', text)
            self.assertNotIn('click_area', config_text)
            self.assertNotIn('SecretTitle', config_text)
            self.assertIn('AutoClicker 诊断摘要', summary_text)

    def test_package_name_unique(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = diagnostics.package_path(tmp, now=None)
            with open(first, 'wb') as fh:
                fh.write(b'x')
            second = diagnostics.package_path(tmp, now=None)
            self.assertNotEqual(first, second)
            self.assertTrue(second.endswith('.zip'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
