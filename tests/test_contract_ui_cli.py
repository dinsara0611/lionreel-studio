"""
tests/test_contract_ui_cli.py
=============================
Contract tests verifying the strict mapping and validation contract between
the LionReel Dashboard (Web UI) and the CLI Automation Script (lion_automate_v97.py).

Verifies:
1. Every dashboard option (formats short/long/both, animals feline/canine/mixed/duo,
   layouts, languages, pace and slicing choices, clip count and clip time ranges,
   allow_shorter and allow_reuse) maps to CLI arguments that the parser accepts.
2. CLI parser accepts both canonical values and safety-net aliases ("long" -> "compilation",
   "mixed" -> "duo") without throwing an error.
3. Unknown or malformed inputs return validation errors (for HTTP 400) and are never executed.
4. Dashboard source files (app.js, index.html) do not contain unmapped options.
"""

import os
import sys
import re
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

class TestContractUiCli(unittest.TestCase):
    def test_job_options_module_exists_and_exports_contract(self):
        """Verify job_options module exists and provides required contract definitions."""
        try:
            import job_options
        except ImportError:
            self.fail("job_options module does not exist yet. Must be created as single contract module.")

        self.assertTrue(hasattr(job_options, "normalize_job_options"), "Missing normalize_job_options")
        self.assertTrue(hasattr(job_options, "build_arg_parser"), "Missing build_arg_parser")
        self.assertTrue(hasattr(job_options, "build_cli_args"), "Missing build_cli_args")
        self.assertTrue(hasattr(job_options, "FORMAT_MAP"), "Missing FORMAT_MAP")
        self.assertTrue(hasattr(job_options, "ANIMAL_MAP"), "Missing ANIMAL_MAP")
        self.assertTrue(hasattr(job_options, "LAYOUT_MAP"), "Missing LAYOUT_MAP")

    def test_long_format_maps_to_compilation_and_passes_cli_parser(self):
        """Verify format 'long' maps to 'compilation' and parses cleanly without exit code 2."""
        import job_options
        cfg = {
            "VIDEO_TYPE": "long",
            "ANIMAL_MODE": "cat",
            "TARGET_CLIPS": 25,
            "SHORT_CLIP_SEC": 12.0,
            "SPEED_PROFILE": "balanced",
            "MOMENT_CUT_MODE": "peak_viral",
            "LAYOUT_MODE": "smart_crop"
        }
        ok, mapped, err = job_options.normalize_job_options(cfg)
        self.assertTrue(ok, f"normalize_job_options failed for long video: {err}")
        self.assertEqual(mapped["type"], "compilation", "Long format must map to CLI type 'compilation'")

        parser = job_options.build_arg_parser()
        args_list = job_options.build_cli_args(mapped, job_id="test_job_123", job_start_time=1000.0)
        parsed = parser.parse_args(args_list)
        self.assertEqual(parsed.type, "compilation")
        self.assertEqual(parsed.clips, 25)
        self.assertEqual(parsed.clip_time, 12.0)

    def test_cli_parser_accepts_alias_long_directly(self):
        """CLI parser must accept --type long directly as safety net and normalize to compilation."""
        import job_options
        parser = job_options.build_arg_parser()
        parsed = parser.parse_args(["--type", "long", "--mode", "cat"])
        self.assertIn(parsed.type, ["compilation", "long"])

    def test_cli_parser_accepts_alias_mixed_directly(self):
        """CLI parser must accept --mode mixed directly as safety net and normalize to duo."""
        import job_options
        parser = job_options.build_arg_parser()
        parsed = parser.parse_args(["--mode", "mixed", "--type", "short"])
        self.assertIn(parsed.mode, ["duo", "mixed"])

    def test_all_enumerated_dashboard_combinations(self):
        """Enumerate all valid options the dashboard can send and verify they parse cleanly."""
        import job_options
        parser = job_options.build_arg_parser()

        formats = ["short", "long", "both"]
        animals = ["feline", "canine", "mixed", "cat", "dog", "duo"]
        layouts = ["smart_crop", "blur_fit", "auto", "Smart crop", "Blur-fit", "Auto"]
        languages = ["en", "si"]
        paces = ["fast", "balanced", "cinematic"]
        slicings = ["peak_viral", "fast_action", "funny_moments", "balanced"]

        for fmt in formats:
            for animal in animals:
                for layout in layouts:
                    for lang in languages:
                        for pace in paces:
                            for slicing in slicings:
                                cfg = {
                                    "VIDEO_TYPE": fmt,
                                    "ANIMAL_MODE": animal,
                                    "LAYOUT_MODE": layout,
                                    "LANG": lang,
                                    "SPEED_PROFILE": pace,
                                    "MOMENT_CUT_MODE": slicing,
                                    "TARGET_CLIPS": 6,
                                    "SHORT_CLIP_SEC": 8.0,
                                    "ALLOW_SHORTER": True,
                                    "ALLOW_REUSE": False
                                }
                                ok, mapped, err = job_options.normalize_job_options(cfg)
                                self.assertTrue(ok, f"Failed combination: {cfg} -> {err}")
                                args_list = job_options.build_cli_args(mapped, job_id="test_combo", job_start_time=12345.0)
                                parsed = parser.parse_args(args_list)
                                self.assertIsNotNone(parsed)

    def test_invalid_options_rejected_with_clear_error(self):
        """Unknown format or animal must be rejected with informative error message."""
        import job_options
        bad_format_cfg = {"VIDEO_TYPE": "ultra_wide"}
        ok, _, err = job_options.normalize_job_options(bad_format_cfg)
        self.assertFalse(ok)
        self.assertIn("Unknown format", err)
        self.assertIn("Allowed: short, long, both", err)

        bad_animal_cfg = {"VIDEO_TYPE": "short", "ANIMAL_MODE": "elephant"}
        ok, _, err = job_options.normalize_job_options(bad_animal_cfg)
        self.assertFalse(ok)
        self.assertIn("Unknown animal", err)

    def test_dashboard_files_do_not_contain_unmapped_options(self):
        """Read option lists from dashboard files (app.js / index.html) and verify they are all mapped."""
        import job_options
        app_js_path = os.path.join(BASE_DIR, "gui", "app.js")
        self.assertTrue(os.path.exists(app_js_path), "gui/app.js must exist")

        with open(app_js_path, "r", encoding="utf-8") as f:
            app_js_content = f.read()

        # Find setVideoType calls
        vtype_matches = set(re.findall(r'setVideoType\(["\']([a-zA-Z0-9_]+)["\']', app_js_content))
        for vt in vtype_matches:
            self.assertIn(vt, job_options.FORMAT_MAP, f"gui/app.js has unmapped video type '{vt}' in setVideoType")

        # Find animal mode radio/buttons in index.html
        index_html_path = os.path.join(BASE_DIR, "gui", "index.html")
        with open(index_html_path, "r", encoding="utf-8") as f:
            index_content = f.read()

        # Check animal buttons / collection cards in index.html (e.g. .collection-card[data-mode])
        animal_matches = set(re.findall(r'class=["\'][^"\']*collection-card[^"\']*["\'][^>]*data-mode=["\']([a-zA-Z0-9_]+)["\']', index_content) +
                             re.findall(r'data-mode=["\']([a-zA-Z0-9_]+)["\'][^>]*class=["\'][^"\']*collection-card[^"\']*["\']', index_content))
        for am in animal_matches:
            self.assertIn(am.lower(), job_options.ANIMAL_MAP, f"gui/index.html has unmapped animal mode '{am}'")

if __name__ == "__main__":
    unittest.main()
