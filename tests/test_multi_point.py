# -*- coding: utf-8 -*-
"""T06159 多点序列：校验、排序、导入导出与预览映射。"""
import os
import tempfile
import unittest

from auto_clicker_layers import multi_point


class PointTests(unittest.TestCase):
    def test_normalize_rejects_bad_values(self):
        with self.assertRaises(multi_point.PointError):
            multi_point.normalize_points([{'x': 'a', 'y': 1}])
        with self.assertRaises(multi_point.PointError):
            multi_point.normalize_points('nope')
        with self.assertRaises(multi_point.PointError):
            multi_point.normalize_points([{'x': 1, 'y': 1}] * 201)

    def test_move_point_orders_without_mutating_input(self):
        points = [{'x': 1, 'y': 1}, {'x': 2, 'y': 2}, {'x': 3, 'y': 3}]
        moved = multi_point.move_point(points, 2, 0)
        self.assertEqual([p['x'] for p in moved], [3, 1, 2])
        self.assertEqual([p['x'] for p in points], [1, 2, 3])
        with self.assertRaises(multi_point.PointError):
            multi_point.move_point(points, 9, 0)

    def test_export_import_roundtrip(self):
        points = [{'x': 10, 'y': 20}, {'x': 30, 'y': 40}]
        tmp = tempfile.mkdtemp(prefix='ac-points-')
        path = os.path.join(tmp, 'points.json')
        multi_point.export_file(path, points)
        loaded = multi_point.import_file(path)
        self.assertEqual(loaded, points)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('{bad')
        with self.assertRaises(multi_point.PointError):
            multi_point.import_file(path)

    def test_preview_maps_and_clamps(self):
        bounds = {'left': -1920, 'top': 0, 'width': 3840, 'height': 1080}
        points = [{'x': -1920, 'y': 0}, {'x': 1920, 'y': 1080}]
        positions = multi_point.preview_positions(points, bounds, width=200, height=100)
        self.assertEqual(len(positions), 2)
        self.assertGreaterEqual(positions[0][0], 10)
        self.assertLessEqual(positions[1][0], 190)
        self.assertGreaterEqual(positions[1][1], 10)
        self.assertLessEqual(positions[1][1], 90)


if __name__ == '__main__':
    unittest.main()
