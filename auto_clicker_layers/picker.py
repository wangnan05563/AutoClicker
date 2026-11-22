# -*- coding: utf-8 -*-
"""FR-27 取点遮罩的纯逻辑：坐标钳制、边缘吸附、框选归一化与键盘微调。

UI 只负责事件和绘制；这里不依赖 tkinter，便于覆盖负坐标与多显示器边界。
"""
DEFAULT_SNAP_PX = 8
DEFAULT_CLICK_PX = 4


def _bounds(value):
    left, top, right, bottom = [int(v) for v in value]
    if right <= left or bottom <= top:
        raise ValueError("无效屏幕范围: %r" % (value,))
    return left, top, right, bottom


def clamp(value, low, high_inclusive):
    value = int(value)
    if value < low:
        return int(low)
    if value > high_inclusive:
        return int(high_inclusive)
    return value


def _axis_edges(lo, hi, monitor_rects, axis):
    edges = {int(lo), int(hi) - 1}
    for rect in monitor_rects or ():
        try:
            r = _bounds(rect)
        except ValueError:
            continue
        if axis == 'x':
            edges.add(r[0])
            edges.add(r[2] - 1)
        else:
            edges.add(r[1])
            edges.add(r[3] - 1)
    return edges


def snap_point(x, y, bounds, monitor_rects=None, threshold=DEFAULT_SNAP_PX):
    """把点吸附到虚拟屏或任一显示器的最近边缘；阈值内取最近，超阈值保持原值。"""
    left, top, right, bottom = _bounds(bounds)
    x = clamp(x, left, right - 1)
    y = clamp(y, top, bottom - 1)
    threshold = max(0, int(threshold))
    if threshold == 0:
        return x, y
    for value, edges, name in (
            (x, _axis_edges(left, right, monitor_rects, 'x'), 'x'),
            (y, _axis_edges(top, bottom, monitor_rects, 'y'), 'y')):
        near = [edge for edge in edges if abs(edge - value) <= threshold]
        if near:
            edge = min(near, key=lambda item: (abs(item - value), item))
            if name == 'x':
                x = edge
            else:
                y = edge
    return x, y


def point_selection(x, y, bounds, monitor_rects=None, threshold=DEFAULT_SNAP_PX):
    x, y = snap_point(x, y, bounds, monitor_rects, threshold)
    return {'x': x, 'y': y, 'width': 1, 'height': 1, 'point': True}


def rect_selection(x1, y1, x2, y2, bounds, monitor_rects=None,
                   threshold=DEFAULT_SNAP_PX, click_threshold=DEFAULT_CLICK_PX):
    """把拖拽起止点变成选区；位移不超过 click_threshold 时按单击取点。"""
    left, top, right, bottom = _bounds(bounds)
    raw_dx = abs(int(x2) - int(x1))
    raw_dy = abs(int(y2) - int(y1))
    x1, y1 = snap_point(x1, y1, bounds, monitor_rects, threshold)
    x2, y2 = snap_point(x2, y2, bounds, monitor_rects, threshold)
    if max(raw_dx, raw_dy) <= max(0, int(click_threshold)):
        return {'x': x2, 'y': y2, 'width': 1, 'height': 1, 'point': True}
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    return {'x': x1, 'y': y1, 'width': width, 'height': height, 'point': False}


def nudge_selection(selection, dx, dy, bounds):
    """方向键微调：点移动 1/10px；矩形整体平移，保持尺寸并限制在虚拟屏内。"""
    left, top, right, bottom = _bounds(bounds)
    if not isinstance(selection, dict):
        return None
    width = max(1, int(selection.get('width', 1) or 1))
    height = max(1, int(selection.get('height', 1) or 1))
    width = min(width, right - left)
    height = min(height, bottom - top)
    x = clamp(selection.get('x', left), left, right - width)
    y = clamp(selection.get('y', top), top, bottom - height)
    x = clamp(x + int(dx), left, right - width)
    y = clamp(y + int(dy), top, bottom - height)
    return {
        'x': x, 'y': y, 'width': width, 'height': height,
        'point': bool(selection.get('point', width == 1 and height == 1)),
    }


def magnifier_box(x, y, bounds, size=5):
    """返回以 (x,y) 为中心的 5×5 像素范围；靠近屏幕边缘时整体内收，不越界。"""
    left, top, right, bottom = _bounds(bounds)
    size = max(1, int(size))
    if size % 2 == 0:
        size += 1
    half = size // 2
    x = clamp(x, left, right - 1)
    y = clamp(y, top, bottom - 1)
    left = clamp(x - half, left, right - size)
    top = clamp(y - half, top, bottom - size)
    return left, top, left + size, top + size


def format_point(selection):
    if not isinstance(selection, dict):
        return '--'
    return '(%d, %d) · %d×%d' % (
        int(selection.get('x', 0)), int(selection.get('y', 0)),
        int(selection.get('width', 1)), int(selection.get('height', 1)))
