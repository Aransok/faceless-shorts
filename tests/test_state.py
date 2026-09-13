"""Pure-logic tests for pipeline/state.py's Phase 18/20 query helpers
(recent_beats, recent_cta_types) -- runs against a throwaway temp SQLite
file (db_path is an explicit parameter on every state.py function
specifically for this), never the real state.db."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.state import create_video, create_video_steps, get_video, init_db, recent_beats, recent_cta_types, update_video


class StateHelpersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = Path(self._tmp.name)
        self._tmp.close()
        init_db(self.db_path)

    def tearDown(self):
        self.db_path.unlink(missing_ok=True)

    def test_recent_beats_truncates_and_orders_newest_first(self):
        vid1 = create_video("facts", topic="topic one", db_path=self.db_path)
        create_video_steps(
            vid1,
            [
                {"script_text": " ".join(["word"] * 20)},  # over the 15-word truncation limit
                {"script_text": "short fact under the limit"},
            ],
            db_path=self.db_path,
        )
        vid2 = create_video("facts", topic="topic two", db_path=self.db_path)
        create_video_steps(vid2, [{"script_text": "second video fact"}], db_path=self.db_path)

        facts = recent_beats("facts", limit_videos=15, db_path=self.db_path)

        self.assertEqual(facts[0], "second video fact")  # newest video first
        self.assertTrue(facts[1].endswith("..."))  # truncated long fact
        self.assertEqual(len(facts[1].rstrip(".").split()), 15)
        self.assertEqual(facts[2], "short fact under the limit")  # untouched, under the limit

    def test_recent_beats_excludes_other_templates(self):
        vid = create_video("programming", topic="not facts", db_path=self.db_path)
        create_video_steps(vid, [{"script_text": "some code narration"}], db_path=self.db_path)
        self.assertEqual(recent_beats("facts", db_path=self.db_path), [])

    def test_recent_beats_scoped_to_sauce_recipe_independently_of_facts(self):
        # Real bug this guards against (2026-09-10): two consecutive
        # sauce_recipe videos both independently picked chimichurri --
        # recent_beats("sauce_recipe", ...) must see sauce_recipe's own
        # beats, not just facts', and vice versa.
        facts_vid = create_video("facts", topic="a fact theme", db_path=self.db_path)
        create_video_steps(facts_vid, [{"script_text": "octopuses have three hearts"}], db_path=self.db_path)
        sauce_vid = create_video("sauce_recipe", topic="a sauce theme", db_path=self.db_path)
        create_video_steps(sauce_vid, [{"script_text": "chimichurri is parsley and garlic"}], db_path=self.db_path)

        self.assertEqual(recent_beats("sauce_recipe", db_path=self.db_path), ["chimichurri is parsley and garlic"])
        self.assertEqual(recent_beats("facts", db_path=self.db_path), ["octopuses have three hearts"])

    def test_recent_cta_types_returns_most_recent_first(self):
        vid1 = create_video("facts", topic="a", db_path=self.db_path)
        update_video(vid1, db_path=self.db_path, cta_angle="comment_question")
        vid2 = create_video("programming", topic="b", db_path=self.db_path)
        update_video(vid2, db_path=self.db_path, cta_angle="save")

        self.assertEqual(recent_cta_types(limit=1, db_path=self.db_path), ["save"])
        self.assertEqual(recent_cta_types(limit=2, db_path=self.db_path), ["save", "comment_question"])

    def test_recent_cta_types_empty_when_nothing_recorded(self):
        create_video("facts", topic="a", db_path=self.db_path)
        self.assertEqual(recent_cta_types(db_path=self.db_path), [])

    def test_every_add_column_migration_is_writable_via_update_video(self):
        # Real production bug (2026-09-13): family_game_segments_json got
        # a real ALTER TABLE migration in init_db() but was never added to
        # _COLUMNS, update_video()'s separate hardcoded allowlist -- so
        # every real write to it raised "unknown video field(s)" despite
        # the column genuinely existing. Every test elsewhere mocks
        # update_video() entirely, so nothing caught this until a real
        # production run did. Exercise the real function against a real
        # (temp) DB for every column init_db() knows how to migrate, not
        # just the ones a specific feature's own tests happen to mock.
        video_id = create_video("family_game_night", topic="a topic", db_path=self.db_path)
        update_video(video_id, db_path=self.db_path, family_game_segments_json='[{"kind": "host"}]')
        video = get_video(video_id, db_path=self.db_path)
        self.assertEqual(video["family_game_segments_json"], '[{"kind": "host"}]')


if __name__ == "__main__":
    unittest.main()
