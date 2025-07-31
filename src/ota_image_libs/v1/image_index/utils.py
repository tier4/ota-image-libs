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
"""Utils for operating the index.json."""

from __future__ import annotations

from pathlib import Path

from ota_image_libs.common import Sha256Digest
from ota_image_libs.v1.consts import IMAGE_INDEX_FNAME, RESOURCE_DIR
from ota_image_libs.v1.image_index.schema import ImageIndex


class ImageIndexHelper:
    """Update image_index when we add new image into OTA image."""

    def __init__(self, image_root: Path) -> None:
        self._image_root = image_root
        self._image_index_f = image_root / IMAGE_INDEX_FNAME
        self._image_index = ImageIndex.parse_metafile(self._image_index_f.read_text())

    @property
    def image_index(self) -> ImageIndex:
        return self._image_index

    @property
    def image_index_json(self) -> str:
        return self._image_index.export_metafile()

    @property
    def image_index_fpath(self) -> Path:
        """Return the path to the image index.json."""
        return self._image_index_f

    @property
    def image_resource_dir(self) -> Path:
        """Return the path to the blob storage of the image."""
        return self._image_root / RESOURCE_DIR

    def sync_index(self) -> tuple[ImageIndex, ImageIndex.Descriptor]:
        """Write the updated image index back to the file."""
        _contents = self._image_index.export_metafile().encode("utf-8")
        _digest = ImageIndex.Descriptor.supported_digest_impl(_contents).digest()
        self._image_index_f.write_bytes(_contents)
        return self._image_index, ImageIndex.Descriptor(
            digest=Sha256Digest(_digest.hex()), size=len(_contents)
        )
