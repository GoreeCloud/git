"""Appearance preferences are local-only, non-secret and light-first."""
import unittest
from goreecloud_git.theme import CSS, appearance_cookie, appearance_from_cookie


class AppearanceTests(unittest.TestCase):
    def test_default_rejects_untrusted_cookie(self):
        for raw in ("", "gcgit_appearance=invalid", "gcgit_appearance=dark\r\n", "x" * 4100):
            with self.subTest(raw=raw[:30]):
                self.assertEqual(appearance_from_cookie(raw), "light")

    def test_persistent_choices_and_reset(self):
        for mode in ("light", "dark", "auto"):
            header = appearance_cookie(mode)
            self.assertEqual(appearance_from_cookie(header), mode)
            self.assertIn("HttpOnly", header)
            self.assertIn("SameSite=Strict", header)
            self.assertIn("Max-Age=31536000", header)
        self.assertIn("Max-Age=0", appearance_cookie("reset"))
        with self.assertRaises(ValueError):
            appearance_cookie("untrusted-value")

    def test_auto_is_opt_in_and_forced_colors_supported(self):
        self.assertIn("color-scheme:light", CSS)
        self.assertIn('@media (prefers-color-scheme:dark)', CSS)
        self.assertIn(':root[data-gc-mode="auto"]', CSS)
        self.assertIn('@media (forced-colors:active)', CSS)
        self.assertIn("prefers-reduced-motion:reduce", CSS)
        self.assertIn("--gc-v1-foundation-radius-lg:26px", CSS)

    def test_reference_text_pairs_meet_wcag_normal_text_contrast(self):
        """A narrow static check; not a browser/rendered-background WCAG audit."""
        def luminance(hex_color):
            rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                      for v in rgb]
            return sum(a * b for a, b in zip(linear, (0.2126, 0.7152, 0.0722)))

        def contrast(foreground, background):
            a, b = sorted((luminance(foreground), luminance(background)), reverse=True)
            return (a + 0.05) / (b + 0.05)

        for text, background in (
            ("#20243A", "#ECF0F8"),  # light canvas
            ("#20243A", "#F9FAFD"),  # light surface
            ("#5F657B", "#F9FAFD"),  # light muted text
            ("#4034B9", "#F9FAFD"),  # light link
            ("#F2F2FA", "#10131E"),  # dark canvas
            ("#F2F2FA", "#1D2231"),  # dark surface
            ("#B3B9CF", "#1D2231"),  # dark muted text
            ("#C5BFFF", "#1D2231"),  # dark link
        ):
            with self.subTest(text=text, background=background):
                self.assertGreaterEqual(contrast(text, background), 4.5)


if __name__ == "__main__":
    unittest.main()
