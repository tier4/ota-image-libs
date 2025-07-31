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

from abc import abstractmethod
from typing import Any, ClassVar

from typing_extensions import Self

from ota_image_libs.common.model_spec import PydanticFromBytesSchema

_filter_register: dict[bytes, type[FilterConfig]] = {}


def register_filter(_filter: type[FilterConfig], code_name: bytes):
    _filter_register[code_name] = _filter


def get_filter_type(_codename: bytes) -> type[FilterConfig]:
    return _filter_register[_codename]


class FilterConfig(PydanticFromBytesSchema):
    """The base schema for filter_applied field.

    Raw schema for filter_applied field:

    `<filter_type>:<filter_specific_options>`

    When validating, we will get one of the following concrete FilterOption subtype:
    1. InlineFilter: code_name `i`
    2. BundleFilter: code_name `b`
    3. CompressFilter: code_name `c`
    4. SliceFilter: code_name `s`

    When serializing, instance of FilterConfigBase subtype will be serialized into bytes.
    """

    filter_type: ClassVar[Any]

    @classmethod
    @abstractmethod
    def from_raw_options(cls, _filter_options: bytes) -> Any:
        """Create an instance from raw options."""
        raise NotImplementedError

    @classmethod
    def bytes_schema_validator(cls, _in: bytes) -> Self:
        _filter_type, _filter_options = pre_process_raw(_in)
        # NOTE: base FIlterConfig is used in model definition, so we need
        #       to use get_filter_type to narrow down to concrete filter impl.
        try:
            return get_filter_type(_filter_type).from_raw_options(_filter_options)
        except KeyError:
            raise ValueError(f"unknown filter type: {_filter_type}") from None

    @abstractmethod
    def list_resource_id(self) -> int | list[int]:
        """List all resources that build this resource."""
        raise NotImplementedError


def pre_process_raw(_in: bytes) -> tuple[bytes, bytes]:
    """Pre-process the raw filter config string.

    Returns:
        A tuple of (filter_type, raw_options).
    """
    _split: list[bytes] = _in.split(b":", maxsplit=1)
    if len(_split) != 2:
        raise ValueError(f"invalid filter config string: {_in}")
    return tuple(_split)  # type: ignore
