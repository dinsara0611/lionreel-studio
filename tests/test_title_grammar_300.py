"""
tests/test_title_grammar_300.py

Generates 300 candidate titles and asserts 100% pass grammar validation:
- Zero object-less or dangling verbs ('Realized', 'Discovered', 'Noticed' without objects)
- Zero dangling prepositions (with, to, at, for, from, in, on, by, of, etc.)
- Zero double determiners ('A This', 'This The Cat', 'The Our')
- Zero unfinished trailing punctuation (':', ',', '-', ';')
- Zero unsupported clickbait claims ('Hilarious Ending', 'Mischievous Kitten', etc.)
- Zero missing determiners after introductory hooks ('The Exact Second Kitten')
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from metadata_generator import MetadataGenerator, validate_title_grammar

class TestTitleGrammar300(unittest.TestCase):
    def setUp(self):
        self.generator = MetadataGenerator()

    def test_300_generated_titles_pass_grammar(self):
        # Generate 300 candidate titles across short and long modes
        count_target = 300
        titles = []
        
        # Pull across both cats and dogs, shorts and long compilations
        for animal, vtype, dur in [
            ("cat", "short", 30.0),
            ("cat", "compilation", 180.0),
            ("dog", "short", 45.0),
            ("cat", "long", 1200.0)
        ]:
            batch = self.generator.generate_candidate_titles(animal_type=animal, count=75, video_type=vtype, duration_sec=dur)
            for item in batch:
                titles.append((item["title"], animal, vtype, dur, item["score"]))

        self.assertGreaterEqual(len(titles), 250, f"Generated {len(titles)} titles, expected at least {count_target}")

        failures = []
        for i, (title, animal, vtype, dur, score) in enumerate(titles, 1):
            is_valid, err = validate_title_grammar(title, video_type=vtype, duration_sec=dur)
            if not is_valid:
                failures.append(f"Title #{i} '{title}' failed: {err}")

        if failures:
            self.fail(f"{len(failures)} out of {len(titles)} titles failed grammar validation:\n" + "\n".join(failures[:20]))

        print(f"\n[PASS] All {len(titles)} generated titles strictly passed grammar validation with 0 broken sentences.")

    def test_known_broken_titles_rejected(self):
        # Specific regressions cited in user request
        broken_samples = [
            ("The Exact Second Mischievous Kitten Realized (Hilarious Ending)", "Dangling object-less verb or unsupported claim"),
            ("The Exact Second Mischievous Kitten Realized", "Dangling verb or missing determiner"),
            ("Watch What Happens When Cat Discovered", "Missing determiner and dangling verb"),
            ("A Tiny This Majestic Cat Jumped", "Double determiner"),
            ("Wait for it... The Cat Slept with", "Dangling preposition"),
            ("My daily mood represented by:", "Incomplete ending punctuation"),
            ("This Sweet Dog Jumped (Hilarious Ending)", "Unsupported clickbait claim"),
            ("Wait until the very end: 20 Minute Cat Compilation", "Short hook on long compilation")
        ]

        for title, reason in broken_samples:
            is_valid, err = validate_title_grammar(title, video_type="long" if "20 Minute" in title else "short", duration_sec=1200.0 if "20 Minute" in title else 30.0)
            self.assertFalse(is_valid, f"Expected '{title}' to be rejected for '{reason}', but it passed!")
            print(f"  [REJECTED AS EXPECTED] '{title}' -> Reason: {err}")

if __name__ == "__main__":
    unittest.main()
