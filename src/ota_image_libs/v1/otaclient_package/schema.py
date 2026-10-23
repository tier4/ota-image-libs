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
"""Manifest of otaclient package."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ota_image_libs.common import (
    AliasEnabledModel,
    MediaType,
    MetaFileBase,
    MetaFileDescriptor,
    OCIDescriptor,
    SchemaVersion,
    Sha256Digest,
)
from ota_image_libs.common.model_spec import ArtifactType
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    OTACLIENT_APP_IMAGE,
    OTACLIENT_PACKAGE_ARTIFACT,
    OTACLIENT_PACKAGE_MANIFEST,
)

SQUASHFS = "squashfs"


class OTAClientOriginManifest(BaseModel):
    class _Payload(BaseModel):
        filename: str
        version: str
        type: str
        architecture: Literal["arm64", "x86_64"]
        size: int
        checksum: Sha256Digest

    # fmt: off
    class Descriptor(OCIDescriptor):
        """Points to the original otaclient release manifest.json."""

        MediaType = MediaType[OTACLIENT_PACKAGE_MANIFEST]
    # fmt: on

    schema_version: str = "1"
    date: str
    packages: list[_Payload]


class OTAClientPackageManifest(MetaFileBase):
    # fmt: off
    class Descriptor(MetaFileDescriptor["OTAClientPackageManifest"]):
        MediaType = MediaType[OTACLIENT_PACKAGE_MANIFEST]
        ArtifactType = ArtifactType[OTACLIENT_PACKAGE_ARTIFACT]

    class Annotations(AliasEnabledModel):
        date: str

    SchemaVersion = SchemaVersion[2]
    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[OTACLIENT_PACKAGE_ARTIFACT]

    config: OTAClientOriginManifest.Descriptor
    layers: list[OTAClientPayloadDescriptor]
    annotations: Annotations
    # fmt: on

    def find_package(
        self, version: str, architecture: Literal["arm64", "x86_64"]
    ) -> OTAClientPayloadDescriptor | None:
        for _descriptor in self.layers:
            _annotations = _descriptor.annotations
            if not _annotations:
                continue
            if (
                _annotations.version == version
                and _annotations.architecture == architecture
            ):
                return _descriptor


class OTAClientPayloadDescriptor(OCIDescriptor):
    class Annotations(AliasEnabledModel):
        """Mapping to packages element in manifest.json."""

        version: str
        type: str = SQUASHFS
        architecture: Literal["arm64", "x86_64"]
        size: int
        checksum: Sha256Digest

    MediaType = MediaType[OTACLIENT_APP_IMAGE]

    annotations: Annotations | None = None
