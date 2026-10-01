from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_BYTES = 8


@dataclass(frozen=True)
class AudioPacket:
    epoch: int
    sequence: int
    pcm16: bytes


def decode_audio_packet(payload: bytes) -> AudioPacket:
    if len(payload) < HEADER_BYTES:
        raise ValueError("audio packet is missing its header")
    epoch, sequence = struct.unpack_from("<II", payload)
    pcm16 = payload[HEADER_BYTES:]
    if not pcm16 or len(pcm16) % 2:
        raise ValueError("audio packet must contain non-empty 16-bit PCM")
    return AudioPacket(epoch=epoch, sequence=sequence, pcm16=pcm16)


def encode_audio_packet(epoch: int, sequence: int, pcm16: bytes) -> bytes:
    if not pcm16 or len(pcm16) % 2:
        raise ValueError("pcm16 must be non-empty and aligned")
    return struct.pack("<II", epoch, sequence) + pcm16
