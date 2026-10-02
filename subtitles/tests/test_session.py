import asyncio
import threading

import numpy as np

from server.app.audio import SAMPLE_RATE
from server.app.models import Transcript
from server.app.session import PRE_ROLL_SAMPLES, SubtitleSession, remove_overlap, stable_prefix


def test_stable_prefix() -> None:
    assert stable_prefix("hello local world", "hello local model") == "hello local"
    assert stable_prefix("hello work", "hello world") == "hello"
    assert stable_prefix("hel", "hello") == ""
    assert stable_prefix("なんだよ知らない", "なんだよ知らねえ") == "なんだよ知ら"
    assert stable_prefix("one", "two") == ""


def test_vlog_uses_lower_streaming_gate() -> None:
    session = SubtitleSession("test", None, None, audio_mode="vlog")  # type: ignore[arg-type]
    assert session.vad.threshold == 0.002
    assert SubtitleSession("test", None, None).vad.threshold == 0.004  # type: ignore[arg-type]


def test_forced_chunk_transcript_overlap_is_removed() -> None:
    assert remove_overlap("なんだよ知らねえ", "知らねえことばっか") == "ことばっか"
    assert remove_overlap("hello world", "world again") == "again"
    assert remove_overlap("hello world", "something else") == "something else"
    assert remove_overlap("はい", "はい") == "はい"


def test_epoch_reset_discards_transient_caption() -> None:
    session = SubtitleSession(session_id="test", models=None, send=None, epoch=1)  # type: ignore[arg-type]
    session.last_preview_text = "old caption"
    session.last_sequence = 3
    session.reset(2)
    assert session.epoch == 2
    assert session.last_preview_text == ""
    assert session.last_sequence == -1
    assert session.overlap_tail is None
    assert session.last_final_id == -1


def test_old_epoch_does_not_reset_session() -> None:
    session = SubtitleSession(session_id="test", models=None, send=None, epoch=2)  # type: ignore[arg-type]
    session.reset(2)
    assert session.epoch == 2


def test_flush_sends_buffered_final_caption() -> None:
    events: list[dict[str, object]] = []

    async def send(event: dict[str, object]) -> None:
        events.append(event)

    session = SubtitleSession(session_id="test", models=None, send=send)  # type: ignore[arg-type]
    session.utterance = [np.ones(16000, dtype=np.float32)]
    session.utterance_samples = 16000
    session.vad.speech_seen = True
    session._infer = lambda audio, hint, overlap_text="", preview_id=None: ("hello", "你好", "en", 0.99)  # type: ignore[method-assign]
    asyncio.run(session.flush())
    assert events[-1]["type"] == "subtitle"
    assert events[-1]["final"] is True


def test_pause_flushes_short_speech_without_changing_epoch() -> None:
    events: list[dict[str, object]] = []

    async def send(event: dict[str, object]) -> None:
        events.append(event)

    async def run() -> None:
        session = SubtitleSession("test", None, send)  # type: ignore[arg-type]
        session._infer = lambda audio, hint, overlap_text="", preview_id=None: ("yes", "是", "en", 0.99)  # type: ignore[method-assign]
        speech = np.full(SAMPLE_RATE // 5, 500, dtype="<i2").tobytes()
        await session.accept_audio(0, 0, speech)
        assert session.utterance_samples == SAMPLE_RATE // 5
        await session.flush()
        assert session.epoch == 0

    asyncio.run(run())
    assert [(event["original"], event["final"]) for event in events] == [("yes", True)]


def test_fast_mode_does_not_repeat_inference_each_second() -> None:
    events: list[dict[str, object]] = []

    async def send(event: dict[str, object]) -> None:
        events.append(event)

    async def run() -> None:
        session = SubtitleSession(session_id="test", models=None, send=send, mode="fast")  # type: ignore[arg-type]
        session._infer = lambda audio, hint, overlap_text="", preview_id=None: ("hello", "你好", "en", 0.99)  # type: ignore[method-assign]
        packet = np.full(16000, 0.1, dtype="<f4")
        pcm = (packet * 32767).astype("<i2").tobytes()
        for second in range(1, 7):
            await session.accept_audio(0, second, pcm)
            if session.processing_task is not None:
                await session.processing_task
            if second == 3:
                assert len(events) == 2
        assert [event["final"] for event in events] == [False, False, False, True]

    asyncio.run(run())


def test_slow_inference_queues_speech_instead_of_discarding_it() -> None:
    events: list[dict[str, object]] = []
    started = threading.Event()
    release = threading.Event()

    async def send(event: dict[str, object]) -> None:
        events.append(event)

    def infer(audio: np.ndarray, hint: str | None, overlap_text: str = "",
              preview_id: int | None = None) -> tuple[str, str, str, float]:
        started.set()
        release.wait(timeout=5)
        return f"samples {audio.size}", "译文", "ja", 0.99

    async def run() -> None:
        session = SubtitleSession(session_id="test", models=None, send=send)  # type: ignore[arg-type]
        session._infer = infer  # type: ignore[method-assign]
        pcm = np.full(SAMPLE_RATE, 1000, dtype="<i2").tobytes()
        try:
            for sequence in range(18):
                await session.accept_audio(0, sequence, pcm)
                if sequence == 5:
                    await asyncio.to_thread(started.wait, 5)
            assert session.utterance_samples == 0
            assert len(session.pending_finals) == 2
        finally:
            release.set()
        await session.flush()
        subtitles = [event for event in events if event["type"] == "subtitle"]
        assert [event["utterance_id"] for event in subtitles] == [0, 1, 2]
        assert all(event["original"].startswith("samples ") for event in subtitles)
        assert subtitles[0]["original"] == "samples 96000"

    asyncio.run(run())


def test_long_silence_keeps_short_lead_in_instead_of_forcing_a_split() -> None:
    processed_lengths: list[int] = []

    async def send(event: dict[str, object]) -> None:
        pass

    def infer(audio: np.ndarray, hint: str | None, overlap_text: str = "",
              preview_id: int | None = None) -> tuple[str, str, str, float]:
        processed_lengths.append(audio.size)
        return "short phrase", "短句", "en", 0.99

    async def run() -> None:
        session = SubtitleSession("test", None, send)  # type: ignore[arg-type]
        session._infer = infer  # type: ignore[method-assign]
        silence = np.zeros(SAMPLE_RATE, dtype="<i2").tobytes()
        for sequence in range(10):
            await session.accept_audio(0, sequence, silence)
        assert session.utterance_samples == PRE_ROLL_SAMPLES
        assert not session.pending_finals
        assert session.processing_task is None
        speech = np.full(SAMPLE_RATE // 5, 200, dtype="<i2").tobytes()
        await session.accept_audio(0, 10, speech)
        await session.accept_audio(0, 11, np.zeros(SAMPLE_RATE * 7 // 10, dtype="<i2").tobytes())
        await session.flush()

    asyncio.run(run())
    assert processed_lengths == [PRE_ROLL_SAMPLES + SAMPLE_RATE // 5 + SAMPLE_RATE * 7 // 10]


def test_explicit_japanese_language_remains_locked() -> None:
    hints: list[str | None] = []

    async def send(event: dict[str, object]) -> None:
        pass

    async def run() -> None:
        session = SubtitleSession(session_id="test", models=None, send=send,
                                  language_hint="ja", language_locked=True)  # type: ignore[arg-type]

        def infer(audio: np.ndarray, hint: str | None, overlap_text: str = "",
                  preview_id: int | None = None) -> tuple[str, str, str, float]:
            hints.append(hint)
            return "日本語", "日语", "en", 0.99

        session._infer = infer  # type: ignore[method-assign]
        session.utterance = [np.ones(SAMPLE_RATE, dtype=np.float32)]
        session.utterance_samples = SAMPLE_RATE
        session.vad.speech_seen = True
        await session.flush()
        assert session.language_hint == "ja"
        assert hints == ["ja"]

    asyncio.run(run())


def test_forced_split_reuses_audio_tail_and_translates_only_new_text() -> None:
    events: list[dict[str, object]] = []
    translated: list[str] = []
    audio_lengths: list[int] = []

    class Models:
        def transcribe(self, audio, mode, language_hint, context="", hotwords=""):
            audio_lengths.append(audio.size)
            return Transcript("なんだよ知らねえ" if len(audio_lengths) == 1 else
                              "知らねえことばっか", "ja", 0.99)

        def translate(self, text, language, glossary="", target_language="zh", context="", term_pack_enabled=True):
            translated.append(text)
            return f"译:{text}"

    class Speech:
        def has_speech(self, audio, audio_mode):
            return True

    async def run() -> None:
        async def send(event):
            events.append(event)

        session = SubtitleSession("test", Models(), send)
        session.silero = Speech()  # type: ignore[assignment]
        pcm = np.full(SAMPLE_RATE, 1000, dtype="<i2").tobytes()
        for sequence in range(6):
            await session.accept_audio(0, sequence, pcm)
        assert session.processing_task is not None
        await session.processing_task
        for sequence in range(6, 12):
            await session.accept_audio(0, sequence, pcm)
        assert session.processing_task is not None
        await session.processing_task

    asyncio.run(run())
    assert audio_lengths[0] == 6 * SAMPLE_RATE
    assert audio_lengths[1] > 6 * SAMPLE_RATE  # includes the preceding half-second
    assert translated == ["なんだよ知らねえ", "ことばっか"]
    assert [event["original"] for event in events if event["type"] == "subtitle"] == [
        "なんだよ知らねえ", "ことばっか"]


def test_queued_final_skips_stale_preview_translation() -> None:
    started = threading.Event()
    release = threading.Event()
    translated: list[str] = []
    events: list[dict[str, object]] = []

    class Models:
        calls = 0

        def transcribe(self, audio, mode, language_hint, context="", hotwords=""):
            self.calls += 1
            if self.calls == 1:
                started.set()
                release.wait(timeout=5)
            return Transcript("hello", "en", 0.99)

        def translate(self, text, language, glossary="", target_language="zh", context="", term_pack_enabled=True):
            translated.append(text)
            return "你好"

    class Speech:
        def has_speech(self, audio, audio_mode):
            return True

    async def run() -> None:
        async def send(event):
            events.append(event)

        session = SubtitleSession("test", Models(), send, mode="fast")
        session.silero = Speech()  # type: ignore[assignment]
        pcm = np.full(SAMPLE_RATE, 1000, dtype="<i2").tobytes()
        await session.accept_audio(0, 0, pcm)
        await asyncio.to_thread(started.wait, 5)
        try:
            for sequence in range(1, 6):
                await session.accept_audio(0, sequence, pcm)
        finally:
            release.set()
        await session.flush()

    asyncio.run(run())
    assert translated == ["hello"]
    assert [event["final"] for event in events if event["type"] == "subtitle"] == [True]


def test_audio_session_passes_selected_target_language() -> None:
    received = []

    class Models:
        def transcribe(self, audio, mode, language_hint, context="", hotwords=""):
            return Transcript("こんにちは", "ja", 0.99)

        def translate(self, text, language, glossary, target_language, context="", term_pack_enabled=True):
            received.append((text, language, target_language))
            return "Hello"

    class Speech:
        def has_speech(self, audio, audio_mode):
            return True

    session = SubtitleSession("test", Models(), lambda event: None, target_language="en")  # type: ignore[arg-type]
    session.silero = Speech()  # type: ignore[assignment]
    assert session._infer(np.ones(SAMPLE_RATE, dtype=np.float32), "ja")[:2] == ("こんにちは", "Hello")
    assert received == [("こんにちは", "ja", "en")]


def test_only_confirmed_same_language_text_becomes_bounded_context() -> None:
    received: list[tuple[str, str, str]] = []

    class Models:
        calls = 0

        def transcribe(self, audio, mode, language_hint, context="", hotwords=""):
            self.calls += 1
            received.append(("asr", context, hotwords))
            return Transcript("Donald Duck" if self.calls <= 2 else "He is funny", "en", 0.99)

        def translate(self, text, language, glossary="", target_language="zh", context="", term_pack_enabled=True):
            received.append(("translation", context, text))
            return "唐老鸭" if text == "Donald Duck" else "他很有趣"

    class Speech:
        def has_speech(self, audio, audio_mode):
            return True

    async def run() -> SubtitleSession:
        async def send(event):
            pass

        session = SubtitleSession("test", Models(), send, language_hint="en", language_locked=True,
                                  glossary="en|Donald Duck = 唐老鸭")
        session.silero = Speech()  # type: ignore[assignment]
        audio = np.ones(SAMPLE_RATE, dtype=np.float32)
        await session._process(audio, 0, 0, False, False, 0)
        assert not session.confirmed_text
        await session._process(audio, 0, 0, True, False, 0)
        await session._process(audio, 0, 1, True, False, 24)
        return session

    session = asyncio.run(run())
    assert received[0] == ("asr", "", "Donald Duck")
    assert received[2] == ("asr", "", "Donald Duck")
    assert received[4] == ("asr", "Donald Duck", "Donald Duck")
    assert received[5] == ("translation", "Donald Duck → 唐老鸭", "He is funny")
    assert session.diagnostics()["samples"] == 3
    assert session.diagnostics()["latest"]["queue_ms"] == 24
    session.reset(1)
    assert not session.confirmed_text
    assert not session.confirmed_dialogue
    assert session.diagnostics()["samples"] == 0


def test_topic_context_uses_only_final_dialogue_and_drops_old_lines() -> None:
    contexts = []

    class Models:
        calls = 0

        def transcribe(self, audio, mode, language_hint, context="", hotwords=""):
            self.calls += 1
            return Transcript(f"line {self.calls}", "en", 0.99)

        def translate(self, text, language, glossary, target_language, context, term_pack_enabled=True):
            contexts.append(context)
            return f"译文 {text}"

    class Speech:
        def has_speech(self, audio, audio_mode):
            return True

    async def run() -> SubtitleSession:
        async def send(event):
            pass

        session = SubtitleSession("test", Models(), send, mode="fast")
        session.silero = Speech()  # type: ignore[assignment]
        audio = np.ones(SAMPLE_RATE, dtype=np.float32)
        await session._process(audio, 0, 0, False, False, 0)
        for index in range(1, 9):
            await session._process(audio, 0, index, True, False, 0)
        return session

    session = asyncio.run(run())
    assert contexts[0] == contexts[1] == ""  # A preview never becomes topic evidence.
    assert "line 2 → 译文 line 2" in contexts[2]
    assert len(session.confirmed_dialogue) == 6
    assert session.confirmed_dialogue[0][0] == "line 4"
    assert "line 1" not in contexts[-1]
    assert len(contexts[-1]) <= 240


def test_context_excludes_other_languages_and_limits_length() -> None:
    received = []

    class Models:
        def transcribe(self, audio, mode, language_hint, context="", hotwords=""):
            received.append((context, hotwords))
            return Transcript("hello", "en", 0.99)

        def translate(self, text, language, glossary, target_language, context, term_pack_enabled=True):
            return "你好"

    class Speech:
        def has_speech(self, audio, audio_mode):
            return True

    session = SubtitleSession("test", Models(), lambda event: None,
                              language_hint="en", language_locked=True)  # type: ignore[arg-type]
    session.silero = Speech()  # type: ignore[assignment]
    session.confirmed_text.extend([("ja", "日本語"), ("en", "a" * 120), ("en", "b" * 120)])
    session._infer(np.ones(SAMPLE_RATE, dtype=np.float32), "en")
    assert len(received[0][0]) == 160
    assert "日本語" not in received[0][0]
    assert received[0][0].endswith("b" * 120)
