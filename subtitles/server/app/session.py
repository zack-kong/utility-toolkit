from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import numpy as np

from .audio import SAMPLE_RATE, StreamingVad, pcm16_to_float32, rms
from .glossary import parse_glossary
from .models import ModelRegistry
from .vad import SileroSpeechValidator

SendEvent = Callable[[dict[str, object]], Awaitable[None]]


def stable_prefix(previous: str, current: str) -> str:
    length = 0
    for old, new in zip(previous, current):
        if old != new:
            break
        length += 1
    prefix = previous[:length]
    continues_word = ((length < len(previous) and previous[length].isascii() and previous[length].isalpha())
                      or (length < len(current) and current[length].isascii() and current[length].isalpha()))
    if prefix and continues_word:
        # Do not mark half an alphabetic word as stable; Japanese has no word spaces.
        if prefix[-1].isascii() and prefix[-1].isalpha():
            prefix = prefix.rsplit(" ", 1)[0] if " " in prefix else ""
    return prefix.rstrip()


def remove_overlap(previous: str, current: str) -> str:
    """Remove only an exact transcript overlap caused by a forced audio split."""
    for length in range(min(20, len(previous), len(current) - 1), 1, -1):
        if previous[-length:] == current[:length] and len(current[:length].strip()) >= 2:
            return current[length:].lstrip()
    return current


OVERLAP_SAMPLES = SAMPLE_RATE // 2
PRE_ROLL_SAMPLES = SAMPLE_RATE * 3 // 10
PREVIEW_INTERVAL_SAMPLES = 2 * SAMPLE_RATE


@dataclass
class SubtitleSession:
    session_id: str
    models: ModelRegistry
    send: SendEvent
    mode: str = "accurate"
    audio_mode: str = "dialogue"
    epoch: int = 0
    language_hint: str | None = None
    language_locked: bool = False
    language_candidate: str | None = None
    language_candidate_count: int = 0
    glossary: str = ""
    target_language: str = "zh"
    term_pack_enabled: bool = True
    utterance: list[np.ndarray] = field(default_factory=list)
    utterance_samples: int = 0
    utterance_id: int = 0
    pending_finals: deque[tuple[np.ndarray, int, int, bool, float]] = field(default_factory=deque)
    confirmed_text: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=3))
    confirmed_dialogue: deque[tuple[str, str]] = field(default_factory=lambda: deque(maxlen=6))
    timing_samples: deque[dict[str, int]] = field(default_factory=lambda: deque(maxlen=50))
    inference_timing: tuple[int, int] = (0, 0)
    last_sequence: int = -1
    last_preview_at: int = 0
    last_preview_text: str = ""
    last_final_text: str = ""
    last_final_id: int = -1
    overlap_tail: np.ndarray | None = None
    overlap_wait_samples: int = 0
    utterance_has_overlap: bool = False
    vad: StreamingVad = field(default_factory=StreamingVad)
    silero: SileroSpeechValidator = field(default_factory=SileroSpeechValidator)
    processing_task: asyncio.Task[None] | None = None
    closed: bool = False

    def reset(self, epoch: int) -> None:
        if epoch <= self.epoch:
            return
        self.epoch = epoch
        self.utterance.clear()
        self.pending_finals.clear()
        self.confirmed_text.clear()
        self.confirmed_dialogue.clear()
        self.timing_samples.clear()
        self.utterance_samples = 0
        self.utterance_id += 1
        self.last_sequence = -1
        self.last_preview_at = 0
        self.last_preview_text = ""
        self.last_final_text = ""
        self.last_final_id = -1
        self.overlap_tail = None
        self.overlap_wait_samples = 0
        self.utterance_has_overlap = False
        self.vad.reset()

    async def _finish_utterance(self, forced: bool = False) -> None:
        if not self.utterance_samples:
            return
        audio = np.concatenate(self.utterance)
        had_speech = self.vad.speech_seen
        current_id = self.utterance_id
        had_overlap = self.utterance_has_overlap
        self.utterance.clear()
        self.utterance_samples = 0
        self.utterance_has_overlap = False
        self.utterance_id += 1
        self.last_preview_at = 0
        self.vad.reset()
        if self.audio_mode == "dialogue" and not had_speech:
            return
        if forced and had_speech:
            self.overlap_tail = audio[-OVERLAP_SAMPLES:].copy()
            self.overlap_wait_samples = 0
        self.pending_finals.append((audio, self.epoch, current_id, had_overlap, time.perf_counter()))
        if len(self.pending_finals) > 8:
            self.pending_finals.popleft()
            await self.send({"type": "status", "state": "backpressure", "epoch": self.epoch,
                             "message": "Inference is far behind; the oldest audio segment was skipped."})

    async def accept_audio(self, epoch: int, sequence: int, pcm16: bytes) -> None:
        if self.closed or epoch != self.epoch or sequence <= self.last_sequence:
            return
        self.last_sequence = sequence
        samples = pcm16_to_float32(pcm16)
        if self.overlap_tail is not None:
            if rms(samples) >= self.vad.threshold:
                self.utterance.append(self.overlap_tail)
                self.utterance_samples += self.overlap_tail.size
                self.vad.observe(self.overlap_tail)
                self.utterance_has_overlap = True
                self.overlap_tail = None
            else:
                self.overlap_wait_samples += samples.size
                if self.overlap_wait_samples >= SAMPLE_RATE // 4:
                    self.overlap_tail = None
        self.utterance.append(samples)
        self.utterance_samples += samples.size
        self.vad.observe(samples)
        if not self.vad.speech_seen:
            # Keep only the lead-in to the next utterance. Long silence must not
            # force-split the first syllable of a new sentence at six seconds.
            while self.utterance_samples > PRE_ROLL_SAMPLES:
                excess = self.utterance_samples - PRE_ROLL_SAMPLES
                first = self.utterance[0]
                if first.size <= excess:
                    self.utterance.pop(0)
                    self.utterance_samples -= first.size
                else:
                    self.utterance[0] = first[excess:].copy()
                    self.utterance_samples -= excess
            return
        forced = self.utterance_samples >= 6 * SAMPLE_RATE
        ending = forced or (
            self.utterance_samples >= int(0.8 * SAMPLE_RATE)
            and self.vad.speech_seen and self.vad.reached_trailing_silence
        )
        if ending:
            await self._finish_utterance(forced=forced)
        await self._schedule_if_ready()

    async def _schedule_if_ready(self) -> None:
        if self.processing_task is not None:
            return
        if self.pending_finals:
            final = True
            audio, current_epoch, current_id, had_overlap, queued_at = self.pending_finals.popleft()
            queue_ms = round((time.perf_counter() - queued_at) * 1000)
        elif self.mode == "fast" and self.utterance_samples >= (
            SAMPLE_RATE if not self.last_preview_at else self.last_preview_at + PREVIEW_INTERVAL_SAMPLES
        ):
            final = False
            audio = np.concatenate(self.utterance)
            current_epoch = self.epoch
            current_id = self.utterance_id
            had_overlap = self.utterance_has_overlap
            self.last_preview_at = self.utterance_samples
            queue_ms = 0
        else:
            return
        if final:
            self.last_preview_at = 0
        self.processing_task = asyncio.create_task(
            self._process(audio, current_epoch, current_id, final, had_overlap, queue_ms))

    async def _process(self, audio: np.ndarray, epoch: int, utterance_id: int,
                       final: bool, had_overlap: bool, queue_ms: int) -> None:
        try:
            self.inference_timing = (0, 0)
            # A locked hint is periodically dropped so a multilingual video can switch languages.
            hint = self.language_hint if self.language_locked or utterance_id % 2 else None
            overlap_text = self.last_final_text if had_overlap and self.last_final_id == utterance_id - 1 else ""
            result = await asyncio.to_thread(self._infer, audio, hint, overlap_text,
                                             None if final else utterance_id)
            if result is None or self.closed or epoch != self.epoch:
                return
            if not final and any(item[2] == utterance_id for item in self.pending_finals):
                return
            original, translation, language, confidence = result
            if final and not self.language_locked and hint is None:
                self._observe_language(language, confidence)
            previous = self.last_preview_text
            self.last_preview_text = "" if final else original
            if final:
                self.last_final_text = original
                self.last_final_id = utterance_id
                self.confirmed_text.append((language, original))
                self.confirmed_dialogue.append((original, translation))
            asr_ms, translation_ms = self.inference_timing
            self.timing_samples.append({"queue_ms": queue_ms, "asr_ms": asr_ms,
                                        "translation_ms": translation_ms})
            await self.send({"type": "subtitle", "epoch": epoch, "utterance_id": utterance_id,
                             "original": original, "translation": translation, "final": final,
                             "stable_prefix": stable_prefix(previous, original)})
        except Exception as error:
            if not self.closed and epoch == self.epoch:
                await self.send({"type": "error", "epoch": epoch, "code": "inference_failed",
                                 "message": str(error)})
        finally:
            if not final and self.utterance_samples >= audio.size + PREVIEW_INTERVAL_SAMPLES:
                # A slow preview must not immediately start another stale preview.
                self.last_preview_at = self.utterance_samples
            self.processing_task = None
            if not self.closed:
                await self._schedule_if_ready()

    def _infer(self, audio: np.ndarray, hint: str | None,
               overlap_text: str = "", preview_id: int | None = None) -> tuple[str, str, str, float] | None:
        self.inference_timing = (0, 0)
        if not self.silero.has_speech(audio, self.audio_mode):
            return None
        confirmed = tuple(self.confirmed_text)
        dialogue = tuple(self.confirmed_dialogue)
        context_language = hint or self.language_hint
        context = " ".join(text for language, text in confirmed
                           if language == context_language)[-160:]
        hotwords = ", ".join(source for language, source, _ in parse_glossary(self.glossary)
                             if language is None or language == context_language)[:100]
        asr_started = time.perf_counter()
        transcript = self.models.transcribe(audio, self.mode, hint, context, hotwords)
        asr_ms = round((time.perf_counter() - asr_started) * 1000)
        self.inference_timing = (asr_ms, 0)
        if not transcript.text:
            return None
        if preview_id is not None and preview_id != self.utterance_id:
            return None
        original = remove_overlap(overlap_text, transcript.text) if overlap_text else transcript.text
        if not original:
            return None
        translation_started = time.perf_counter()
        dialogue_context = "\n".join(f"{source} → {target}" for source, target in dialogue)[-240:]
        translation = (original if transcript.language == self.target_language else
                       self.models.translate(original, transcript.language, self.glossary,
                                             self.target_language, dialogue_context,
                                             self.term_pack_enabled))
        self.inference_timing = (asr_ms, round((time.perf_counter() - translation_started) * 1000))
        return original, translation, transcript.language, transcript.language_probability

    def diagnostics(self) -> dict[str, object]:
        samples = list(self.timing_samples)
        keys = ("queue_ms", "asr_ms", "translation_ms")
        return {"samples": len(samples), "latest": samples[-1] if samples else None,
                "average_ms": {key: round(sum(item[key] for item in samples) / len(samples))
                               for key in keys} if samples else None}

    def _observe_language(self, language: str, probability: float) -> None:
        if self.language_hint is None:
            if probability >= 0.75:
                self.language_hint = language
            return
        if language == self.language_hint or probability < 0.85:
            self.language_candidate = None
            self.language_candidate_count = 0
            return
        if self.language_candidate == language:
            self.language_candidate_count += 1
        else:
            self.language_candidate = language
            self.language_candidate_count = 1
        if self.language_candidate_count >= 3:
            self.language_hint = language
            self.language_candidate = None
            self.language_candidate_count = 0

    def close(self) -> None:
        self.closed = True

    async def flush(self) -> None:
        """Finish buffered speech and any in-flight preview before closing."""
        if self.closed:
            return
        if self.utterance_samples:
            await self._finish_utterance()
        await self._schedule_if_ready()
        while self.processing_task is not None or self.pending_finals:
            task = self.processing_task
            if task is not None:
                await task
            else:
                await self._schedule_if_ready()
