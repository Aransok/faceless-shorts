"""Tests for the case-file style (pipeline/casefile.py, STYLE.md).
Pure logic plus one drawing smoke test; no network, no ffmpeg."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image

from pipeline import casefile
from pipeline.metadata import _append_music_credit
from pipeline.plan import _apply_casefile_tags, _parse_response
from pipeline.visuals_facts import (
    _parse_beat_visual_plan,
    _plan_beat_segments,
)

FACTS_RAW = """TOPIC: Lake Nyos limnic eruption
HOOK: A lake in Cameroon killed 1,746 people in one night.
FACT_1_SCRIPT: This lake killed 1,746 people in a single night, and not one of them drowned.
FACT_1_SUBJECT: Lake Nyos
FACT_1_EXACT_QUERIES: Lake Nyos, crater lake Cameroon
FACT_1_REPRESENTATION_QUERIES: crater lake aerial, volcanic lake
FACT_1_CONCEPT_QUERIES: none
FACT_2_SCRIPT: Its deep water was loaded with volcanic carbon dioxide.
FACT_2_SUBJECT: carbon dioxide lake
FACT_2_EXACT_QUERIES: lake bubbles, gas bubbles water
FACT_2_REPRESENTATION_QUERIES: soda bubbles, fizzing water
FACT_2_CONCEPT_QUERIES: none
FACT_3_SCRIPT: Pipes now vent it nonstop, and every local knows exactly why
FACT_3_SUBJECT: degassing pipe fountain
FACT_3_EXACT_QUERIES: water fountain lake, geyser
FACT_3_REPRESENTATION_QUERIES: lake fountain, water jet
FACT_3_CONCEPT_QUERIES: none
CASE_HEADER: Lake Nyos, Cameroon
CASE_DATE: 21.08.1986
STAMP: "NOT DROWNED"
TAG_1: 1,746
TAG_LABEL_1: DEAD IN ONE NIGHT
TAG_2: CO₂
TAG_LABEL_2: DISSOLVED IN DEEP WATER
TAG_3: 24/7
TAG_LABEL_3: VENTED SINCE 2001
SCREEN_HOOK: THIS LAKE KILLED 1,746
"""


def _w(word: str, start: float, end: float | None = None) -> dict:
    return {"word": word, "start": start, "end": end if end is not None else start + 0.25}


class CleanFieldTest(unittest.TestCase):
    def test_uppercases_and_strips_quotes_and_markdown(self):
        self.assertEqual(casefile.clean_field(' "Lake  Nyos" ', 32), "LAKE NYOS")
        self.assertEqual(casefile.clean_field("**stamp**", 14), "STAMP")

    def test_none_empty_and_too_long_become_none(self):
        for value in (None, "", "none", "None", "N/A", "-"):
            self.assertIsNone(casefile.clean_field(value, 10))
        self.assertIsNone(casefile.clean_field("WAY TOO LONG FOR THIS SLOT", 7))

    def test_subscript_two_is_normalized(self):
        self.assertEqual(casefile.clean_field("CO₂", 7), "CO2")


class ExtractFieldsTest(unittest.TestCase):
    def test_reads_every_field_and_strips_the_lines(self):
        stripped, fields = casefile.extract_fields(FACTS_RAW)
        self.assertEqual(fields["header"], "LAKE NYOS, CAMEROON")
        self.assertEqual(fields["date"], "21.08.1986")
        self.assertEqual(fields["stamp"], "NOT DROWNED")
        self.assertEqual(fields["tags"], [("1,746", "DEAD IN ONE NIGHT"), ("CO2", "DISSOLVED IN DEEP WATER"), ("24/7", "VENTED SINCE 2001")])
        for name in ("CASE_HEADER", "CASE_DATE", "STAMP", "TAG_1", "TAG_LABEL_3"):
            self.assertNotIn(name + ":", stripped)
        self.assertIn("FACT_3_CONCEPT_QUERIES: none", stripped)

    def test_missing_lines_never_raise(self):
        _, fields = casefile.extract_fields("TOPIC: x\nHOOK: y")
        self.assertIsNone(fields["header"])
        self.assertEqual(fields["tags"], [(None, None)] * 3)

    def test_invalid_tag_hides_only_that_tag(self):
        _, fields = casefile.extract_fields("TAG_1: ELEVEN CHARS\nTAG_LABEL_1: OK LABEL\nTAG_2: 25 KM")
        self.assertEqual(fields["tags"][0], (None, "OK LABEL"))
        self.assertEqual(fields["tags"][1], ("25 KM", None))


class PlanIntegrationTest(unittest.TestCase):
    def test_facts_parser_ignores_casefile_lines_and_keeps_them(self):
        parsed = _parse_response("facts", FACTS_RAW)
        self.assertEqual(len(parsed["facts"]), 3)
        self.assertTrue(parsed["facts"][0]["script_text"].endswith("drowned."))
        self.assertEqual(parsed["casefile"]["stamp"], "NOT DROWNED")
        self.assertEqual(parsed["screen_hook"], "THIS LAKE KILLED 1,746")

    def test_tags_go_into_the_keywords_json_without_breaking_the_visual_plan(self):
        parsed = _parse_response("facts", FACTS_RAW)
        _apply_casefile_tags(parsed)
        beat = {"keywords": parsed["facts"][0]["keywords"]}
        self.assertEqual(casefile.beat_tag(beat), ("1,746", "DEAD IN ONE NIGHT"))
        plan = _parse_beat_visual_plan(beat["keywords"])
        self.assertEqual(plan["subject"], "Lake Nyos")
        self.assertIn("Lake Nyos", plan["exact"])

    def test_beat_tag_tolerates_old_rows(self):
        self.assertEqual(casefile.beat_tag({"keywords": "lake, water"}), (None, None))
        self.assertEqual(casefile.beat_tag({"keywords": None}), (None, None))


class AppliesTest(unittest.TestCase):
    def test_flag_and_template(self):
        on = {"VISUAL_STYLE": "casefile"}
        self.assertTrue(casefile.applies("facts", on))
        self.assertTrue(casefile.applies("sauce_recipe", on))
        self.assertFalse(casefile.applies("programming", on))
        self.assertFalse(casefile.applies("facts", {"VISUAL_STYLE": "comic"}))
        self.assertFalse(casefile.applies("facts", {}))

    def test_prompt_block_states_the_limits(self):
        block = casefile.prompt_block("facts")
        for field in ("CASE_HEADER", "CASE_DATE", "STAMP", "TAG_1", "TAG_LABEL_3"):
            self.assertIn(field + ":", block)
        self.assertIn(f"max {casefile.LIMITS['TAG']} characters", block)
        self.assertIn("RECIPE", casefile.KICKER["sauce_recipe"])


class CaptionChunksTest(unittest.TestCase):
    def test_numbers_and_tag_words_stand_alone(self):
        words = [_w("This", 0.0), _w("lake", 0.3), _w("killed", 0.6), _w("1,746", 0.9), _w("people", 2.7)]
        chunks = casefile.caption_chunks(words, solo=set())
        self.assertEqual([[x["word"] for x in c] for c in chunks], [["This", "lake"], ["killed"], ["1,746"], ["people"]])
        chunks = casefile.caption_chunks([_w("burst", 0), _w("like", 0.3), _w("soda", 0.6)], solo={"soda"})
        self.assertEqual([[x["word"] for x in c] for c in chunks], [["burst", "like"], ["soda"]])

    def test_new_card_after_sentence_end_and_char_limit(self):
        words = [_w("drowned.", 0.0), _w("Its", 0.4), _w("extraordinarily", 0.7), _w("deep", 1.2)]
        chunks = casefile.caption_chunks(words, solo=set())
        self.assertEqual([[x["word"] for x in c] for c in chunks], [["drowned."], ["Its"], ["extraordinarily"], ["deep"]])

    def test_chunk_at_holds_then_hands_over(self):
        chunks = [[_w("a", 0.0, 0.2)], [_w("b", 1.0, 1.2)]]
        self.assertEqual(casefile.chunk_at(chunks, 0.1), 0)
        self.assertEqual(casefile.chunk_at(chunks, 0.4), 0)  # within the 0.25 s hold
        self.assertEqual(casefile.chunk_at(chunks, 0.6), -1)
        self.assertEqual(casefile.chunk_at(chunks, 1.1), 1)


class EffectsPlanTest(unittest.TestCase):
    def test_snaps_punches_and_flashes(self):
        segments = [
            {"start": 0, "frames": 75, "kind": "video"},
            {"start": 75, "frames": 60, "kind": "card"},
            {"start": 135, "frames": 90, "kind": "video"},
        ]
        fx = casefile.plan_effects(segments, beat_starts=[0.0, 4.5, 9.0])
        self.assertEqual(fx["snaps"], [135])  # never on frame 0, never on a card
        self.assertEqual(fx["punches"], [(37, 75), (180, 225)])  # clips over 2.4 s
        self.assertEqual(fx["flashes"], [135, 270])  # beats 2 and 3


class MusicTest(unittest.TestCase):
    def test_facts_gets_the_bed_with_a_stable_in_range_offset(self):
        a = casefile.pick_music("facts", "video-1", 25.0, duration_of=lambda p: 200.0)
        b = casefile.pick_music("facts", "video-1", 25.0, duration_of=lambda p: 200.0)
        self.assertEqual(a, b)
        self.assertTrue(0.0 <= a["offset"] <= 200.0 - 25.0 - 4.0)
        self.assertIn("CC BY 4.0", a["credit"])
        offsets = {casefile.pick_music("facts", f"v{i}", 25.0, duration_of=lambda p: 200.0)["offset"] for i in range(20)}
        self.assertGreater(len(offsets), 10)  # consecutive Shorts don't share the opening bars

    def test_sauce_keeps_the_default_pool(self):
        self.assertIsNone(casefile.pick_music("sauce_recipe", "v", 25.0, duration_of=lambda p: 200.0))


class SegmentPlanTest(unittest.TestCase):
    def test_image_last_puts_the_card_at_the_end_and_keeps_the_frame_count(self):
        plan = _plan_beat_segments(9.0, use_image=True, segment_seconds=2.5, image_seconds=2.0, image_last=True)
        self.assertEqual(plan[-1], {"kind": "image", "frames": 60})
        self.assertTrue(all(s["kind"] == "video" for s in plan[:-1]))
        self.assertEqual(sum(s["frames"] for s in plan), 270)
        self.assertGreaterEqual(len(plan), 4)  # ~2.5 s cuts, not 5 s

    def test_default_still_puts_the_photo_first(self):
        plan = _plan_beat_segments(9.0, use_image=True)
        self.assertEqual(plan[0]["kind"], "image")


class MusicCreditTest(unittest.TestCase):
    CREDIT = 'Music: "Darkest Child" by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0'

    def test_goes_above_the_hashtag_line(self):
        out = _append_music_credit("Line one.\n\nSubscribe to ByteBits.\n#Shorts #Facts", self.CREDIT)
        self.assertTrue(out.endswith("#Shorts #Facts"))
        self.assertIn(self.CREDIT + "\n\n#Shorts", out)

    def test_appends_when_no_hashtags_and_is_idempotent(self):
        out = _append_music_credit("Just text.", self.CREDIT)
        self.assertTrue(out.endswith(self.CREDIT))
        self.assertEqual(_append_music_credit(out, self.CREDIT), out)

    def test_trims_the_body_not_the_credit(self):
        out = _append_music_credit("x" * 5000 + "\n#Shorts", self.CREDIT)
        self.assertLessEqual(len(out), 5000)
        self.assertIn(self.CREDIT, out)


class LayerDrawSmokeTest(unittest.TestCase):
    def test_draws_the_hook_frame_and_hides_captions_at_the_seam(self):
        def beat(tag, label, dur):
            return {"duration": dur, "keywords": json.dumps({"exact": [], "tag": tag, "tag_label": label})}

        video = {"template": "facts", "style_json": json.dumps({"header": "LAKE NYOS, CAMEROON", "date": "21.08.1986", "stamp": "NOT DROWNED"})}
        beats = [beat("1,746", "DEAD IN ONE NIGHT", 5.0), beat("CO2", "IN THE DEEP WATER", 5.0), beat(None, "VENTED SINCE 2001", 5.0)]
        words = [_w("This", 0.1), _w("lake", 0.4), _w("drowned.", 4.0), _w("Its", 5.1), _w("why", 14.5)]
        layer = casefile._Layer(video, beats, words, duration=15.0)
        self.assertEqual(layer.t_stamp, 4.0)
        self.assertEqual(layer.tag_index(0.0), 0)
        self.assertEqual(layer.tag_index(6.0), 1)
        self.assertEqual(layer.tag_index(14.8), 0)  # loop seam shows beat 1's tag again

        frame0 = Image.new("RGBA", (casefile.W, casefile.H), (90, 90, 90, 255))
        layer.draw(frame0, 0.0)
        tag_box = np.asarray(frame0.crop((200, casefile.TAG_Y - 80, 880, casefile.TAG_Y + 80)).convert("RGB")).astype(int)
        reds = int(((tag_box[..., 0] > 200) & (tag_box[..., 1] < 90) & (tag_box[..., 2] < 90)).sum())
        self.assertGreater(reds, 1000)  # the red 1,746 is fully drawn on frame 0

        seam = Image.new("RGBA", (casefile.W, casefile.H), (90, 90, 90, 255))
        layer.draw(seam, 14.8)
        cap_box = np.asarray(seam.crop((90, casefile.CAPTION_Y - 70, 990, casefile.CAPTION_Y + 70)).convert("RGB")).astype(int)
        self.assertLess(int(cap_box.max() - cap_box.min()), 40)  # only gradient shading: no caption in the loop seam


if __name__ == "__main__":
    unittest.main()
