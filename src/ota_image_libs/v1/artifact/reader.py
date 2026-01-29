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
"""Read OTA image artifact without decompressing the artifact."""

from __future__ import annotations

from os import PathLike, path
from pathlib import Path
from typing import IO, Generator
from zipfile import ZIP_STORED, ZipFile

from ota_image_libs.v1.consts import (
    IMAGE_INDEX_FNAME,
    INDEX_JWT_FNAME,
    RESOURCE_DIR,
)
from ota_image_libs.v1.image_config.schema import ImageConfig
from ota_image_libs.v1.image_config.sys_config import SysConfig
from ota_image_libs.v1.image_index.schema import ImageIndex
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier, ImageManifest

DEFAULT_READ_SIZE = 8 * 1024**2


class OTAImageArtifactReader:
    """Helper class for reading the OTA image artifact file.

    This file is NOT safe for multi-thread, create separated instance
        for each worker thread if used in multi-threaded environment.
    """

    def __init__(
        self,
        _f: ZipFile | PathLike,
        *,
        read_chunk_size: int = DEFAULT_READ_SIZE,
        close_on_exit: bool = True,
    ) -> None:
        if isinstance(_f, ZipFile):
            self._f = _f
        else:
            self._f = ZipFile(_f, mode="r", compression=ZIP_STORED)

        self._close_on_exit = close_on_exit
        self._chunk_size = read_chunk_size
        self._resource_dir = RESOURCE_DIR

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._close_on_exit:
            self.close()
        return False

    def close(self) -> None:
        self._f.close()

    def is_valid_image(self) -> bool:
        """Check if this ZIP archive is an OTA image.

        NOTE that this method works by only checking the present of
            `index.json` file!
        """
        try:
            self._f.getinfo(IMAGE_INDEX_FNAME)
            return True
        except Exception:
            return False

    def parse_index(self) -> ImageIndex:
        with self._f.open(IMAGE_INDEX_FNAME) as _f:
            return ImageIndex.parse_metafile(_f.read().decode("utf-8"))

    def retrieve_jwt_raw(self) -> str | None:
        try:
            with self._f.open(INDEX_JWT_FNAME) as _f:
                return _f.read().decode("utf-8")
        except KeyError:
            return  # this image is not signed

    def open_blob(self, sha256_digest: str) -> IO[bytes]:
        """Open a blob in the blob storage of the archive."""
        try:
            return self._f.open(path.join(self._resource_dir, sha256_digest))
        except KeyError:
            raise FileNotFoundError(
                f"blob with {sha256_digest=} not found in the artifact!"
            ) from None

    def read_blob(self, sha256_digest: str) -> bytes:
        with self.open_blob(sha256_digest) as _blob_reader:
            return _blob_reader.read()

    def read_blob_as_text(self, sha256_digest: str) -> str:
        return self.read_blob(sha256_digest).decode("utf-8")

    def stream_blob(
        self, sha256_digest: str, *, read_size: int | None = None
    ) -> Generator[bytes]:
        read_size = self._chunk_size if read_size is None else read_size
        with self.open_blob(sha256_digest) as _blob_reader:
            while _chunk := _blob_reader.read(read_size):
                yield _chunk

    def select_image_payload(
        self, _image_id: ImageIdentifier, _image_index: ImageIndex
    ) -> ImageManifest | None:
        if _manifest_descriptor := _image_index.find_image(_image_id):
            return ImageManifest.parse_metafile(
                self.read_blob_as_text(_manifest_descriptor.digest.digest_hex)
            )

    def get_image_config(
        self, _image_manifest: ImageManifest
    ) -> tuple[ImageConfig, SysConfig | None]:
        _image_config = ImageConfig.parse_metafile(
            self.read_blob_as_text(_image_manifest.config.digest.digest_hex)
        )

        if _image_config.sys_config:
            _sys_config = SysConfig.parse_metafile(
                self.read_blob_as_text(_image_config.sys_config.digest.digest_hex)
            )
            return _image_config, _sys_config
        return _image_config, None

    def get_file_table(self, _image_config: ImageConfig, _save_dst: Path) -> Path:
        _ft_descriptor = _image_config.file_table
        with self.open_blob(_ft_descriptor.digest.digest_hex) as src:
            return _ft_descriptor.export_blob_from_bytes_stream(
                src, _save_dst, auto_decompress=True
            )

    def get_resource_table(self, _image_index: ImageIndex, _save_dst: Path) -> Path:
        if not (_descriptor := _image_index.image_resource_table):
            raise ValueError("invalid OTA image, resource_table not found!")
        with self.open_blob(_descriptor.digest.digest_hex) as src:
            return _descriptor.export_blob_from_bytes_stream(
                src, _save_dst, auto_decompress=True
            )
