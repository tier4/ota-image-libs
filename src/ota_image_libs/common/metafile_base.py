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
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Generic, Type, TypeVar, Union, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationInfo,
    computed_field,
    model_validator,
)
from typing_extensions import Self

from .model_fields import ConstFieldMeta, NotDefinedField
from .oci_spec import OCIDescriptor, Sha256Digest

MetaFile_T = TypeVar("MetaFile_T", bound="MetaFileBase")


class MetaFileDescriptor(OCIDescriptor, Generic[MetaFile_T]):
    """An OCIDescriptor that points to a OTA image metafile.

    The metafile is in either JSON or YAML format.
    """

    @classmethod
    @lru_cache
    def metafile_type(cls) -> type[MetaFile_T]:
        # NOTE: pydantic will create concrete subclass for parameterized subclass,
        #       so class that subclasses a parameterized model will lost the information
        #       of paramterize type args, we need to get the information from the parent.
        _parent = super(cls, cls)  # a bound super
        _parameterize_meta = _parent.__pydantic_generic_metadata__
        if not (_args := _parameterize_meta["args"]):
            raise TypeError(f"{cls.__name__} is not parameterized")
        if len(_args) != 1:
            raise TypeError(
                f"{cls.__name__} should only be parameterized with exact one type"
            )

        _wrapped_type = _args[0]
        if isinstance(_wrapped_type, str):  # forward reference
            # normally, we use forward reference when the Descriptor is defined
            #   within the MetaFile class creation namespace
            try:
                _module = sys.modules[cls.__module__]
                _resolved_type = _module.__dict__[_wrapped_type]
                return cast("type[MetaFile_T]", _resolved_type)
            except Exception as e:
                raise TypeError(
                    f"{cls.__name__}: Failed to resolve forward reference '{_wrapped_type}'"
                ) from e

        if not (
            isinstance(_wrapped_type, type) and issubclass(_wrapped_type, MetaFileBase)
        ):
            raise TypeError(
                f"{cls.__name__} should only be parameterized with MetaFileBase type"
            )
        return cast("type[MetaFile_T]", _wrapped_type)

    @classmethod
    def export_metafile_to_resource_dir(
        cls,
        meta_file: MetaFile_T,
        resource_dir: Path,
        *,
        annotations: dict[str, Any] | None = None,
    ) -> Self:
        """Save <meta_file> to <resource_dir> and return an OCIDescriptor."""
        _contents = meta_file.export_metafile().encode("utf-8")
        _digest = cls.supported_digest_impl(_contents).hexdigest()
        (resource_dir / _digest).write_bytes(_contents)
        return cls(
            size=len(_contents),
            digest=Sha256Digest(_digest),
            annotations=cls._validate_annotations(annotations) if annotations else None,
        )

    def load_metafile_from_resource_dir(self, resource_dir: Path) -> MetaFile_T:
        """Load the metafile from the resource directory."""
        _raw_content = self.get_blob_from_resource_dir(resource_dir).read_text(
            encoding="utf-8"
        )
        return self.metafile_type().parse_metafile(_raw_content)


class MetaFileBase(BaseModel):
    """Base class for a metadata file.

    NOTE: this class MUST not be directly used, it needs to be
          subclassed and assigned MediaType(and SchemaVersion, etc.).
    """

    model_config = ConfigDict(
        populate_by_name=True, ignored_types=(ConstFieldMeta, NotDefinedField)
    )

    Descriptor: ClassVar[Type[MetaFileDescriptor]]
    MediaType = NotDefinedField()
    SchemaVersion = NotDefinedField()

    @computed_field
    @property
    def schemaVersion(self) -> Union[int, None]:
        return self.SchemaVersion

    @computed_field
    @property
    def mediaType(self) -> str:
        if not self.MediaType:
            raise ValueError(f"{self.__class__.__name__} doesn't define `mediaType`!")
        return self.MediaType

    @model_validator(mode="before")
    @classmethod
    def _external_input_validator(cls, data: Any, info: ValidationInfo) -> Any:
        """Validate external input, like parsing meta files."""
        assert isinstance(data, dict)
        if info.mode == "json":
            if cls.SchemaVersion and cls.SchemaVersion != data.get("schemaVersion"):
                raise ValueError(
                    f"Expect schemaVersion {cls.SchemaVersion}, get {data.get('schemaVersion')}"
                )
            if cls.MediaType != data.get("mediaType"):
                raise ValueError(
                    f"Expect mediaType {cls.MediaType}, get {data.get('mediaType')}"
                )
        return data

    @classmethod
    def parse_metafile(cls, _input: str) -> Self:
        assert isinstance(cls.MediaType, str)
        _media_type = cls.MediaType
        if _media_type.endswith("+json"):
            return cls.model_validate_json(_input)
        if _media_type.endswith("+yaml"):
            _raw = yaml.safe_load(_input)
            return cls.model_validate(_raw)
        raise ValueError(
            f"{_media_type} indicates the input file is not a JSON or YAML file."
        )

    def export_metafile(self) -> str:
        _media_type = self.mediaType
        if _media_type.endswith("+json"):
            return self.model_dump_json(by_alias=True, exclude_none=True)
        if _media_type.endswith("+yaml"):
            _raw = self.model_dump(by_alias=True, exclude_none=True)
            return yaml.dump(_raw)
        raise ValueError(f"{_media_type} is not a JSON or YAML file.")
