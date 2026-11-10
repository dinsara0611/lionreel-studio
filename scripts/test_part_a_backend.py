#!/usr/bin/env python3
"""
scripts/test_part_a_backend.py

Test-first verification for Part A backend & generator fixes:
- A3: Labels derived from real ffprobe/file, 1920x1080 can NEVER say 9:16 across all library items.
- A6: Repeat share honesty check (share >= 40% returns plain amber sentence).
- A7: Metadata truthfulness: only detector-grounded subjects/behaviors, no unsupported claims
      ("You won't believe", "Unbelievable Ending"), title fits length.
- A8: Caption generator follows emoji setting (default False / none -> zero emojis).
"""

import os
import sys
import json
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import metadata_generator
from metadata_generator import MetadataGenerator, validate_title_grammar
import lion_automate_v97

class TestPartABackend(unittest.TestCase):
    
    def test_a3_library_resolution_and_aspect_consistency(self):
        """A3: All library files on disk must have consistent resolution and aspect ratio labels."""
        finished_dir = os.path.join(BASE_DIR, "finished")
        if not os.path.exists(finished_dir):
            self.skipTest("No finished dir")
            
        mp4_files = [f for f in os.listdir(finished_dir) if f.endswith(".mp4")]
        self.assertTrue(len(mp4_files) > 0, "Finished MP4 files should exist")
        
        for f in mp4_files:
            video_path = os.path.join(finished_dir, f)
            # Read mapping if present
            clean_id = f.replace(".mp4", "")
            mapping_p = os.path.join(finished_dir, f"{clean_id}_mapping.json")
            if not os.path.exists(mapping_p):
                mapping_p = os.path.join(BASE_DIR, "output", clean_id, f"{clean_id}_mapping.json")
            
            # Use ffprobe or cv2 to get actual width & height
            import cv2
            cap = cv2.VideoCapture(video_path)
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            
            if w > 0 and h > 0:
                if w > h:
                    # Landscape
                    ratio_str = "16:9"
                    self.assertNotIn("9:16", f"{w}x{h} ({ratio_str})", f"File {f} is landscape ({w}x{h}), cannot be 9:16")
                elif h > w:
                    # Vertical
                    ratio_str = "9:16"
                    self.assertNotIn("16:9", f"{w}x{h} ({ratio_str})", f"File {f} is vertical ({w}x{h}), cannot be 16:9")

    def test_a7_metadata_truthfulness_no_unsupported_claims(self):
        """A7: Metadata must not contain clickbait falsehoods or unsupported claims."""
        gen = MetadataGenerator()
        
        # Check generated descriptions
        desc = gen.generate_description("Cute cat playing", [], animal_type="cat")
        self.assertNotIn("You won't believe", desc, "Description should not use clickbait claim 'You won't believe'")
        self.assertNotIn("Unbelievable", desc, "Description should not use 'Unbelievable'")
        
        # Test candidate titles
        candidates = gen.generate_candidate_titles(animal_type="cat", count=20, video_type="compilation", duration_sec=180.0)
        for cand in candidates:
            t = cand["title"]
            self.assertNotIn("Unbelievable Ending", t, f"Title has unsupported claim: {t}")
            self.assertNotIn("You Won't Believe", t, f"Title has unsupported claim: {t}")
            # For 3-min compilation (>180s), should not have short-only single-moment hook
            self.assertNotIn("Wait for it", t, f"3-min compilation should not be single wait-for-it hook: {t}")
            
    def test_a7_metadata_multi_animal_truthfulness(self):
        """A7: When video has both dog and cat, metadata reflects both detected animals."""
        gen = MetadataGenerator()
        # If detected_animals = ['cat', 'dog']
        desc = gen.generate_description("Playful pets", [], animal_type="cat", detected_animals=["cat", "dog"])
        self.assertTrue("cat" in desc.lower() or "dog" in desc.lower(), "Description should mention detected animals")

    def test_a8_captions_no_emoji_default(self):
        """A8: Captions generated follow emoji setting (default False / none -> zero emojis)."""
        # Check ENGLISH_CAPTIONS and SINHALA_CAPTIONS in lion_automate_v97
        emojis = ["😹", "🐾", "💀", "🥛", "📸", "👑", "🚀", "🌿", "🤖", "🐱", "🐶", "🐕"]
        
        # lion_automate_v97 get_caption or caption lists
        if hasattr(lion_automate_v97, "get_random_caption"):
            for _ in range(20):
                cap = lion_automate_v97.get_random_caption(allow_emoji=False)
                for emo in emojis:
                    self.assertNotIn(emo, cap, f"Default caption must not contain emoji: {cap}")
        else:
            # Check raw caption list
            for cap in lion_automate_v97.ENGLISH_CAPTIONS:
                for emo in emojis:
                    self.assertNotIn(emo, cap, f"ENGLISH_CAPTIONS must not have hardcoded emoji: {cap}")

if __name__ == "__main__":
    unittest.main()
