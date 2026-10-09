# Copyright 2026 TIER IV, INC. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""The Android boot image a Jetson kernel partition holds.

UEFI reads the kernel partition when `L4TDefaultBootMode` is 2, and takes the kernel,
the ramdisk and the kernel command line -- where a verity root hash lives -- from the
image there. The format is version 0: a header, then the kernel and the ramdisk at
page boundaries. The image build packs one per slot for a flash, and the update agent
packs one on the device for the slot it writes; both call this, so what a device boots
and what it was flashed with are the same bytes.

The addresses are not ours to choose: they are where this SoC's firmware places the
kernel and the ramdisk, read off the image the board was flashed with.
"""

from __future__ import annotations

import hashlib
import struct

MAGIC = b"ANDROID!"
PAGE_SIZE = 2048
KERNEL_ADDR = 0x10008000
RAMDISK_ADDR = 0x11000000
SECOND_ADDR = 0x10F00000
TAGS_ADDR = 0x10000100
BOARD_NAME = b"internal"

CMDLINE_LEN = 512
EXTRA_CMDLINE_LEN = 1024
HEADER_LEN = 64 + CMDLINE_LEN + 32 + EXTRA_CMDLINE_LEN

__all__ = ["CMDLINE_LEN", "PAGE_SIZE", "BootImageError", "pack", "read_cmdline"]


class BootImageError(ValueError):
    """A boot image that cannot be built, or is not one."""


def _pad(data: bytes) -> bytes:
    """To the next page boundary: every section of the image starts on one."""
    remainder = len(data) % PAGE_SIZE
    return data + (b"\0" * (PAGE_SIZE - remainder) if remainder else b"")


def _image_id(kernel: bytes, ramdisk: bytes) -> bytes:
    """mkbootimg's `id`: SHA-1 over each section and its length, in order. Nothing is
    known to check it, which is exactly why it is computed rather than zeroed."""
    h = hashlib.sha1()  # noqa: S324 - the format specifies SHA-1; it is not a security claim
    for section in (kernel, ramdisk, b""):
        h.update(section)
        h.update(struct.pack("<I", len(section)))
    return h.digest().ljust(32, b"\0")


def pack(kernel: bytes, ramdisk: bytes, cmdline: str) -> bytes:
    """A version 0 boot image UEFI will boot, carrying `cmdline`.

    The command line has a fixed 512-byte field, and the 1024-byte extra field is not
    read on this path, so one that does not fit is refused here rather than silently
    truncated into a kernel that boots the wrong root.
    """
    if not kernel:
        raise BootImageError("the boot blob carries no kernel")
    if not ramdisk:
        raise BootImageError("the boot blob carries no initramfs")
    encoded = cmdline.encode()
    if len(encoded) >= CMDLINE_LEN:
        raise BootImageError(
            f"the kernel command line is {len(encoded)} bytes and the boot image holds "
            f"{CMDLINE_LEN - 1}; a truncated one would boot the wrong root"
        )
    header = struct.pack(
        "<8s10I16s512s32s1024s",
        MAGIC,
        len(kernel),
        KERNEL_ADDR,
        len(ramdisk),
        RAMDISK_ADDR,
        0,  # second stage: none
        SECOND_ADDR,
        TAGS_ADDR,
        PAGE_SIZE,
        0,  # header version
        0,  # os version
        BOARD_NAME,
        encoded,
        _image_id(kernel, ramdisk),
        b"",
    )
    assert len(header) == HEADER_LEN, len(header)
    return _pad(header) + _pad(kernel) + _pad(ramdisk)


def read_cmdline(image: bytes) -> str:
    """The command line of an existing boot image: what the slot would boot with."""
    if image[: len(MAGIC)] != MAGIC:
        raise BootImageError("not an Android boot image")
    return image[64 : 64 + CMDLINE_LEN].split(b"\0", 1)[0].decode("utf-8", "replace")
