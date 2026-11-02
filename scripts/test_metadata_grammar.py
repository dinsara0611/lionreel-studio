"""
Test Suite: Metadata Title Grammar & Slot Validator
Validates 300 generated titles and defect cases:
1. Double determiners ("A Tiny This Majestic", "This The Cat")
2. Dangling prepositions ("slipped off with", "jumped to")
3. Article mismatch ("A orange", "An cat")
4. Repeated consecutive words ("cat cat", "the the")
5. Long compilation hook mismatch ("Wait for it..." on >180s videos)
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from metadata_generator import validate_title_grammar, MetadataGenerator


class TestMetadataGrammar(unittest.TestCase):
    def test_double_determiner_rejections(self):
        defects = [
            "A Tiny This Majestic Cat With The Biggest Personality",
            "Watch What Happens When This The Cat Jumps",
            "The Sweetest Little A Kitten You'll See Today",
            "Our Resident This Cat Decided To Nap",
            "This My Cat Stared Into The 5th Dimension",
            "A That Dog Slipped Off The Couch"
        ]
        for title in defects:
            valid, err = validate_title_grammar(title)
            self.assertFalse(valid, f"Expected rejection for '{title}', but got valid=True")
            self.assertIn("Double determiner", err)

    def test_dangling_preposition_rejections(self):
        defects = [
            "Wait For It... What The Cat Jumped With",
            "Nobody Expected The Kitten To Turn Into",
            "The Exact Second The Cat Fell Off",
            "When Your Cat Demands Attention At",
            "How My Cat Asks For Love Without"
        ]
        for title in defects:
            valid, err = validate_title_grammar(title)
            self.assertFalse(valid, f"Expected rejection for '{title}', but got valid=True")
            self.assertIn("Dangling preposition", err)

    def test_article_mismatch_rejections(self):
        defects = [
            "A Orange Cat Tried To Jump",
            "A Empty Food Bowl Reaction",
            "An Cat Slipped Off The Sofa",
            "An Tiny Kitten Falling Asleep"
        ]
        for title in defects:
            valid, err = validate_title_grammar(title)
            self.assertFalse(valid, f"Expected rejection for '{title}', but got valid=True")
            self.assertIn("Article mismatch", err)

    def test_repeated_consecutive_words_rejections(self):
        defects = [
            "Watch This Cat Cat Jump High",
            "When The Little Little Kitten Falls Asleep",
            "Why Does My Dog Dog Always React"
        ]
        for title in defects:
            valid, err = validate_title_grammar(title)
            self.assertFalse(valid, f"Expected rejection for '{title}', but got valid=True")
            self.assertIn("Repeated consecutive word", err)

    def test_compilation_hook_mismatch(self):
        comp_defect = "Wait for it... The Ultimate Cat Compilation"
        valid, err = validate_title_grammar(comp_defect, video_type="compilation", duration_sec=300.0)
        self.assertFalse(valid, "Expected rejection for short hook on 300s compilation")
        self.assertIn("inappropriate for long compilation", err)

    def test_valid_titles_pass(self):
        valid_examples = [
            "Nobody Expected This Cat To Do A Backflip (Instant Regret)",
            "The Exact Second My Fluffy Cat Realized What Happened",
            "Pure Unfiltered Chaos From Our Orange Cat",
            "Tell Me This Kitten Isn't The Cutest Baby In The World",
            "POV: Living With A Tuxedo Cat Every Single Morning"
        ]
        for title in valid_examples:
            valid, err = validate_title_grammar(title)
            self.assertTrue(valid, f"Expected valid for '{title}', but got err: {err}")

    def test_300_generated_titles_suite(self):
        mg = MetadataGenerator()
        total_tested = 0
        failures = []

        # Test 150 cat titles (short & long compilation)
        cat_shorts = mg.generate_candidate_titles(animal_type="cat", count=75, video_type="short", duration_sec=45.0)
        cat_longs = mg.generate_candidate_titles(animal_type="cat", count=75, video_type="compilation", duration_sec=300.0)
        # Test 150 dog titles (short & long compilation)
        dog_shorts = mg.generate_candidate_titles(animal_type="dog", count=75, video_type="short", duration_sec=45.0)
        dog_longs = mg.generate_candidate_titles(animal_type="dog", count=75, video_type="compilation", duration_sec=300.0)

        all_generated = (
            [(t, "short", 45.0) for t in cat_shorts] +
            [(t, "compilation", 300.0) for t in cat_longs] +
            [(t, "short", 45.0) for t in dog_shorts] +
            [(t, "compilation", 300.0) for t in dog_longs]
        )

        for item, v_type, d_sec in all_generated:
            title = item["title"]
            total_tested += 1
            valid, err = validate_title_grammar(title, video_type=v_type, duration_sec=d_sec)
            if not valid:
                failures.append((title, err))
            if not valid:
                self.assertLess(item["score"], 60)
            self.assertTrue(valid, f"Generated title failed grammar validation: '{title}' -> {err}")

        print(f"\n[METADATA TEST SUITE] Successfully tested {total_tested} generated titles: 0 grammar failures!")
        self.assertEqual(len(failures), 0)
        self.assertGreaterEqual(total_tested, 300)


if __name__ == "__main__":
    unittest.main()
