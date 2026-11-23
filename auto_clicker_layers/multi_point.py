# -*- coding: utf-8 -*-
"""T06159：多点序列的校验、排序、导入导出与预览坐标（纯逻辑）。"""
import json
import os
import tempfile

SCHEMA = 'autoclicker.multi-points/1'
MAX_POINTS = 200
LIMIT = 100000


class PointError(ValueError):
    """多点配置格式错误；消息面向用户。"""


def _point(raw):
    if not isinstance(raw, dict):
        raise PointError('点位必须是对象')
    try:
        x, y = int(raw.get('x')), int(raw.get('y'))
    except (TypeError, ValueError):
        raise PointError('点位坐标必须是整数')
    if abs(x) > LIMIT or abs(y) > LIMIT:
        raise PointError('点位坐标超出范围')
    return {'x': x, 'y': y}


def normalize_points(points):
    if points is None:
        return []
    if not isinstance(points, list):
        raise PointError('points 必须是数组')
    if len(points) > MAX_POINTS:
        raise PointError('点位最多 %d 个' % MAX_POINTS)
    return [_point(p) for p in points]


def move_point(points, source, target):
    """返回新列表，把 source 移到 target；非法索引抛 PointError。"""
    clean = normalize_points(points)
    if not clean:
        return []
    if source < 0 or source >= len(clean) or target < 0 or target >= len(clean):
        raise PointError('拖拽索引越界')
    if source == target:
        return clean
    item = clean.pop(source)
    clean.insert(target, item)
    return clean


def export_payload(points):
    clean = normalize_points(points)
    return {'schema': SCHEMA, 'points': clean}


def parse_payload(data):
    if not isinstance(data, dict):
        raise PointError('导入文件必须是 JSON 对象')
    if data.get('schema') not in (SCHEMA, None):
        raise PointError('schema 必须是 %s' % SCHEMA)
    return normalize_points(data.get('points'))


def export_file(path, points):
    payload = export_payload(points)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.multi-points-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write('\n')
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise
    return path


def import_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return parse_payload(json.load(handle))
    except PointError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise PointError('读取多点配置文件失败：%s' % exc)


def preview_positions(points, bounds, width=720, height=96, padding=10):
    """把屏幕坐标映射到 Canvas 坐标；返回 [(x,y,index)]。"""
    clean = normalize_points(points)
    if not clean:
        return []
    left = int(bounds.get('left', 0))
    top = int(bounds.get('top', 0))
    sw = max(1, int(bounds.get('width', 1920)))
    sh = max(1, int(bounds.get('height', 1080)))
    usable_w = max(1, int(width) - padding * 2)
    usable_h = max(1, int(height) - padding * 2)
    result = []
    for index, point in enumerate(clean):
        px = padding + (point['x'] - left) / sw * usable_w
        py = padding + (point['y'] - top) / sh * usable_h
        px = min(max(padding, px), padding + usable_w)
        py = min(max(padding, py), padding + usable_h)
        result.append((px, py, index))
    return result
