# Copyright 2025 TIER IV, INC. All rights reserved.
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
"""Test msgpack utilities."""

import pytest

from ota_image_libs.common.msgpack_utils import pack_obj, unpack_list


class TestMsgpackUtils:
    """Test msgpack utility functions."""

    def test_pack_list(self):
        """Test packing a list."""
        obj = [1, 2, 3, "test", {"nested": "dict"}]
        packed = pack_obj(obj)
        assert isinstance(packed, bytes)

    def test_pack_complex_nested_structure(self):
        """Test packing complex nested structures."""
        obj = {
            "list": [1, 2, 3],
            "dict": {"nested": {"deep": "value"}},
            "mixed": [{"key": "val"}, [1, 2], "string"],
        }
        packed = pack_obj(obj)
        assert isinstance(packed, bytes)
        assert len(packed) > 0

    def test_pack_oversized_object_raises_error(self):
        """Test that packing oversized object raises error."""
        # Create a very large object that exceeds FILTER_STRING_MAX_SIZE (1MiB)
        large_obj = {"data": "x" * (1024**2 + 1000)}  # More than 1MiB
        with pytest.raises(ValueError):
            pack_obj(large_obj)

    def test_unpack_list(self):
        """Test unpacking a list."""
        original_list = [1, 2, 3, "test"]
        packed = pack_obj(original_list)
        unpacked = unpack_list(packed)
        assert unpacked == original_list

    def test_unpack_list_wrong_length(self):
        """Test unpacking a list with wrong expected length."""
        original_list = [1, 2, 3]
        packed = pack_obj(original_list)
        with pytest.raises(ValueError):
            unpack_list(packed, expect_len=5)

    def test_unpack_non_list_raises_error(self):
        """Test that unpacking non-list raises error."""
        not_a_list = {"key": "value"}
        packed = pack_obj(not_a_list)
        with pytest.raises(ValueError):
            unpack_list(packed)
