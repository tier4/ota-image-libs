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
"""The Android boot image the Jetson kernel partition holds."""

from __future__ import annotations

import struct

import pytest

from ota_image_tools.libs import bootimg


def test_pack_lays_out_header_kernel_and_ramdisk_on_page_boundaries():
    image = bootimg.pack(b"K" * 3000, b"R" * 100, "root=/dev/mapper/vroot ro")
    assert image[:8] == b"ANDROID!"
    kernel_size, _, ramdisk_size = struct.unpack_from("<3I", image, 8)
    assert (kernel_size, ramdisk_size) == (3000, 100)
    assert len(image) % bootimg.PAGE_SIZE == 0
    header_pages = -(-bootimg.HEADER_LEN // bootimg.PAGE_SIZE)
    assert image[header_pages * bootimg.PAGE_SIZE :].startswith(b"K" * 3000)
    assert bootimg.read_cmdline(image) == "root=/dev/mapper/vroot ro"


def test_two_packs_of_the_same_inputs_are_the_same_bytes():
    assert bootimg.pack(b"K", b"R", "a=b") == bootimg.pack(b"K", b"R", "a=b")


def test_a_command_line_that_does_not_fit_is_refused():
    with pytest.raises(bootimg.BootImageError, match="511"):
        bootimg.pack(b"K", b"R", "x" * bootimg.CMDLINE_LEN)


def test_an_empty_kernel_or_ramdisk_is_refused():
    with pytest.raises(bootimg.BootImageError, match="no kernel"):
        bootimg.pack(b"", b"R", "a=b")
    with pytest.raises(bootimg.BootImageError, match="no initramfs"):
        bootimg.pack(b"K", b"", "a=b")


def test_reading_the_command_line_of_something_else_is_refused():
    with pytest.raises(bootimg.BootImageError, match="not an Android boot image"):
        bootimg.read_cmdline(b"\0" * 4096)
