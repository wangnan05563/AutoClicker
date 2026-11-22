# -*- coding: utf-8 -*-
"""FR-27 取点遮罩纯逻辑测试：负坐标、多显示器、吸附与微调。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clicker_layers import picker


class PointTests(unittest.TestCase):
    bounds = (-1920, 0, 1280, 720)
    monitors = [(-1920, 0, 0, 720), (0, 0, 1280, 720)]

    def test_clamp_inside_virtual_screen(self):
        self.assertEqual(picker.clamp(-2500, -1920, 1279), -1920)
        self.assertEqual(picker.clamp(2500, -1920, 1279), 1279)
        self.assertEqual(picker.clamp(300, -1920, 1279), 300)

    def test_snap_outer_and_internal_monitor_edges(self):
        self.assertEqual(picker.snap_point(-1919, 300, self.bounds, self.monitors)[0], -1920)
        self.assertEqual(picker.snap_point(1276, 300, self.bounds, self.monitors)[0], 1279)
        self.assertEqual(picker.snap_point(-3, 300, self.bounds, self.monitors)[0], -1)
        self.assertEqual(picker.snap_point(4, 300, self.bounds, self.monitors)[0], 0)

    def test_snap_y_and_threshold_boundary(self):
        self.assertEqual(picker.snap_point(300, 7, self.bounds, self.monitors)[1], 0)
        self.assertEqual(picker.snap_point(300, 9, self.bounds, self.monitors)[1], 9)
        self.assertEqual(picker.snap_point(300, 715, self.bounds, self.monitors)[1], 719)

    def test_snap_can_be_disabled(self):
        self.assertEqual(picker.snap_point(-1917, 300, self.bounds, self.monitors, 0), (-1917, 300))

    def test_point_selection_is_one_pixel_and_snaps(self):
        selection = picker.point_selection(1276, 716, self.bounds, self.monitors)
        self.assertTrue(selection['point'])
        self.assertEqual((selection['x'], selection['y']), (1279, 719))
        self.assertEqual((selection['width'], selection['height']), (1, 1))

    def test_negative_origin_click(self):
        selection = picker.point_selection(-1500, 100, self.bounds, self.monitors)
        self.assertEqual((selection['x'], selection['y']), (-1500, 100))


class RectTests(unittest.TestCase):
    bounds = (-1920, 0, 1280, 720)
    monitors = [(-1920, 0, 0, 720), (0, 0, 1280, 720)]

    def test_drag_normalizes_any_direction(self):
        selection = picker.rect_selection(500, 400, 200, 100, self.bounds, self.monitors)
        self.assertFalse(selection['point'])
        self.assertEqual((selection['x'], selection['y']), (200, 100))
        self.assertEqual((selection['width'], selection['height']), (300, 300))

    def test_drag_near_edge_snaps_corners(self):
        selection = picker.rect_selection(4, 6, 1275, 713, self.bounds, self.monitors)
        self.assertEqual((selection['x'], selection['y']), (0, 0))
        self.assertEqual((selection['width'], selection['height']), (1279, 719))

    def test_tiny_drag_becomes_point_at_release_position(self):
        selection = picker.rect_selection(300, 300, 302, 303, self.bounds, self.monitors)
        self.assertTrue(selection['point'])
        self.assertEqual((selection['x'], selection['y']), (302, 303))
        self.assertEqual((selection['width'], selection['height']), (1, 1))

    def test_rect_spanning_negative_origin(self):
        selection = picker.rect_selection(-500, 100, 300, 400, self.bounds, self.monitors)
        self.assertEqual((selection['x'], selection['y']), (-500, 100))
        self.assertEqual((selection['width'], selection['height']), (800, 300))


class NudgeTests(unittest.TestCase):
    bounds = (-1920, 0, 1280, 720)

    def test_point_nudge_clamps_at_left_edge(self):
        selection = picker.point_selection(-1920, 0, self.bounds)
        moved = picker.nudge_selection(selection, -10, -10, self.bounds)
        self.assertEqual((moved['x'], moved['y']), (-1920, 0))
        moved = picker.nudge_selection(moved, 10, 10, self.bounds)
        self.assertEqual((moved['x'], moved['y']), (-1910, 10))

    def test_rect_nudge_keeps_size_and_clamps(self):
        selection = {'x': 1200, 'y': 650, 'width': 80, 'height': 70, 'point': False}
        moved = picker.nudge_selection(selection, 100, 100, self.bounds)
        self.assertEqual((moved['x'], moved['y']), (1200, 650))
        self.assertEqual((moved['width'], moved['height']), (80, 70))

    def test_invalid_selection_returns_none(self):
        self.assertIsNone(picker.nudge_selection(None, 1, 1, self.bounds))


class MagnifierTests(unittest.TestCase):
    bounds = (-1920, 0, 1280, 720)

    def test_center_box_is_five_by_five(self):
        self.assertEqual(picker.magnifier_box(100, 100, self.bounds), (98, 98, 103, 103))

    def test_box_insets_at_right_bottom(self):
        self.assertEqual(picker.magnifier_box(1279, 719, self.bounds), (1275, 715, 1280, 720))

    def test_even_size_is_promoted_to_odd(self):
        box = picker.magnifier_box(100, 100, self.bounds, 4)
        self.assertEqual(box, (98, 98, 103, 103))


if __name__ == '__main__':
    unittest.main(verbosity=2)
