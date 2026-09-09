"""Pure-logic test for pipeline/voice.py's real-bug fix: retrying an
edge_tts synthesis call on the library's own NoAudioReceived exception
(a known transient failure of its free backend, not a config problem)
-- no real network calls, per CLAUDE.md's testing rules. Mocks
edge_tts.Communicate itself."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import edge_tts

from pipeline.voice import EDGE_TTS_RETRY_DELAYS, _synth_one_edge_tts_call


def _fake_communicate_class(stream_side_effect):
    """A stand-in for edge_tts.Communicate whose .stream() either raises
    or yields a real WordBoundary + audio chunk sequence, per call."""

    def _make(*args, **kwargs):
        instance = MagicMock()

        async def _stream():
            outcome = stream_side_effect.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            for chunk in outcome:
                yield chunk

        instance.stream = _stream
        return instance

    return _make


_ONE_WORD_STREAM = [
    {"type": "audio", "data": b"fake-audio-bytes"},
    {"type": "WordBoundary", "offset": 0, "duration": 1_000_000, "text": "hi"},
]


class SynthOneEdgeTtsCallRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_succeeds_immediately_no_retry_needed(self, tmp_path=None):
        out_path = Path("/tmp/test_voice_out1.mp3")
        with patch("edge_tts.Communicate", _fake_communicate_class([_ONE_WORD_STREAM])), patch(
            "asyncio.sleep", new=AsyncMock()
        ) as mock_sleep:
            words = await _synth_one_edge_tts_call("hi", out_path)
        self.assertEqual(len(words), 1)
        mock_sleep.assert_not_called()
        out_path.unlink(missing_ok=True)

    async def test_retries_on_no_audio_received_then_succeeds(self):
        out_path = Path("/tmp/test_voice_out2.mp3")
        side_effect = [edge_tts.exceptions.NoAudioReceived("no audio"), _ONE_WORD_STREAM]
        with patch("edge_tts.Communicate", _fake_communicate_class(side_effect)), patch(
            "asyncio.sleep", new=AsyncMock()
        ) as mock_sleep:
            words = await _synth_one_edge_tts_call("hi", out_path)
        self.assertEqual(len(words), 1)
        mock_sleep.assert_awaited_once()
        out_path.unlink(missing_ok=True)

    async def test_gives_up_after_exhausting_retries(self):
        out_path = Path("/tmp/test_voice_out3.mp3")
        side_effect = [edge_tts.exceptions.NoAudioReceived("no audio")] * (len(EDGE_TTS_RETRY_DELAYS) + 1)
        with patch("edge_tts.Communicate", _fake_communicate_class(side_effect)), patch(
            "asyncio.sleep", new=AsyncMock()
        ):
            with self.assertRaises(edge_tts.exceptions.NoAudioReceived):
                await _synth_one_edge_tts_call("hi", out_path)
        out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
