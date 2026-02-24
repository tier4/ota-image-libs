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

import sys
from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Generic, TypeVar, Union
from weakref import WeakValueDictionary

from pydantic import BaseModel, ConfigDict, GetCoreSchemaHandler
from pydantic_core import CoreSchema, core_schema
from typing_extensions import Self, TypeVarTuple, Unpack

from .model_fields import ConstFieldWithAltMeta
from .msgpack_utils import pack_obj, unpack_dict

StrOrPath = Union[str, Path]
AnnotationsField = Dict[str, Union[str, int, float, bool]]
T = TypeVar("T")

_parameterized_const_field = WeakValueDictionary()

if sys.version_info >= (3, 10):
    from types import GenericAlias
else:
    if TYPE_CHECKING:

        class GenericAlias:
            def __init__(self, origin: type, *args: Any) -> None:
                self.origin = origin
                self.args = args
    else:
        from typing import List

        GenericAlias = type(List[int])


class PydanticFromBytesSchema:
    @classmethod
    @abstractmethod
    def bytes_schema_validator(cls, _in: bytes) -> Self:
        raise NotImplementedError

    @abstractmethod
    def bytes_schema_serializer(self) -> bytes:
        raise NotImplementedError

    @classmethod
    def _from_bytes_validator(cls, data: Any) -> Self:
        if isinstance(data, cls):
            return data
        if isinstance(data, bytes):
            return cls.bytes_schema_validator(data)
        raise ValueError(f"unexpected {type(data)=}")

    def _to_bytes_serializer(self) -> bytes:
        return self.bytes_schema_serializer()

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        _plain_validator = core_schema.no_info_plain_validator_function(
            cls._from_bytes_validator
        )
        _plain_serializer = core_schema.plain_serializer_function_ser_schema(
            cls._to_bytes_serializer
        )

        json_schema = core_schema.chain_schema(
            [
                core_schema.bytes_schema(),
                _plain_validator,
            ]
        )
        return core_schema.json_or_python_schema(
            json_schema=json_schema,
            python_schema=_plain_validator,
            serialization=_plain_serializer,
        )


class MsgPackedDict(Dict[str, bytes], PydanticFromBytesSchema):
    @classmethod
    def bytes_schema_validator(cls, _in: bytes) -> Self:
        try:
            _unpacked = unpack_dict(_in)
            if not all(isinstance(_elem, bytes) for _elem in _unpacked.values()):
                raise ValueError("not all elements are bytes object")
            return cls(_unpacked)
        except Exception as e:
            raise ValueError(f"failed to unpack: {e!r}") from e

    def bytes_schema_serializer(self) -> bytes:
        return pack_obj(self)


Ts = TypeVarTuple("Ts")


class _ConstField(Generic[Unpack[Ts]], metaclass=ConstFieldWithAltMeta):
    """Base class for defining field should have expected value,
        optionally with one or more aliases.

    When pydantic validates the input, this class will check if the input value
        matches at least one of the expected pre-defined value.
    When pydantic serializes the corresponding model, only the canonical value
        will be used.
    """

    expected: tuple[Unpack[Ts]]

    def __class_getitem__(cls, value: tuple[Any, ...] | Any):
        """Return a class with the expected schema version."""
        if not isinstance(value, tuple):
            value = (value,)

        # might be TypeVar, return an instance of GenericAlias
        for _v in value:
            if not isinstance(_v, (int, str)):
                return GenericAlias(cls, *value)

        _key = (cls.__name__, value)
        if _key in _parameterized_const_field:
            return _parameterized_const_field[_key]

        # parameterize new schema version type
        _new_type = type(f"{cls.__name__}[{value}]", (cls,), {"expected": value})
        _parameterized_const_field[_key] = _new_type
        return _new_type


class SchemaVersion(_ConstField[T]): ...


class MediaType(_ConstField[T]): ...


class MediaTypeWithAlt(_ConstField[Unpack[Ts]]): ...


class ArtifactType(_ConstField[T]): ...


class AliasEnabledModel(BaseModel):
    # NOTE: allow field to be validated by its original attr name.
    model_config = ConfigDict(populate_by_name=True)
