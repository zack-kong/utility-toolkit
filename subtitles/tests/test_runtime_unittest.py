import asyncio
import unittest

import numpy as np

from server.app.models import Transcript
from server.app.session import SubtitleSession


class FakeModels:
    def transcribe(self, audio, mode, language_hint, context="", hotwords=""):
        return Transcript("hello world", "en", 0.98)

    def translate(self, text, language, glossary="", target_language="zh", context="", term_pack_enabled=True):
        return "你好世界"


class FakeSilero:
    def has_speech(self, audio, audio_mode):
        return True


class SubtitleSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []

        async def record(event):
            self.events.append(event)

        self.session = SubtitleSession("test", FakeModels(), record, mode="fast")
        self.session.silero = FakeSilero()

    async def send_audio(self, count, value=0.1):
        packet = np.full(320, int(value * 32767), dtype="<i2").tobytes()
        for sequence in range(count):
            await self.session.accept_audio(self.session.epoch, sequence, packet)
        await asyncio.sleep(0.05)

    async def test_fast_preview_then_final(self):
        await self.send_audio(50)
        previews = [event for event in self.events if event["type"] == "subtitle"]
        self.assertTrue(previews)
        self.assertFalse(previews[-1]["final"])
        silence = np.zeros(320, dtype="<i2").tobytes()
        for sequence in range(50, 85):
            await self.session.accept_audio(0, sequence, silence)
        await asyncio.sleep(0.05)
        subtitles = [event for event in self.events if event["type"] == "subtitle"]
        self.assertTrue(subtitles[-1]["final"])
        self.assertEqual(subtitles[-1]["utterance_id"], previews[-1]["utterance_id"])

    async def test_old_epoch_audio_is_ignored(self):
        self.session.reset(1)
        packet = np.full(320, 1000, dtype="<i2").tobytes()
        await self.session.accept_audio(0, 1, packet)
        self.assertEqual(self.session.utterance_samples, 0)


if __name__ == "__main__":
    unittest.main()
