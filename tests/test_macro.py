# -*- coding: utf-8 -*-
"""FR-13 宏 schema、录制与回放纯逻辑测试。"""
import json
import os
import tempfile
import unittest

from auto_clicker_layers import macro


def sample_steps():
    return [
        {'type': 'move', 'x': 100, 'y': 200},
        {'type': 'click', 'x': 100, 'y': 200, 'button': 'left', 'hold_ms': 0},
        {'type': 'wait', 'ms': 500},
        {'type': 'key', 'key': 'a', 'action': 'down'},
        {'type': 'key', 'key': 'a', 'action': 'up'},
        {'type': 'move', 'x': 300, 'y': 400},
        {'type': 'click', 'x': 300, 'y': 400, 'button': 'right', 'hold_ms': 20},
        {'type': 'wait', 'ms': 2000},
        {'type': 'key', 'key': 'enter', 'action': 'press'},
        {'type': 'wait', 'ms': 100},
    ]


class SchemaTests(unittest.TestCase):
    def test_make_and_validate_ten_steps(self):
        data = macro.make_macro('demo', sample_steps(),
                                {'left': 0, 'top': 0, 'width': 1920, 'height': 1080})
        self.assertEqual(data['schema'], macro.SCHEMA)
        self.assertEqual(len(data['steps']), 10)
        self.assertEqual(data['steps'][0]['type'], 'move')

    def test_manual_json_edit_is_still_valid(self):
        raw = {
            'schema': macro.SCHEMA,
            'name': '手改宏',
            'steps': [
                {'type': 'move', 'x': 10, 'y': 20},
                {'type': 'click', 'x': 10, 'y': 20},
                {'type': 'wait', 'ms': '250'},
                {'type': 'key', 'key': 'ctrl', 'action': 'down'},
                {'type': 'key', 'key': 'c', 'action': 'down'},
            ],
        }
        data = macro.validate_macro(raw)
        self.assertEqual(data['steps'][2]['ms'], 250)
        self.assertIsNone(data['screen'])

    def test_invalid_schema_and_empty_steps(self):
        with self.assertRaises(macro.MacroError):
            macro.validate_macro({'schema': 'other', 'name': 'x', 'steps': []})
        with self.assertRaises(macro.MacroError):
            macro.validate_macro({'schema': macro.SCHEMA, 'name': 'x', 'steps': []})

    def test_created_at_is_length_limited(self):
        data = macro.validate_macro({
            'schema': macro.SCHEMA, 'name': 'x', 'created_at': 'x' * 200,
            'steps': [{'type': 'move', 'x': 1, 'y': 2}]})
        self.assertEqual(len(data['created_at']), 64)

    def test_invalid_step_fields(self):
        with self.assertRaises(macro.MacroError):
            macro.validate_macro({
                'schema': macro.SCHEMA, 'name': 'x',
                'steps': [{'type': 'click', 'x': 1, 'y': 2, 'button': 'bad'}],
            })
        with self.assertRaises(macro.MacroError):
            macro.validate_macro({
                'schema': macro.SCHEMA, 'name': 'x',
                'steps': [{'type': 'wait', 'ms': 0}],
            })
        with self.assertRaises(macro.MacroError):
            macro.validate_macro({
                'schema': macro.SCHEMA, 'name': 'x',
                'steps': [{'type': 'key', 'key': '', 'action': 'down'}],
            })

    def test_screen_and_step_limit(self):
        with self.assertRaises(macro.MacroError):
            macro.validate_macro({
                'schema': macro.SCHEMA, 'name': 'x',
                'screen': {'left': 0, 'top': 0, 'width': 0, 'height': 10},
                'steps': [{'type': 'wait', 'ms': 1}],
            })
        with self.assertRaises(macro.MacroError):
            macro.validate_macro({
                'schema': macro.SCHEMA, 'name': 'x',
                'steps': [{'type': 'wait', 'ms': 1}] * (macro.MAX_STEPS + 1),
            })

    def test_name_sanitize_and_unique_path(self):
        self.assertEqual(macro.sanitize_macro_name('  a/b:c*?  '), 'a_b_c')
        with tempfile.TemporaryDirectory() as td:
            first = macro.unique_macro_path(td, 'demo')
            self.assertTrue(first.endswith('demo.json'))
            with open(first, 'w', encoding='utf-8') as handle:
                handle.write('{}')
            second = macro.unique_macro_path(td, 'demo')
            self.assertTrue(second.endswith('demo-2.json'))

    def test_duration_and_preview(self):
        data = macro.make_macro('demo', sample_steps())
        self.assertEqual(macro.format_duration(0), '0.000s')
        self.assertEqual(macro.format_duration(1500), '1.500s')
        self.assertEqual(macro.format_duration(61000), '1:01')
        preview = macro.preview_lines(data, limit=3)
        self.assertIn('move', preview)
        self.assertIn('共 10 步', preview)

    def test_recorder_updates_last_click_hold(self):
        rec = macro.MacroRecorder('hold', clock=lambda: 0.0)
        rec.start()
        self.assertTrue(rec.add_click(10, 20, 'left', 0))
        self.assertTrue(rec.update_last_click_hold(10, 20, 'left', 350))
        click_steps = [s for s in rec.steps if s.get('type') == 'click']
        self.assertEqual(click_steps[-1]['hold_ms'], 350)
        self.assertFalse(rec.update_last_click_hold(99, 99, 'left', 10))


class FileTests(unittest.TestCase):
    def test_save_load_roundtrip_and_atomic_temp_cleanup(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'demo.json')
            macro.save_macro(path, macro.make_macro('demo', sample_steps()))
            loaded = macro.load_macro(path)
            self.assertEqual(loaded['name'], 'demo')
            self.assertEqual(len(loaded['steps']), 10)
            self.assertFalse([n for n in os.listdir(td) if n.startswith('.macro-')])
            with open(path, 'r', encoding='utf-8') as handle:
                raw = json.load(handle)
            self.assertEqual(raw['schema'], macro.SCHEMA)

    def test_load_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, 'bad.json')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('{bad')
            with self.assertRaises(macro.MacroError):
                macro.load_macro(path)

    def test_list_macros_marks_bad_files(self):
        with tempfile.TemporaryDirectory() as td:
            macro.save_macro(os.path.join(td, 'good.json'),
                             macro.make_macro('good', [{'type': 'wait', 'ms': 50}]))
            with open(os.path.join(td, 'bad.json'), 'w', encoding='utf-8') as handle:
                handle.write('{}')
            entries = macro.list_macros(td)
            good = [e for e in entries if e['name'] == 'good'][0]
            bad = [e for e in entries if e['name'] == 'bad'][0]
            self.assertTrue(good['valid'])
            self.assertFalse(bad['valid'])
            self.assertTrue(bad['error'])


class RecorderTests(unittest.TestCase):
    def test_click_adds_move_and_gap(self):
        clock = [10.0]
        rec = macro.MacroRecorder('r', clock=lambda: clock[0])
        rec.start(now=10.0)
        self.assertTrue(rec.add_click(10, 20, 'left', 0, now=10.0))
        clock[0] = 10.25
        self.assertTrue(rec.add_key('a', 'down', now=10.25))
        data = rec.snapshot()
        self.assertEqual([s['type'] for s in data['steps']],
                         ['move', 'click', 'wait', 'key'])
        self.assertEqual(data['steps'][2]['ms'], 250)
        self.assertEqual(data['steps'][3]['action'], 'down')

    def test_pause_excludes_events_and_resume_resets_gap(self):
        clock = [20.0]
        rec = macro.MacroRecorder('r', clock=lambda: clock[0])
        rec.start(now=20.0)
        rec.add_key('a', 'down', now=20.0)
        rec.pause()
        rec.add_key('b', 'down', now=20.5)
        clock[0] = 30.0
        rec.resume(now=30.0)
        rec.add_key('a', 'up', now=30.0)
        data = rec.snapshot()
        self.assertEqual([s.get('key') for s in data['steps']], ['a', 'a'])
        self.assertEqual(data['steps'][1]['action'], 'up')

    def test_stop_ignores_later_events_and_max_steps(self):
        rec = macro.MacroRecorder('r', max_steps=4)
        rec.start(now=0)
        self.assertTrue(rec.add_click(1, 2, now=0))
        self.assertTrue(rec.add_click(3, 4, now=0.005))
        self.assertFalse(rec.add_click(5, 6, now=0.2))
        data = rec.snapshot()
        self.assertEqual(len(data['steps']), 4)
        self.assertFalse(rec.add_key('a', 'down', now=1.0))

    def test_add_wait_bounds(self):
        rec = macro.MacroRecorder('r')
        rec.start(now=0)
        self.assertTrue(rec.add_wait(100, now=0))
        with self.assertRaises(macro.MacroError):
            rec.add_wait(0, now=0)

    def test_long_gap_is_capped_and_flagged(self):
        rec = macro.MacroRecorder('r')
        rec.start(now=0)
        rec.add_key('a', 'press', now=0)
        rec.add_key('b', 'press', now=65.0)
        waits = [s for s in rec.steps if s['type'] == 'wait']
        self.assertEqual(waits, [{'type': 'wait', 'ms': macro.MAX_WAIT_MS}])
        self.assertEqual(rec.truncated_gap_ms, 65000)


class PlayerTests(unittest.TestCase):
    def test_ten_actions_in_order_and_progress(self):
        executed = []
        progress = []
        player = macro.MacroPlayer(
            macro.make_macro('demo', sample_steps()),
            lambda step: executed.append(step['type']),
            speed=2.0, wait=lambda seconds: None,
            on_progress=lambda *args: progress.append(args),
        )
        self.assertEqual(player.run(), 'finished')
        self.assertEqual(executed,
                         ['move', 'click', 'key', 'key', 'move', 'click', 'key'])
        self.assertEqual(len(progress), 10)
        self.assertEqual(progress[-1], (0, 9, 10))

    def test_loop_count_and_sequence(self):
        executed = []
        player = macro.MacroPlayer(
            macro.make_macro('loop', [
                {'type': 'key', 'key': 'a', 'action': 'press'},
                {'type': 'wait', 'ms': 20},
            ]),
            lambda step: executed.append(step['key']),
            loop_count=3, wait=lambda seconds: None,
        )
        player.run()
        self.assertEqual(executed, ['a', 'a', 'a'])

    def test_wait_scaled_by_speed_and_stop(self):
        waits = []
        player = macro.MacroPlayer(
            macro.make_macro('w', [{'type': 'wait', 'ms': 100}]),
            lambda step: None, speed=2.0, wait=lambda seconds: waits.append(seconds),
        )
        self.assertEqual(player.run(), 'finished')
        self.assertAlmostEqual(sum(waits), 0.05)
        player.stop()
        self.assertLessEqual(player._wait_ms(1000), False)

    def test_invalid_speed_and_loop_clamped(self):
        player = macro.MacroPlayer(
            macro.make_macro('x', [{'type': 'wait', 'ms': 10}]),
            lambda step: None, speed=9, loop_count=999, wait=lambda seconds: None)
        self.assertEqual(player.speed, macro.MAX_SPEED)
        self.assertEqual(player.loop_count, macro.MAX_LOOP_COUNT)
        player.run()


class HotkeyBindingTests(unittest.TestCase):
    """T06149 AC-19：三个宏各自绑定热键，回调独立投递到指定宏路径。"""

    class FakeKeyboard:
        def __init__(self):
            self.handlers = {}
            self.removed = []

        def add_hotkey(self, key, callback):
            if key in self.handlers:
                raise RuntimeError('duplicate hotkey ' + key)
            self.handlers[key] = callback

        def remove_hotkey(self, key):
            self.removed.append(key)
            self.handlers.pop(key, None)

    def test_three_macros_bind_independently(self):
        import queue
        from unittest import mock
        import auto_clicker_py3 as app_module
        tmp = tempfile.mkdtemp(prefix='ac-macro-hotkey-')
        paths = [LibraryTests._make(self, tmp, '宏%d' % i) for i in range(3)]
        keys = ['alt+1', 'alt+2', 'alt+3']
        app = object.__new__(app_module.AutoClicker)
        app.config = {
            'hotkey_start': 'f6', 'hotkey_emergency': 'f8',
            'macro_hotkeys': dict(zip(paths, keys)),
        }
        app._hotkey_queue = queue.Queue()
        app._hk_keys = []
        fake_kb = self.FakeKeyboard()
        with mock.patch.object(app_module, '_get_keyboard', return_value=fake_kb):
            app._register_hotkeys()
        self.assertEqual(app._hotkey_state['macro_keys'], keys)
        self.assertFalse(app._hotkey_state['macro_errors'])
        for key, path in zip(keys, paths):
            fake_kb.handlers[key]()
            self.assertEqual(app._hotkey_queue.get_nowait(), ('macro', path))


class LibraryTests(unittest.TestCase):
    def _make(self, directory, name='m1'):
        data = macro.make_macro(name, [
            {'type': 'click', 'x': 10, 'y': 20, 'button': 'left', 'hold_ms': 10},
        ])
        path = macro.unique_macro_path(directory, name)
        macro.save_macro(path, data)
        return path

    def test_rename_and_delete(self):
        tmp = tempfile.mkdtemp(prefix='ac-macro-lib-')
        path = self._make(tmp, '旧名')
        new_path, data = macro.rename_macro(path, '新名', tmp)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(new_path))
        self.assertEqual(data['name'], '新名')
        self.assertTrue(macro.delete_macro(new_path))
        self.assertFalse(os.path.exists(new_path))
        self.assertFalse(macro.delete_macro(new_path))

    def test_export_import(self):
        tmp = tempfile.mkdtemp(prefix='ac-macro-lib-')
        src = self._make(tmp, 'source')
        out = os.path.join(tempfile.mkdtemp(prefix='ac-macro-out-'), 'export.json')
        macro.export_macro(src, out)
        imported, data = macro.import_macro(out, tmp)
        self.assertTrue(os.path.exists(imported))
        self.assertEqual(data['name'], 'source')

    def test_recent_push_dedupes_and_caps(self):
        recent = []
        for i in range(6):
            recent = macro.push_recent(recent, '/tmp/m%d.json' % i,
                                       used_at='2026-11-23T12:0%d:00' % i)
        self.assertEqual(len(recent), 5)
        self.assertTrue(recent[0]['path'].endswith('m5.json'))
        recent = macro.push_recent(recent, '/tmp/m5.json', '2026-11-23T13:00:00')
        self.assertEqual(len(recent), 5)
        self.assertIn('2026-11-23 13:00', macro.recent_label(recent))


if __name__ == '__main__':
    unittest.main(verbosity=2)
