# -*- coding: utf-8 -*-
"""T06162：强调色对比度保护、hover/pressed 派生与调色板写入。"""
import unittest

from auto_clicker_layers import accent


class AccentTests(unittest.TestCase):
    def test_normalize_hex(self):
        self.assertEqual(accent.normalize_hex('#abc'), '#AABBCC')
        self.assertEqual(accent.normalize_hex('0056b3'), '#0056B3')
        with self.assertRaises(ValueError):
            accent.normalize_hex('blue')

    def test_contrast_ratio_known_values(self):
        self.assertAlmostEqual(accent.contrast_ratio('#000000', '#FFFFFF'), 21.0, places=1)
        self.assertAlmostEqual(accent.contrast_ratio('#FFFFFF', '#FFFFFF'), 1.0, places=2)

    def test_low_contrast_is_adjusted_or_rejected(self):
        adjusted, changed, ratio = accent.ensure_accent('#AAAAAA', '#FFFFFF')
        self.assertTrue(changed)
        self.assertGreaterEqual(ratio, 4.5)
        self.assertLess(accent.relative_luminance(adjusted),
                        accent.relative_luminance('#AAAAAA'))
        with self.assertRaises(ValueError):
            accent.ensure_accent('#0056B3', '#FFFFFF', min_ratio=25)

    def test_derive_states_and_palette(self):
        states = accent.derive_states('#0056B3', '#FFFFFF')
        self.assertEqual(states['primary'], '#0056B3')
        self.assertEqual(states['on_primary'], '#FFFFFF')
        self.assertNotEqual(states['primary_hover'], states['primary'])
        pal = {'bg': '#FFFFFF', 'surface': '#F8F9FA', 'primary': '#0056B3',
               'primary_hover': '#004A99', 'primary_pressed': '#003D80',
               'on_primary': '#FFFFFF', 'success': '#1E7E34'}
        merged = accent.apply_to_palette(pal, '#0056B3')
        self.assertEqual(merged['success'], '#1E7E34')
        self.assertEqual(merged['primary'], '#0056B3')
        self.assertFalse(merged['accent_adjusted'])
        self.assertIn('soft', merged)
        for key in ('primary', 'primary_hover', 'primary_pressed'):
            self.assertGreaterEqual(accent.contrast_ratio(merged['on_primary'], merged[key]), 4.5,
                                    key)


if __name__ == '__main__':
    unittest.main(verbosity=2)
