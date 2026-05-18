#!/usr/bin/env python3
"""
Convert S16LE stereo PCM (stdin) to IEC958_SUBFRAME_LE (stdout).
Silence blocks sent as pure zeros to avoid noise on HDMI receivers.
"""
import sys
import struct

BLOCK_FRAMES    = 2048
BLOCK_BYTES_IN  = BLOCK_FRAMES * 2 * 2   # S16LE: 2 bytes × 2 ch
SILENCE_THRESHOLD = 64                    # S16 amplitude below which = silence

stdout = sys.stdout.buffer
stdin  = sys.stdin.buffer

frame_count = 0  # 0..191 within 192-frame IEC958 block

while True:
    data = stdin.read(BLOCK_BYTES_IN)
    if not data:
        break
    if len(data) % 4 != 0:
        data += b'\x00' * (4 - len(data) % 4)

    n_samples = len(data) // 2  # total individual S16LE samples

    is_silence = all(abs(struct.unpack_from('<h', data, i * 2)[0]) < SILENCE_THRESHOLD
                     for i in range(n_samples))

    if is_silence:
        stdout.write(b'\x00' * (n_samples * 4))
        stdout.flush()
        continue

    out = bytearray(n_samples * 4)
    for i in range(n_samples):
        sample  = struct.unpack_from('<h', data, i * 2)[0]
        channel = i % 2

        audio24 = (sample & 0xFFFF) << 8           # S16 → 24-bit
        subframe = (audio24 << 4) & 0x0FFFFFF0     # bits 27:4

        if channel == 0:
            preamble = 0x5 if frame_count == 0 else 0x9
        else:
            preamble = 0x6

        struct.pack_into('<I', out, i * 4, subframe | preamble)

        if channel == 1:
            frame_count = (frame_count + 1) % 192

    stdout.write(out)
    stdout.flush()
