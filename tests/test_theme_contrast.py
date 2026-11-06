"""Static contrast regression for GC UI v1 semantic colors used by GoreeCloud Git.

This does not assert browser-level WCAG conformance or visual acceptance.
WCAG contrast formulas are public accessibility criteria, not design tokens.
"""
import re
import unittest

from goreecloud_git.theme import CSS


def _roles(mode: str) -> dict[str, str]:
    selector = ":root {" if mode == "light" else ':root[data-gc-mode="dark"] {'
    if selector not in CSS:
        raise AssertionError(f"Missing {mode} semantic scheme")
    block = CSS.split(selector, 1)[1].split("}", 1)[0]
    return dict(re.findall(
        r"--gc-v1-color-([a-z-]+)\s*:\s*(#[0-9A-Fa-f]{6})\s*;", block
    ))


def _luminance(srgb: str) -> float:
    rgb = [int(srgb[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
              for v in rgb]
    return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))


def contrast_ratio(foreground: str, background: str) -> float:
    hi, lo = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (hi + .05) / (lo + .05)


class GCUIContrastTests(unittest.TestCase):
    def test_normal_size_text_roles_retain_45_to_1(self):
        # These are actual pairings in the current web.py/theme.py markup/CSS.
        pairs = (
            ("on-canvas", "canvas"),
            ("on-surface", "surface"),
            ("on-surface-muted", "canvas"),
            ("on-surface-muted", "surface"),
            ("link", "canvas"),
            ("link", "surface"),
            ("on-secondary-container", "secondary-container"),
            ("on-surface", "surface-tonal"),
        )
        for mode in ("light", "dark"):
            roles = _roles(mode)
            for fore, back in pairs:
                with self.subTest(mode=mode, foreground=fore, background=back):
                    self.assertIn(fore, roles)
                    self.assertIn(back, roles)
                    value = contrast_ratio(roles[fore], roles[back])
                    self.assertGreaterEqual(value, 4.5, f"{mode}: {fore}/{back} = {value:.2f}:1")

    def test_focus_and_outline_roles_retain_3_to_1(self):
        # Visible focus ring and meaningful control boundaries.
        for mode in ("light", "dark"):
            roles = _roles(mode)
            for fore, back in (
                ("focus-ring", "surface"),
                ("focus-ring", "canvas"),
                ("outline", "surface"),
            ):
                with self.subTest(mode=mode, foreground=fore, background=back):
                    value = contrast_ratio(roles[fore], roles[back])
                    self.assertGreaterEqual(value, 3.0, f"{mode}: {fore}/{back} = {value:.2f}:1")

    def test_forced_colors_and_user_control_are_not_replaced_with_hex(self):
        self.assertIn("@media (forced-colors:active)", CSS)
        for role in ("canvas:Canvas", "on-canvas:CanvasText",
                     "focus-ring:Highlight", "link:LinkText"):
            self.assertIn("--gc-v1-color-" + role, CSS)
        self.assertIn('@media (prefers-color-scheme:dark)', CSS)
        self.assertIn(':root[data-gc-mode="auto"]', CSS)
        self.assertIn(':root[data-gc-mode="dark"]', CSS)


if __name__ == "__main__":
    unittest.main()
