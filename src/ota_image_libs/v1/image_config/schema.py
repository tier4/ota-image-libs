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

from typing import Union

from pydantic import Field

from ota_image_libs import DIGEST_ALGORITHM
from ota_image_libs.common.metafile_base import MetaFileBase, MetaFileDescriptor
from ota_image_libs.common.model_spec import AliasEnabledModel, MediaType, SchemaVersion
from ota_image_libs.v1.annotation_keys import (
    NVIDIA_JETSON_BSP_VER,
    OS,
    OS_VERSION,
    OTA_IMAGE_BLOBS_COUNT,
    OTA_IMAGE_BLOBS_SIZE,
    SYS_IMAGE_BASE_IMAGE,
    SYS_IMAGE_DIRS_COUNT,
    SYS_IMAGE_NON_REGULAR_FILES_COUNT,
    SYS_IMAGE_REGULAR_FILES_COUNT,
    SYS_IMAGE_SIZE,
    SYS_IMAGE_UNIQUE_FILES_COUNT,
    SYS_IMAGE_UNIQUE_FILES_SIZE,
)
from ota_image_libs.v1.file_table.schema import (
    FileTableDescriptor,
    ZstdCompressedFileTableDescriptor,
)
from ota_image_libs.v1.media_types import OTA_IMAGE_CONFIG_JSON

from .sys_config import SysConfig


class ImageConfig(MetaFileBase):
    class Descriptor(MetaFileDescriptor["ImageConfig"]):
        MediaType = MediaType[OTA_IMAGE_CONFIG_JSON]

    # fmt: off
    class Annotations(AliasEnabledModel):
        base_image: str = Field(alias=SYS_IMAGE_BASE_IMAGE)
        os: Union[str, None] = Field(alias=OS, default=None)
        os_version: Union[str, None] = Field(alias=OS_VERSION, default=None)
        nvidia_jetson_bsp_version: Union[str, None] = Field(alias=NVIDIA_JETSON_BSP_VER, default=None)

        image_blobs_count: int = Field(alias=OTA_IMAGE_BLOBS_COUNT)
        image_blobs_size: int = Field(alias=OTA_IMAGE_BLOBS_SIZE)

        sys_image_size: Union[int, None] = Field(alias=SYS_IMAGE_SIZE, default=None)
        sys_image_regular_files_count: int = Field(alias=SYS_IMAGE_REGULAR_FILES_COUNT)
        sys_image_non_regular_files_count: int = Field(alias=SYS_IMAGE_NON_REGULAR_FILES_COUNT)
        sys_image_dirs_count: int = Field(alias=SYS_IMAGE_DIRS_COUNT)
        sys_image_unique_file_entries: int = Field(alias=SYS_IMAGE_UNIQUE_FILES_COUNT)
        sys_image_unique_file_entries_size: int = Field(alias=SYS_IMAGE_UNIQUE_FILES_SIZE)
    # fmt: on

    SchemaVersion = SchemaVersion[1]
    MediaType = MediaType[OTA_IMAGE_CONFIG_JSON]

    resource_digest_alg: str = Field(init=False, default=DIGEST_ALGORITHM)
    description: Union[str, None] = None
    created: Union[str, None] = None
    architecture: str
    os: Union[str, None] = None
    os_version: Union[str, None] = Field(alias="os.version", default=None)
    sys_config: Union[SysConfig.Descriptor, None] = None
    file_table: Union[FileTableDescriptor, ZstdCompressedFileTableDescriptor]
    labels: Annotations

    @property
    def sys_image_size(self) -> int | None:
        return self.labels.sys_image_size

    @property
    def sys_image_regular_files_count(self) -> int:
        return self.labels.sys_image_regular_files_count

    @property
    def sys_image_dirs_count(self) -> int:
        return self.labels.sys_image_dirs_count

    @property
    def sys_image_non_regular_files_count(self) -> int:
        return self.labels.sys_image_non_regular_files_count

    @property
    def sys_image_unique_file_entries(self) -> int:
        return self.labels.sys_image_unique_file_entries

    @property
    def sys_image_unique_file_entries_size(self) -> int:
        return self.labels.sys_image_unique_file_entries_size
