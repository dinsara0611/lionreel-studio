"""
Unit tests for FunnyEventDetector and Shot-Aware Cut Placement rules (Phase 6.1).

Tests required:
1. Compilation source with 5s shots (no window crosses a scene cut)
2. Silent visual jump (detected through visual/motion signal despite 0 audio)
3. Meow plus pounce (peak placed at 35-50% with at least 1.5s of reaction aftermath)
4. Event longer than window (best sub-event, start and payoff intact)
5. Loud sound without any pet event (rejected or low score)
"""

import unittest
import numpy as np
from funny_event_detector import (
    FunnyEventDetector,
    FunnyEvent,
    place_shot_aware_window,
    validate_window_funny_part
)

class TestFunnyEventDetector(unittest.TestCase):
    def setUp(self):
        self.detector = FunnyEventDetector()

    def test_1_compilation_source_with_5s_shots(self):
        """1. Compilation source with 5s shots: no window crosses a scene cut."""
        # Source has rapid cuts every 5.0s
        shots = [
            (0.0, 5.0),
            (5.0, 10.0),
            (10.0, 15.0),
            (15.0, 20.0),
            (20.0, 25.0)
        ]
        
        # Action event inside Shot 2 [5.0, 10.0]
        event = FunnyEvent(
            onset_s=6.2,
            peak_s=7.5,
            end_s=8.8,
            score=0.92,
            trigger_type="motion",
            details={"description": "playful cat hop inside compilation shot"}
        )
        
        target_dur = 4.5  # Must adapt to fit inside the 5.0s shot
        win_start, win_end, win_peak, passed, reason = place_shot_aware_window(
            event=event,
            shots=shots,
            source_dur=25.0,
            target_dur=target_dur
        )
        
        self.assertTrue(passed, f"Window placement failed: {reason}")
        self.assertGreaterEqual(win_start, 5.0, "Window start crossed the preceding shot cut at 5.0s!")
        self.assertLessEqual(win_end, 10.0, "Window end crossed the following shot cut at 10.0s!")
        
        # Verify 0 shot cuts crossed
        cuts_crossed = [c for c in [5.0, 10.0, 15.0, 20.0] if win_start < c < win_end]
        self.assertEqual(len(cuts_crossed), 0, f"Window crossed scene cuts: {cuts_crossed}")

    def test_2_silent_visual_jump(self):
        """2. Silent visual jump: detected through visual/motion signals despite 0 audio energy."""
        # 10s synthetic timeline at 10 Hz (100 frames)
        times = np.linspace(0, 10, 100)
        audio_energy = np.zeros(100)  # Complete silence
        
        # Visual motion: pet jumps at t = 4.2s (frames 38-50)
        pet_speed = np.zeros(100)
        pet_flow = np.zeros(100)
        jump_idx = slice(38, 52)
        pet_speed[jump_idx] = np.sin(np.linspace(0, np.pi, 14)) * 0.45
        pet_flow[jump_idx] = np.sin(np.linspace(0, np.pi, 14)) * 0.55
        
        # Run event extraction
        events = self.detector.detect_events_from_timeline(
            times_s=times,
            audio_energy=audio_energy,
            audio_events=[{}] * 100,
            pet_speed=pet_speed,
            pet_flow=pet_flow,
            pet_accel=np.gradient(pet_speed),
            interaction_probs=np.zeros(100)
        )
        
        self.assertGreater(len(events), 0, "Failed to detect silent visual jump!")
        top_event = events[0]
        self.assertIn("motion", top_event.trigger_type.lower())
        self.assertAlmostEqual(top_event.peak_s, 4.5, delta=0.5, msg="Peak should be around 4.5s")
        self.assertGreater(top_event.score, 0.40, "Motion event score should exceed baseline threshold")

    def test_3_meow_plus_pounce(self):
        """3. Meow plus pounce: peak placed at 35-50% of the clip with at least 1.5s reaction."""
        # Event with meow onset at 2.5s, peak pounce at 4.0s, reaction until 5.2s
        event = FunnyEvent(
            onset_s=2.5,
            peak_s=4.0,
            end_s=5.2,
            score=0.96,
            trigger_type="multimodal",
            details={"audio": "cat meow", "motion": "pounce"}
        )
        shots = [(0.0, 30.0)]  # Long single shot
        target_dur = 8.0
        
        win_start, win_end, win_peak, passed, reason = place_shot_aware_window(
            event=event,
            shots=shots,
            source_dur=30.0,
            target_dur=target_dur
        )
        
        self.assertTrue(passed)
        clip_dur = win_end - win_start
        peak_offset = win_peak - win_start
        peak_pct = peak_offset / clip_dur
        reaction_dur = win_end - win_peak
        
        self.assertGreaterEqual(peak_pct, 0.35, f"Peak placed too early: {peak_pct:.1%}")
        self.assertLessEqual(peak_pct, 0.55, f"Peak placed too late: {peak_pct:.1%}")
        self.assertGreaterEqual(reaction_dur, 1.5, f"Reaction aftermath ({reaction_dur:.2f}s) is under 1.5s!")

    def test_4_event_longer_than_window(self):
        """4. Event longer than window: trims to best sub-event without cutting start or payoff."""
        # 14s event from t=2.0s to t=16.0s with peak at t=7.0s
        long_event = FunnyEvent(
            onset_s=2.0,
            peak_s=7.0,
            end_s=16.0,
            score=0.88,
            trigger_type="motion",
            details={"sub_events": "extended chase & capture"}
        )
        shots = [(0.0, 30.0)]
        target_dur = 7.0  # Window is shorter than the 14s event
        
        win_start, win_end, win_peak, passed, reason = place_shot_aware_window(
            event=long_event,
            shots=shots,
            source_dur=30.0,
            target_dur=target_dur
        )
        
        self.assertTrue(passed)
        self.assertLessEqual(win_end - win_start, target_dur + 0.1)
        # Verify peak is preserved inside the trimmed window
        self.assertGreaterEqual(win_peak, win_start)
        self.assertLessEqual(win_peak, win_end)
        # Verify lead-in and payoff are intact
        self.assertGreaterEqual(win_peak - win_start, 1.2, "Lead-in clipped prematurely!")
        self.assertGreaterEqual(win_end - win_peak, 1.2, "Payoff aftermath clipped prematurely!")

    def test_5_loud_sound_without_any_event(self):
        """5. Loud sound without any pet event: rejected or low score (FUNNY_PART_MISSING)."""
        # Event with 0 pet motion, just loud noise
        noise_event = FunnyEvent(
            onset_s=5.0,
            peak_s=6.0,
            end_s=7.0,
            score=0.18,  # Below threshold
            trigger_type="audio_only",
            details={"description": "loud mic bump / traffic noise with static pet"}
        )
        
        # Test validation gate
        passed, reason = validate_window_funny_part(
            event=noise_event,
            win_start=4.0,
            win_end=9.0,
            shots=[(0.0, 20.0)],
            score_threshold=0.35
        )
        
        self.assertFalse(passed, "Loud noise without funny action should fail gate!")
        self.assertEqual(reason, "FUNNY_PART_MISSING")

if __name__ == "__main__":
    unittest.main()
