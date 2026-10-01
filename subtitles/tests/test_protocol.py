import pytest

from server.app.protocol import decode_audio_packet, encode_audio_packet


def test_audio_packet_round_trip() -> None:
    payload = encode_audio_packet(7, 42, b"\x00\x00\xff\x7f")
    packet = decode_audio_packet(payload)
    assert (packet.epoch, packet.sequence, packet.pcm16) == (7, 42, b"\x00\x00\xff\x7f")


@pytest.mark.parametrize("payload", [b"", b"\0" * 8, b"\0" * 9])
def test_audio_packet_rejects_invalid_payload(payload: bytes) -> None:
    with pytest.raises(ValueError):
        decode_audio_packet(payload)
