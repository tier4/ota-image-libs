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
from typing import IO
from zipfile import ZIP_STORED, ZipFile

from ota_image_libs.v1.consts import IMAGE_INDEX_FNAME, RESOURCE_DIR
from ota_image_libs.v1.image_index.schema import ImageIndex


def open_artifact(_file: PathLike) -> OTAImageArtifact:
    return OTAImageArtifact(ZipFile(_file, mode="r", compression=ZIP_STORED))


class OTAImageArtifact:
    """Helper class for reading the OTA image artifact file.

    This file is NOT safe for multi-thread, create separated instance
        for each worker thread if used in multi-threaded environment.
    """

    def __init__(self, _f: ZipFile, *, read_chunk_size: int = 8 * 1024**2) -> None:
        self._f = _f
        self._chunk_size = read_chunk_size
        self._resource_dir = RESOURCE_DIR

        self._image_index = self._parse_index()

    def _parse_index(self) -> ImageIndex:
        with self._f.open(IMAGE_INDEX_FNAME) as _f:
            return ImageIndex.parse_metafile(_f.read().decode("utf-8"))

    def close(self) -> None:
        self._f.close()

    def get_blob(self, sha256_digest: str) -> IO[bytes]:
        """Open a blob in the blob storage of the archive."""
        return self._f.open(path.join(self._resource_dir, sha256_digest))
