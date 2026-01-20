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

import logging
import os
import shutil
from hashlib import sha256
from pathlib import Path
from typing import Any, Union

import zstandard
from pydantic import (
    BaseModel,
    ConfigDict,
    GetCoreSchemaHandler,
    computed_field,
    model_validator,
)
from pydantic_core import CoreSchema, core_schema
from typing_extensions import Self

from ._common import oci_descriptor_before_validator, tmp_fname
from .model_fields import ConstFieldWithAltMeta, NotDefinedField

logger = logging.getLogger(__name__)

HASH_READ_SIZE = 8 * 1024**2  # 8 MiB


class Sha256Digest:
    SHA256_ALG = "sha256"
    sha256_impl = staticmethod(sha256)

    def __init__(self, _digest: str | bytes):
        if isinstance(_digest, str):
            self._digest_hex = _digest
            self._digest_bytes = bytes.fromhex(_digest)
        else:
            self._digest_bytes = _digest
            self._digest_hex = _digest.hex()

    def __hash__(self) -> int:
        return int.from_bytes(self._digest_bytes, byteorder="big")

    def __eq__(self, value: object) -> bool:
        if not isinstance(value, self.__class__):
            return False
        return self.digest == value.digest

    @property
    def digest_hex(self) -> str:
        return self._digest_hex

    @property
    def digest(self) -> bytes:
        return self._digest_bytes

    @classmethod
    def _from_str_validator(cls, data: Any) -> Self:
        if isinstance(data, cls):
            return data
        if isinstance(data, str):
            _alg, _digest_hex = data.split(":", maxsplit=1)
            assert _alg == cls.SHA256_ALG, "Not a sha256 digest"
            return cls(_digest_hex)
        raise ValueError(f"invalid {type(data)=}")

    def _to_str_serializer(self) -> str:
        return f"{self.SHA256_ALG}:{self._digest_hex}"

    def __str__(self):
        return self._to_str_serializer()

    __repr__ = __str__

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> CoreSchema:
        _plain_validator = core_schema.no_info_plain_validator_function(
            cls._from_str_validator
        )
        _plain_serializer = core_schema.plain_serializer_function_ser_schema(
            cls._to_str_serializer
        )

        json_schema = core_schema.chain_schema(
            [
                core_schema.str_schema(),
                _plain_validator,
            ]
        )
        return core_schema.json_or_python_schema(
            json_schema=json_schema,
            python_schema=_plain_validator,
            serialization=_plain_serializer,
        )


class OCIDescriptor(BaseModel):
    """Compatible pydantic model for OCI Descriptor.

    See https://github.com/opencontainers/image-spec/blob/main/descriptor.md for more details.

    NOTE: this class MUST not be directly used, it needs to be
          subclassed and assigned MediaType(and ArtifactType, etc.).
    """

    model_config = ConfigDict(
        populate_by_name=True, ignored_types=(ConstFieldWithAltMeta, NotDefinedField)
    )

    supported_digest_impl = staticmethod(sha256)

    MediaType = NotDefinedField()
    ArtifactType = NotDefinedField()
    Annotations = NotDefinedField()

    size: int
    digest: Sha256Digest
    annotations: Any = None

    @computed_field
    @property
    def mediaType(self) -> str:
        if not self.MediaType:
            raise ValueError(f"{self.__class__.__name__} doesn't define `mediaType`!")
        return self.MediaType

    @computed_field
    @property
    def artifactType(self) -> Union[str, None]:
        return self.ArtifactType

    @model_validator(mode="before")
    @classmethod
    def _external_input_validator(cls, data, info) -> Any:
        return oci_descriptor_before_validator(cls, data, info)

    @classmethod
    def _validate_annotations(cls, annotations: dict[str, Any]):
        if isinstance(cls.Annotations, type) and issubclass(cls.Annotations, BaseModel):
            _validated_annotations = cls.Annotations.model_validate(annotations)
            return _validated_annotations
        raise TypeError(f"{cls.__name__} doesn't define annotations field.")

    @classmethod
    def add_contents_to_resource_dir(
        cls,
        contents: str | bytes,
        resource_dir: Path,
        *,
        annotations: dict[str, Any] | None = None,
    ) -> Self:
        """Add contents as blob to <resource_dir> and return an OCIDescriptor.

        This method should only be used for small files.
        """
        if not isinstance(contents, bytes):
            contents = contents.encode("utf-8")
        _digest = cls.supported_digest_impl(contents).hexdigest()
        (resource_dir / _digest).write_bytes(contents)

        return cls(
            size=len(contents),
            digest=Sha256Digest(_digest),
            annotations=cls._validate_annotations(annotations) if annotations else None,
        )

    @classmethod
    def add_file_to_resource_dir(
        cls,
        src: Path,
        resource_dir: Path,
        *,
        remove_origin: bool = False,
        annotations: dict[str, Any] | None = None,
        zstd_compression_level: int | zstandard.ZstdCompressor = 3,
    ) -> Self:
        """Add <fpath> as a blob into <resource_dir> and return an OCIDescriptor.

        This method supports transparently compressing file with zstd if the mediaType
            indicates the blob should be zstd compressed.

        Args:
            src (Path): The source file path to be added.
            resource_dir (Path): The directory where the blob will be stored.
            remove_origin (bool): If True, remove the original file after adding it to the resource directory.
            annotations (dict[str, Any] | None): Optional annotations to be added to the descriptor. Default is None.
            zstd_compression_level (int | zstandard.ZstdCompressor): If specified as int, use zstd compression with the given level.
                For advanced configuration, can be set as an instance of `zstandard.ZstdCompressor`. Default is 3.
        """
        _media_type: str = cls.MediaType
        if not _media_type:
            raise ValueError(f"{cls.__name__} doesn't have `mediaType` defined")

        _src_file_size = src.stat().st_size

        _tmp_fpath = resource_dir / tmp_fname()
        _write_bytes = 0
        try:
            _hasher = cls.supported_digest_impl()
            with open(src, "rb") as _src, open(_tmp_fpath, "wb") as _dst:
                if _media_type.endswith("+zstd"):
                    if isinstance(zstd_compression_level, int):
                        cctx = zstandard.ZstdCompressor(
                            level=zstd_compression_level,
                            write_checksum=True,
                            write_content_size=True,
                        )
                    else:
                        cctx = zstd_compression_level

                    for _chunk in cctx.read_to_iter(_src, size=_src_file_size):
                        _hasher.update(_chunk)
                        _write_bytes += _dst.write(_chunk)
                else:
                    while data := _src.read(HASH_READ_SIZE):
                        _hasher.update(data)
                        _write_bytes += _dst.write(data)
            _digest = _hasher.hexdigest()
            os.replace(_tmp_fpath, resource_dir / _digest)
        finally:
            _tmp_fpath.unlink(missing_ok=True)

        if _write_bytes != _src_file_size:
            logger.warning(f"{_write_bytes} != {_src_file_size}")

        if remove_origin:
            src.unlink(missing_ok=True)

        return cls(
            size=_write_bytes,
            digest=Sha256Digest(_digest),
            annotations=cls._validate_annotations(annotations) if annotations else None,
        )

    def get_blob_from_resource_dir(self, resource_dir: Path) -> Path:
        """Get the blob fpath from the resource directory.."""
        _blob_path = resource_dir / self.digest.digest_hex
        if not _blob_path.exists():
            raise FileNotFoundError(
                f"Blob with digest {self.digest.digest_hex} not found in OTA image."
            )
        return _blob_path

    def retrieve_blob_contents_from_resource_dir(self, resource_dir: Path) -> bytes:
        """Retrieve the contents of the blob from the resource directory.

        NOTE that this method directly read the whole file. For large file,
            please use `get_blob_from_resource_dir` instead.
        """
        _blob_path = self.get_blob_from_resource_dir(resource_dir)
        return _blob_path.read_bytes()

    def export_blob_from_resource_dir(
        self,
        resource_dir: Path,
        save_dst: Path,
        *,
        auto_decompress: bool = False,
    ) -> Path:
        """Save the blob to a specified path.

        Args:
            resource_dir (Path): The fpath to the blob storage of the image.
            save_dst (Path): where to save the blob to.
            auto_decompress (bool): For zstd compressed file, if specified,
                try to decompress the file when saving. Default is False.

        Returns:
            The fpath to the save location.
        """
        _blob_path = self.get_blob_from_resource_dir(resource_dir)
        if auto_decompress:
            if self.mediaType.endswith("+zstd"):
                dctx = zstandard.ZstdDecompressor()
                with open(_blob_path, "rb") as _src, open(save_dst, "wb") as _dst:
                    dctx.copy_stream(_src, _dst)
                return save_dst
            # silently do normal copy if the blob is not compressed.
        shutil.copyfile(_blob_path, save_dst)
        return save_dst

    def remove_blob_from_resource_dir(self, resource_dir: Path) -> Self:
        """Remove the pointed blob from the resource directory."""
        _blob_path = self.get_blob_from_resource_dir(resource_dir)
        _blob_path.unlink(missing_ok=True)
        return self
