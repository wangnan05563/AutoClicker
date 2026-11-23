# -*- coding: utf-8 -*-
"""T06147：图标尺寸与字号阶梯 tokens、跨平台字体回退、向导无 emoji。"""
import unittest

from auto_clicker_layers import design_tokens, onboarding


class DesignTokenTests(unittest.TestCase):
    def test_icon_sizes_are_three_steps(self):
        self.assertEqual(design_tokens.ICON_SIZES, (16, 20, 24))
        self.assertEqual(design_tokens.icon_size('sm'), 16)
        self.assertEqual(design_tokens.icon_size('md'), 20)
        self.assertEqual(design_tokens.icon_size('lg'), 24)

    def test_font_ladder_px_and_pt(self):
        self.assertEqual(tuple(design_tokens.FONT_PX.values()), (12, 14, 16, 20, 28))
        self.assertEqual(tuple(design_tokens.FONT_PT.values()), (9, 10, 12, 15, 21))
        for px, pt in zip(design_tokens.FONT_PX.values(), design_tokens.FONT_PT.values()):
            self.assertAlmostEqual(pt, px * 0.75, delta=1)

    def test_font_family_fallback_prefers_installed(self):
        self.assertEqual(
            design_tokens.resolve_font_family(['DejaVu Sans', 'Noto Sans CJK SC']),
            'Noto Sans CJK SC')
        self.assertEqual(
            design_tokens.resolve_font_family(['WenQuanYi Micro Hei']),
            'WenQuanYi Micro Hei')
        self.assertIsNone(design_tokens.resolve_font_family(['Consolas']))

    def test_onboarding_icons_are_vector_names_not_emoji(self):
        for template in list(onboarding.TEMPLATES) + [onboarding.SAFE_TEMPLATE]:
            icon = template['icon']
            self.assertTrue(icon.isascii(), icon)
            self.assertIn(icon, {'laptop', 'check', 'repeat', 'gear', 'shield'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
