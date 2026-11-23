# -*- coding: utf-8 -*-
"""T06147 / UI-06：图标尺寸与字号阶梯单一来源。

- 图标按 16/20/24 px 三档出图（PIL 运行时生成，单色透明底）。
- 字号阶梯以像素口径定义 12/14/16/20/28，同时给出 96dpi 下的 pt 换算，
  供 Tk（pt）与文档/设计稿（px）共用，避免两套口径漂移。
- 字体族使用跨平台回退链：Windows 微软雅黑 → 麒麟/Noto CJK → 文泉驿 → DejaVu。
"""
ICON_SIZES = (16, 20, 24)
ICON_SIZE_DEFAULT = 16

FONT_PX = {
    'caption': 12,
    'body': 14,
    'subtitle': 16,
    'title': 20,
    'display': 28,
}
# Tk 的 font size 单位是 pt；96dpi 下 1px = 0.75pt。
FONT_PT = {name: int(round(px * 0.75)) for name, px in FONT_PX.items()}
BASE_FONT_PT = 9

FONT_FAMILIES = (
    'Microsoft YaHei',
    '微软雅黑',
    'Noto Sans CJK SC',
    'Source Han Sans SC',
    'WenQuanYi Micro Hei',
    'DejaVu Sans',
)


def resolve_font_family(available):
    """从 Tk 已安装字体族中选择第一个回退命中的族；都没有时返回 None。"""
    installed = {str(name).lower() for name in (available or [])}
    for family in FONT_FAMILIES:
        if family.lower() in installed:
            return family
    return None


def icon_size(step='md'):
    return {'sm': 16, 'md': 20, 'lg': 24}.get(str(step).lower(), ICON_SIZE_DEFAULT)
