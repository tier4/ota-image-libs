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

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, NamedTuple, Union

from pydantic import Field

from ota_image_libs.common import (
    AliasEnabledModel,
    MediaType,
    MetaFileBase,
    MetaFileDescriptor,
    SchemaVersion,
)
from ota_image_libs.common.model_spec import ArtifactType
from ota_image_libs.v1 import OTA_IMAGE_MEDIA_TYPE
from ota_image_libs.v1.annotation_keys import (
    OTA_RELEASE_KEY,
    PILOT_AUTO_PLATFORM,
    PLATFORM_ECU,
    PLATFORM_ECU_ARCH,
    PLATFORM_ECU_HARDWARE_MODEL,
    PLATFORM_ECU_HARDWARE_SERIES,
)
from ota_image_libs.v1.file_table.schema import (
    FileTableDescriptor,
    ZstdCompressedFileTableDescriptor,
)
from ota_image_libs.v1.image_config.schema import ImageConfig
from ota_image_libs.v1.media_types import IMAGE_MANIFEST, OTA_IMAGE_ARTIFACT


class ImageIdentifier(NamedTuple):
    ecu_id: str
    release_key: OTAReleaseKey


class OTAReleaseKey(str, Enum):
    """OTA release key for the image payload."""

    dev = "dev"
    prd = "prd"


class _ImageIDMixin:
    if TYPE_CHECKING:
        annotations: Any

    @property
    def ecu_id(self) -> str:
        return self.annotations.pilot_auto_platform_ecu

    @property
    def ota_release_key(self) -> OTAReleaseKey:
        return self.annotations.ota_release_key

    @property
    def image_identifier(self) -> ImageIdentifier:
        """Unique identifier to distinguish a manifest in index.json."""
        return ImageIdentifier(self.ecu_id, self.ota_release_key)


# fmt: off
class ImageManifest(_ImageIDMixin, MetaFileBase):
    class Descriptor(_ImageIDMixin, MetaFileDescriptor["ImageManifest"]):
        class Annotations(AliasEnabledModel):
            pilot_auto_platform_ecu: str = Field(alias=PLATFORM_ECU)
            ota_release_key: OTAReleaseKey = Field(alias=OTA_RELEASE_KEY, default=OTAReleaseKey.dev)

        MediaType = MediaType[IMAGE_MANIFEST]
        ArtifactType = ArtifactType[OTA_IMAGE_ARTIFACT]

        annotations: Union[Annotations, None] = None

        @classmethod
        def export_metafile_to_resource_dir(
            cls,
            meta_file: MetaFileBase,
            resource_dir: Path,
            *,
            annotations: dict[str, Any] | None = None,
        ):
            """For ImageManifest descriptor, `annotations` is required."""
            if annotations is None:
                raise ValueError(f"{cls.__name__} MUST have annotations assigned.")
            assert isinstance(meta_file, ImageManifest), f"`meta_file` MUST be instance of {ImageManifest.__name__}"

            return super().export_metafile_to_resource_dir(
                meta_file, resource_dir, annotations=annotations
            )

    class Annotations(AliasEnabledModel):
        pilot_auto_platform_ecu: str = Field(alias=PLATFORM_ECU)
        ota_release_key: OTAReleaseKey = Field(alias=OTA_RELEASE_KEY, default=OTAReleaseKey.dev)

        pilot_auto_platform: Union[str, None] = Field(alias=PILOT_AUTO_PLATFORM, default=None)
        pilot_auto_platform_ecu_hardware: str = Field(alias=PLATFORM_ECU_HARDWARE_MODEL)
        pilot_auto_platform_ecu_hardware_series: Union[str, None] = Field(alias=PLATFORM_ECU_HARDWARE_SERIES, default=None)
        pilot_auto_platform_ecu_arch: str = Field(alias=PLATFORM_ECU_ARCH)

    SchemaVersion= SchemaVersion[2]
    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[OTA_IMAGE_MEDIA_TYPE]

    config: ImageConfig.Descriptor
    layers: List[Union[FileTableDescriptor, ZstdCompressedFileTableDescriptor]]
    annotations: Annotations

    @property
    def image_file_table(self) -> Union[FileTableDescriptor, ZstdCompressedFileTableDescriptor]:
        return self.layers[0]
