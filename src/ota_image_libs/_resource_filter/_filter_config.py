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
"""Serializable/Deserializable FileterConfig types for filter_applied column."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from typing_extensions import Self

from ota_image_libs.common.msgpack_utils import pack_obj, unpack_list

from ._common import FilterConfig, register_filter


@dataclass
class BundleFilter(FilterConfig):
    """Filter config for small resources bundle."""

    filter_type: ClassVar[Literal[b"b"]] = b"b"

    bundle_resource_id: int
    offset: int
    len: int

    def bytes_schema_serializer(self) -> bytes:
        return b":".join(
            [
                self.filter_type,
                pack_obj([self.bundle_resource_id, self.offset, self.len]),
            ],
        )

    @classmethod
    def from_raw_options(cls, _filter_options: bytes) -> Self:
        _bundle_id, _offset, _len = unpack_list(_filter_options, 3)
        return cls(bundle_resource_id=_bundle_id, offset=_offset, len=_len)

    def list_resource_id(self) -> int:
        return self.bundle_resource_id


register_filter(BundleFilter, BundleFilter.filter_type)


@dataclass
class CompressFilter(FilterConfig):
    """Filter config for compressed resources."""

    filter_type: ClassVar[Literal[b"c"]] = b"c"

    resource_id: int
    compression_alg: str

    def bytes_schema_serializer(self) -> bytes:
        return b":".join(
            [
                self.filter_type,
                pack_obj([self.resource_id, self.compression_alg]),
            ],
        )

    @classmethod
    def from_raw_options(cls, _filter_options: bytes) -> Self:
        _compressed_resource_id, _compression_alg = unpack_list(_filter_options, 2)
        return cls(
            resource_id=_compressed_resource_id, compression_alg=_compression_alg
        )

    def list_resource_id(self) -> int:
        return self.resource_id


register_filter(CompressFilter, CompressFilter.filter_type)


@dataclass
class SliceFilter(FilterConfig):
    """Filter config for sliced resources."""

    filter_type: ClassVar[Literal[b"s"]] = b"s"

    slices: list[int]

    def bytes_schema_serializer(self) -> bytes:
        return b":".join(
            [self.filter_type, pack_obj(self.slices)],
        )

    @classmethod
    def from_raw_options(cls, _filter_options: bytes) -> Self:
        slices = unpack_list(_filter_options)
        return cls(slices=slices)

    def list_resource_id(self) -> list[int]:
        return self.slices


register_filter(SliceFilter, SliceFilter.filter_type)
