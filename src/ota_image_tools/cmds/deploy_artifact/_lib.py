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

from pathlib import Path

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.file_table import FILE_TABLE_FNAME
from ota_image_libs.v1.file_table.db import FileTableDBHelper
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier
from ota_image_libs.v1.resource_table import RESOURCE_TABLE_FNAME
from ota_image_libs.v1.resource_table.db import ResourceTableDBHelper
from ota_image_tools._utils import exit_with_err_msg

IMAGE_MANIFEST_SAVE_FNAME = "image_manifest.json"
IMAGE_CONFIG_SAVE_FNAME = "image_config.json"
SYS_CONFIG_SAVE_FNAME = "sys_config.json"


class OTAImageDeployer:
    def __init__(
        self,
        _image_id: ImageIdentifier,
        *,
        artifact: Path,
        workdir: Path,
        rootfsdir: Path,
    ) -> None:
        self._image_id = _image_id
        self.artifact = artifact
        self.workdir = workdir
        self.rootfsdir = rootfsdir

        self._ft_db = workdir / FILE_TABLE_FNAME
        self._rst_db = workdir / RESOURCE_TABLE_FNAME

        # Prepare workdir with all neccessary metadata files extracted from the OTA image artifact
        with OTAImageArtifactReader(self.artifact) as artifact_reader:
            self.image_index = _image_index = artifact_reader.parse_index()

            rst_descriptor = _image_index.image_resource_table
            if not rst_descriptor:
                exit_with_err_msg("invalid OTA image: resource_table not found!")
            with artifact_reader.open_blob(
                rst_descriptor.digest.digest_hex
            ) as _blob_fp:
                rst_descriptor.export_blob_from_bytes_stream(
                    _blob_fp, self._rst_db, auto_decompress=True
                )
                self._rst_db_helper = ResourceTableDBHelper(self._rst_db)

            self.image_manifest = _image_manifest = (
                artifact_reader.select_image_payload(self._image_id, _image_index)
            )
            if not _image_manifest:
                exit_with_err_msg(
                    f"image payload specified by {self._image_id} not found!"
                )

            self.image_config, self.sys_config = artifact_reader.get_image_config(
                _image_manifest
            )

            ft_descriptor = _image_manifest.image_file_table
            with artifact_reader.open_blob(ft_descriptor.digest.digest_hex) as _blob_fp:
                ft_descriptor.export_blob_from_bytes_stream(
                    _blob_fp, self._ft_db, auto_decompress=True
                )
                self._ft_db_helper = FileTableDBHelper(self._ft_db)
