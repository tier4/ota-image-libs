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

from __future__ import annotations

from typing import Any, cast

from msgpack import Unpacker, packb

FILTER_STRING_MAX_SIZE = 1024**2  # 1MiB

#
# ------ msgpack utils ------ #
#


def unpack_list(_in: bytes, expect_len: int | None = None) -> list[Any]:
    _unpacker = Unpacker(max_buffer_size=FILTER_STRING_MAX_SIZE)
    _unpacker.feed(_in)  # feed all the data into the internal buffer

    _options_list = _unpacker.unpack()
    if not isinstance(_options_list, list) or (
        expect_len and len(_options_list) != expect_len
    ):
        raise ValueError(f"invalid options for string: {_in}")
    return _options_list


def pack_obj(_in: Any) -> bytes:
    _res = cast(bytes, packb(_in))
    if len(_res) > FILTER_STRING_MAX_SIZE:
        raise ValueError(
            f"packed message bytes exceeds maximum len: {len(_res)=} > {FILTER_STRING_MAX_SIZE=}"
        )
    return _res


def unpack_dict(_in: bytes) -> dict[str, Any]:
    _unpacker = Unpacker(max_buffer_size=FILTER_STRING_MAX_SIZE)
    _unpacker.feed(_in)  # feed all the data into the internal buffer

    _options_dict = _unpacker.unpack()
    if not isinstance(_options_dict, dict):
        raise ValueError(f"invalid options for string: {_in}")
    return _options_dict
