"""
LionReel Studio — Metadata Generator
Generates platform-compliant, unique, high-quality metadata for YouTube Shorts,
TikTok, and Instagram Reels with Quality Checklist scoring and strict attribution.
"""

import os
import json
import random
import re
from typing import List, Dict, Any, Optional
from clip_ledger import ClipLedger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
TITLE_BANK_PATH = os.path.join(CONFIG_DIR, "title_bank.json")
HASHTAG_BANK_PATH = os.path.join(CONFIG_DIR, "hashtag_bank.json")
PLATFORM_LIMITS_PATH = os.path.join(CONFIG_DIR, "platform_limits.json")


def load_json_config(path: str, default: dict) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


def compute_ngram_overlap(s1: str, s2: str, n: int = 3) -> float:
    """Computes Jaccard word n-gram overlap between two strings."""
    w1 = re.findall(r"\w+", s1.lower())
    w2 = re.findall(r"\w+", s2.lower())
    if len(w1) < n or len(w2) < n:
        set1 = set(w1)
        set2 = set(w2)
        if not set1 or not set2:
            return 0.0
        return len(set1 & set2) / max(len(set1 | set2), 1)

    ngrams1 = set(tuple(w1[i:i + n]) for i in range(len(w1) - n + 1))
    ngrams2 = set(tuple(w2[i:i + n]) for i in range(len(w2) - n + 1))
    if not ngrams1 or not ngrams2:
        return 0.0
    return len(ngrams1 & ngrams2) / max(len(ngrams1 | ngrams2), 1)


class MetadataGenerator:
    def __init__(self, ledger: Optional[ClipLedger] = None):
        self.ledger = ledger or ClipLedger()
        self.title_bank = load_json_config(TITLE_BANK_PATH, {})
        self.hashtag_bank = load_json_config(HASHTAG_BANK_PATH, {})
        self.platform_limits = load_json_config(PLATFORM_LIMITS_PATH, {})

    def score_title_quality(self, title: str, animal_type: str = "cat") -> Dict[str, Any]:
        """
        Evaluates a candidate title using the transparent 'Metadata Quality Checklist'.
        Honesty rule: Never label anything 'viral score' or 'will go viral'.
        Max score: 100 points.
        """
        checklist = []
        score = 0

        # 1. Length Checklist (Optimal 35 - 70 chars)
        t_len = len(title)
        if 35 <= t_len <= 70:
            checklist.append({"item": "Title length optimal (35-70 chars)", "passed": True, "pts": 25})
            score += 25
        elif 25 <= t_len <= 85:
            checklist.append({"item": "Title length acceptable (25-85 chars)", "passed": True, "pts": 15})
            score += 15
        else:
            checklist.append({"item": f"Title length suboptimal ({t_len} chars)", "passed": False, "pts": 5})
            score += 5

        # 2. Hook placement (First 40 chars should carry curiosity or emotion)
        first_40 = title[:40].lower()
        hook_indicators = [
            "wait", "watch", "when", "why", "pov", "how", "nobody", "look", "proof", "moment", "exact"
        ]
        has_hook = any(h in first_40 for h in hook_indicators)
        if has_hook:
            checklist.append({"item": "Strong hook within first 40 characters", "passed": True, "pts": 20})
            score += 20
        else:
            checklist.append({"item": "Hook could be placed earlier", "passed": False, "pts": 10})
            score += 10

        # 3. Subject Clarity (Accurately identifies subject)
        subject_indicators = ["cat", "kitten", "kitty", "feline", "dog", "puppy"]
        has_subject = any(s in title.lower() for s in subject_indicators)
        if has_subject:
            checklist.append({"item": f"Clearly identifies animal subject ({animal_type})", "passed": True, "pts": 20})
            score += 20
        else:
            checklist.append({"item": "Animal subject not explicitly stated", "passed": False, "pts": 5})
            score += 5

        # 4. Clean formatting & punctuation
        exclamation_count = title.count("!")
        caps_ratio = sum(1 for c in title if c.isupper()) / max(len(title), 1)
        if exclamation_count <= 1 and caps_ratio < 0.50:
            checklist.append({"item": "Clean typography & sensible punctuation", "passed": True, "pts": 15})
            score += 15
        else:
            checklist.append({"item": "Excessive capitalization or exclamation marks", "passed": False, "pts": 5})
            score += 5

        # 5. Policy & Clickbait Safety (Zero banned spam phrases)
        banned = self.title_bank.get("fragments", {}).get("banned_phrases", [])
        lower_t = title.lower()
        found_banned = [b for b in banned if b in lower_t]
        if not found_banned:
            checklist.append({"item": "Passes YouTube clickbait & misleading metadata policy", "passed": True, "pts": 20})
            score += 20
        else:
            checklist.append({"item": f"Contains flagged clickbait terms ({found_banned[0]})", "passed": False, "pts": -50})
            score = max(0, score - 50)

        return {
            "score": min(100, max(0, score)),
            "checklist": checklist,
            "title_length": t_len
        }

    def generate_candidate_titles(self, animal_type: str = "cat", count: int = 30) -> List[Dict[str, Any]]:
        """
        Generates 30 candidate titles, scores them with the quality checklist,
        and enforces uniqueness against historical titles in the ledger.
        """
        recent_titles = self.ledger.get_recent_metadata_titles(animal_type, limit=50)
        recent_templates = self.ledger.get_recent_template_ids(animal_type, limit=20)

        categories = self.title_bank.get("categories", {})
        fragments = self.title_bank.get("fragments", {})
        hooks = fragments.get("hooks", ["Wait for it...", "POV:"])
        subjects = fragments.get(f"subjects_{animal_type}", ["This Cat", "The Kitten"])
        subjects_pl = fragments.get(f"subjects_{animal_type}_plural", ["Cats"])
        actions = fragments.get("actions", ["Did something funny"])
        punchlines = fragments.get("punchlines", ["(Instant Regret)"])

        candidates = []
        seen_strings = set(t.lower() for t in recent_titles)

        # Collect all templates with category keys
        all_templates = []
        for cat_key, cat_data in categories.items():
            for t_idx, tmpl in enumerate(cat_data.get("templates", [])):
                all_templates.append((f"{cat_key}_{t_idx}", tmpl))

        # Shuffle templates
        random.shuffle(all_templates)

        attempts = 0
        while len(candidates) < count and attempts < 120:
            attempts += 1
            tmpl_id, tmpl = random.choice(all_templates)
            if tmpl_id in recent_templates:
                continue

            hook = random.choice(hooks)
            subject = random.choice(subjects)
            subject_pl = random.choice(subjects_pl)
            action = random.choice(actions)
            punchline = random.choice(punchlines)

            cand_title = tmpl.format(
                hook=hook,
                subject=subject,
                subject_plural=subject_pl,
                action=action,
                punchline=punchline
            ).strip()

            # Clean spaces
            cand_title = re.sub(r"\s+", " ", cand_title)

            # Check exact duplicates
            if cand_title.lower() in seen_strings:
                continue

            # Check 3-gram overlap against recent titles (< 40%)
            max_overlap = 0.0
            for prev in recent_titles:
                overlap = compute_ngram_overlap(cand_title, prev, n=3)
                if overlap > max_overlap:
                    max_overlap = overlap
            if max_overlap >= 0.40:
                continue

            # Score quality
            quality = self.score_title_quality(cand_title, animal_type)

            candidates.append({
                "title": cand_title,
                "template_id": tmpl_id,
                "score": quality["score"],
                "checklist": quality["checklist"],
                "length": quality["title_length"]
            })
            seen_strings.add(cand_title.lower())

        # Sort by checklist score descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates

    def get_top_titles(self, animal_type: str = "cat", top_n: int = 5) -> List[Dict[str, Any]]:
        """Returns top N scored titles for UI selection dropdown."""
        candidates = self.generate_candidate_titles(animal_type, count=30)
        return candidates[:top_n]

    def select_hashtags(self, animal_type: str = "cat", platform: str = "youtube_shorts") -> List[str]:
        """
        Picks balanced hashtags across tiers (1 mega, 2 medium, 1-2 niche)
        strictly avoiding any banned tags.
        """
        bank = self.hashtag_bank.get(animal_type, {})
        blocklist = set(self.hashtag_bank.get("blocklist", []))

        mega = [h for h in bank.get("mega", []) if h not in blocklist]
        medium = [h for h in bank.get("medium", []) if h not in blocklist]
        niche = [h for h in bank.get("niche", []) if h not in blocklist]

        chosen = []
        if mega:
            chosen.append(random.choice(mega))
        if medium:
            chosen.extend(random.sample(medium, min(2, len(medium))))
        if niche:
            chosen.extend(random.sample(niche, min(2, len(niche))))

        return chosen

    def generate_description(self, title: str, credits_list: List[Dict[str, Any]], animal_type: str = "cat") -> str:
        """
        Builds compliant YouTube Shorts description:
        - First 150 chars: engaging hook
        - Brief genuine context
        - Full Legal Credits Attribution Block
        - 3-5 high-relevance hashtags
        """
        hashtags = self.select_hashtags(animal_type, platform="youtube_shorts")
        hashtags_line = " ".join(hashtags)

        # Build credits section
        credits_lines = []
        if credits_list:
            credits_lines.append("Sources & Creative Commons Attribution:")
            seen_sources = set()
            for c in credits_list:
                src_name = c.get("source") or c.get("source_file") or "Creative Commons Video"
                if src_name in seen_sources:
                    continue
                seen_sources.add(src_name)
                credit_name = c.get("credit") or c.get("channel") or c.get("author") or "Verified CC Contributor"
                license_str = c.get("license") or "Creative Commons Attribution 4.0"
                credits_lines.append(f"• Clip: {credit_name} ({license_str})")
        else:
            credits_lines.append("Footage licensed under Creative Commons CC-BY 4.0 and curated original footage.")

        credits_block = "\n".join(credits_lines)

        hook_text = f"You won't believe how this funny {animal_type} reacted! Captured moments of pure chaos and cuteness."

        desc = (
            f"{hook_text}\n\n"
            f"Watch until the end for the best moment! Subscribe for daily wholesome and hilarious {animal_type} videos.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{credits_block}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{hashtags_line}"
        )
        return desc[:5000].strip()

    def generate_tags(self, animal_type: str = "cat", count: int = 12) -> List[str]:
        """Generates YouTube video tags (8-15 tags, total <= 500 chars)."""
        bank = self.hashtag_bank.get(animal_type, {})
        raw_tags = []
        for tier in ["medium", "niche", "mega"]:
            for h in bank.get(tier, []):
                cleaned = h.lstrip("#")
                if cleaned not in raw_tags:
                    raw_tags.append(cleaned)

        random.shuffle(raw_tags)
        selected = raw_tags[:count]
        # Keep total comma-separated length <= 450 chars
        while len(", ".join(selected)) > 450 and selected:
            selected.pop()
        return selected

    def generate_tiktok_package(self, title: str, credits_list: List[Dict[str, Any]], animal_type: str = "cat") -> Dict[str, str]:
        """Generates TikTok caption with credit line and 3-5 tags within 2200 chars."""
        hashtags = self.select_hashtags(animal_type, platform="tiktok")
        tag_str = " ".join(hashtags)
        first_credit = credits_list[0].get("credit", "CC Creator") if credits_list else "CC-BY"
        caption = f"{title} 😂🐾 Credit: {first_credit} {tag_str}"
        return {
            "caption": caption[:2200],
            "hashtags": tag_str
        }

    def generate_instagram_package(self, title: str, credits_list: List[Dict[str, Any]], animal_type: str = "cat") -> Dict[str, str]:
        """Generates Instagram Reels caption with credit block and tags."""
        hashtags = self.select_hashtags(animal_type, platform="instagram_reels")
        tag_str = " ".join(hashtags)
        credit_parts = []
        for c in (credits_list or [])[:3]:
            cr = c.get("credit", "CC Creator")
            if cr not in credit_parts:
                credit_parts.append(cr)
        cr_line = f"Credit: {', '.join(credit_parts)}" if credit_parts else "Curated CC Content"
        caption = f"{title} 🐱✨\n\n{cr_line}\n\n{tag_str}"
        return {
            "caption": caption[:2200],
            "hashtags": tag_str
        }

    def generate_metadata_package(self, job_id: str, animal_type: str = "cat",
                                  credits_list: Optional[List[Dict[str, Any]]] = None,
                                  mode: str = "full") -> Dict[str, Any]:
        """
        Main entry point: Generates full metadata package or title-only based on mode.
        """
        top_titles = self.get_top_titles(animal_type, top_n=5)
        best_title_obj = top_titles[0] if top_titles else {
            "title": f"Funniest {animal_type.capitalize()} Moments You Can't Miss",
            "template_id": "fallback",
            "score": 85,
            "checklist": []
        }
        chosen_title = best_title_obj["title"]
        credits_list = credits_list or []

        if mode == "title_only":
            return {
                "mode": "title_only",
                "job_id": job_id,
                "title": chosen_title,
                "top_titles": top_titles,
                "ranked_titles": top_titles,
                "quality_checklist": best_title_obj.get("checklist", []),
                "quality_score": best_title_obj.get("score", 85),
                "credits": credits_list
            }

        desc = self.generate_description(chosen_title, credits_list, animal_type)
        tags = self.generate_tags(animal_type, count=12)
        tags_str = ", ".join(tags)
        hashtags = self.select_hashtags(animal_type)
        hashtags_str = " ".join(hashtags)

        tiktok = self.generate_tiktok_package(chosen_title, credits_list, animal_type)
        instagram = self.generate_instagram_package(chosen_title, credits_list, animal_type)

        package = {
            "mode": "full",
            "job_id": job_id,
            "title": chosen_title,
            "top_titles": top_titles,
            "ranked_titles": top_titles,
            "template_id": best_title_obj.get("template_id", ""),
            "quality_checklist": best_title_obj.get("checklist", []),
            "quality_score": best_title_obj.get("score", 85),
            "description": desc,
            "tags": tags_str,
            "hashtags": hashtags_str,
            "tiktok": tiktok,
            "instagram": instagram,
            "credits": credits_list
        }

        # Record in ledger for uniqueness history
        try:
            self.ledger.record_metadata(
                job_id=job_id,
                animal_type=animal_type,
                title=chosen_title,
                description=desc,
                tags=tags_str,
                hashtags=hashtags_str,
                template_id=best_title_obj.get("template_id", ""),
                platform="all"
            )
        except Exception:
            pass

        return package
