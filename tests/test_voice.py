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

import aiohttp
import edge_tts

from pipeline.voice import (
    EDGE_TTS_RETRY_DELAYS,
    _is_transient_edge_tts_error,
    _synth_one_edge_tts_call,
)


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


def _http_error(status: int, handshake: bool = True) -> aiohttp.ClientResponseError:
    cls = aiohttp.WSServerHandshakeError if handshake else aiohttp.ClientResponseError
    return cls(MagicMock(), (), status=status, message="Invalid response status")


class TransientErrorClassificationTest(unittest.TestCase):
    def test_retryable(self):
        for exc in (
            edge_tts.exceptions.NoAudioReceived("x"),
            _http_error(403),  # the real 2026-10-12 failure
            _http_error(429),
            _http_error(503),
            aiohttp.ServerDisconnectedError(),
            asyncio.TimeoutError(),
        ):
            self.assertTrue(_is_transient_edge_tts_error(exc), repr(exc))

    def test_not_retryable_so_real_problems_fail_fast(self):
        for exc in (
            _http_error(400),
            _http_error(404, handshake=False),
            aiohttp.ClientConnectorCertificateError(MagicMock(), Exception("self-signed certificate")),
            ValueError("bad voice name"),
            RuntimeError("boom"),
        ):
            self.assertFalse(_is_transient_edge_tts_error(exc), repr(exc))


class HandshakeRetryTest(unittest.IsolatedAsyncioTestCase):
    async def test_retries_a_403_handshake_then_succeeds(self):
        out_path = Path("/tmp/test_voice_out4.mp3")
        side_effect = [_http_error(403), _http_error(403), _ONE_WORD_STREAM]
        with patch("edge_tts.Communicate", _fake_communicate_class(side_effect)), patch(
            "asyncio.sleep", new=AsyncMock()
        ) as mock_sleep:
            words = await _synth_one_edge_tts_call("hi", out_path)
        self.assertEqual(len(words), 1)
        self.assertEqual(mock_sleep.await_count, 2)
        out_path.unlink(missing_ok=True)

    async def test_a_persistent_403_gives_up_with_the_original_error(self):
        out_path = Path("/tmp/test_voice_out5.mp3")
        side_effect = [_http_error(403)] * (len(EDGE_TTS_RETRY_DELAYS) + 1)
        with patch("edge_tts.Communicate", _fake_communicate_class(side_effect)), patch(
            "asyncio.sleep", new=AsyncMock()
        ), self.assertRaises(aiohttp.WSServerHandshakeError):
            await _synth_one_edge_tts_call("hi", out_path)
        out_path.unlink(missing_ok=True)

    async def test_a_config_error_is_not_retried(self):
        out_path = Path("/tmp/test_voice_out6.mp3")
        with patch("edge_tts.Communicate", _fake_communicate_class([ValueError("bad voice")])), patch(
            "asyncio.sleep", new=AsyncMock()
        ) as mock_sleep, self.assertRaises(ValueError):
            await _synth_one_edge_tts_call("hi", out_path)
        mock_sleep.assert_not_called()
        out_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
