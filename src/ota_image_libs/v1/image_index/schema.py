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

import time
from typing import List, Union

from pydantic import Field

from ota_image_libs.common import (
    AliasEnabledModel,
    MediaType,
    MetaFileBase,
    MetaFileDescriptor,
    SchemaVersion,
)
from ota_image_libs.v1.annotation_keys import (
    BUILD_TOOL_VERSION,
    OTA_IMAGE_BLOBS_COUNT,
    OTA_IMAGE_BLOBS_SIZE,
    OTA_IMAGE_CREATED_AT,
    OTA_IMAGE_SIGNED_AT,
    PILOT_AUTO_PLATFORM,
    PILOT_AUTO_PROJECT_BRANCH,
    PILOT_AUTO_PROJECT_COMMIT,
    PILOT_AUTO_PROJECT_SOURCE,
    PILOT_AUTO_PROJECT_VERSION,
    WEB_AUTO_CATALOG,
    WEB_AUTO_CATALOG_ID,
    WEB_AUTO_ENV,
    WEB_AUTO_PROJECT,
    WEB_AUTO_PROJECT_ID,
)
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier, ImageManifest
from ota_image_libs.v1.media_types import IMAGE_INDEX
from ota_image_libs.v1.otaclient_package.schema import OTAClientPackageManifest
from ota_image_libs.v1.resource_table.schema import (
    ResourceTableDescriptor,
    ZstdCompressedResourceTableDescriptor,
)


class ImageIndex(MetaFileBase):
    class Descriptor(MetaFileDescriptor["ImageIndex"]):
        MediaType = MediaType[IMAGE_INDEX]

    class Annotations(AliasEnabledModel):
        # fmt: off
        build_tool_version: str = Field(alias=BUILD_TOOL_VERSION)

        created_at: Union[int, None] = Field(alias=OTA_IMAGE_CREATED_AT, default=None)
        signed_at: Union[int, None] = Field(alias=OTA_IMAGE_SIGNED_AT, default=None)

        # NOTE: will be calculated when the image is finalized
        total_blobs_count: int = Field(alias=OTA_IMAGE_BLOBS_COUNT, default=0)
        total_blobs_size: int = Field(alias=OTA_IMAGE_BLOBS_SIZE, default=0)

        pilot_auto_platform: Union[str, None] = Field(alias=PILOT_AUTO_PLATFORM, default=None)
        pilot_auto_source_repo: Union[str, None] = Field(alias=PILOT_AUTO_PROJECT_SOURCE, default=None)
        pilot_auto_version: Union[str, None] = Field(alias=PILOT_AUTO_PROJECT_VERSION, default=None)
        pilot_auto_release_commit: Union[str, None] = Field(alias=PILOT_AUTO_PROJECT_COMMIT, default=None)
        pilot_auto_release_branch: Union[str, None] = Field(alias=PILOT_AUTO_PROJECT_BRANCH, default=None)

        web_auto_project: Union[str, None] = Field(alias=WEB_AUTO_PROJECT, default=None)
        web_auto_project_id: Union[str, None] = Field(alias=WEB_AUTO_PROJECT_ID, default=None)
        web_auto_catalog: Union[str, None] = Field(alias=WEB_AUTO_CATALOG, default=None)
        web_auto_catalog_id: Union[str, None] = Field(alias=WEB_AUTO_CATALOG_ID, default=None)
        web_auto_env: Union[str, None] = Field(alias=WEB_AUTO_ENV, default=None)
        # fmt: on

    SchemaVersion = SchemaVersion[2]
    MediaType = MediaType[IMAGE_INDEX]

    manifests: List[
        Union[
            ImageManifest.Descriptor,
            OTAClientPackageManifest.Descriptor,
            ResourceTableDescriptor,
            ZstdCompressedResourceTableDescriptor,
        ]
    ]
    annotations: Annotations

    @property
    def image_finalized(self) -> bool:
        """Check if this OTA image is finalized.

        When the `created_at` annotation is set, it indicates that the image has been finalized.
        No futher changes to the OTA image(like adding more rootfs images) are permitted after this point.
        """
        return self.annotations.created_at is not None

    @property
    def image_signed(self) -> bool:
        """Check if this OTA image is signed.

        When the `signed_at` annotation is set, it indicates that the image has been signed.
        """
        return self.annotations.signed_at is not None

    @property
    def image_can_be_signed(self) -> bool:
        """Check if this OTA image can be signed.

        An image can be signed if it is finalized.
        """
        return self.image_finalized

    @property
    def image_resource_table(
        self,
    ) -> ResourceTableDescriptor | ZstdCompressedResourceTableDescriptor | None:
        """Return the resource_table descriptor of this OTA image."""
        for _manifest in self.manifests:
            if isinstance(
                _manifest,
                (ResourceTableDescriptor, ZstdCompressedResourceTableDescriptor),
            ):
                return _manifest

    @property
    def image_identifiers(self) -> list[ImageIdentifier]:
        """Return a list of all images identifiers.

        Image identifier is the combination of:
            ecu_id and ota_release_key.
        """
        return [
            _manifest.image_identifier
            for _manifest in self.manifests
            if isinstance(_manifest, ImageManifest.Descriptor)
        ]

    def find_image(self, _id: ImageIdentifier) -> ImageManifest.Descriptor | None:
        """Find one image from the manifests list."""
        for _entry in self.manifests:
            if (
                isinstance(_entry, ImageManifest.Descriptor)
                and _entry.image_identifier == _id
            ):
                return _entry

    def find_otaclient_package(self) -> list[OTAClientPackageManifest.Descriptor]:
        """Find all OTAClientPackage manifests from the manifests list."""
        return [
            _entry
            for _entry in self.manifests
            if isinstance(_entry, OTAClientPackageManifest.Descriptor)
        ]

    def finalize_image(self, total_blobs_count: int, total_blobs_size: int) -> None:
        """Label the OTA image as finalized by setting the `created_at` annotation.

        The caller(OTA image builder) SHOULD do optimization to the OTA image's blob storage,
            applying filters like bundle, compression and slicing to the blobs.
            After the optimization, the caller should provide the `total_blobs_count` and `total_blobs_size`
            to finalize the image with this method.
        """
        if self.image_finalized:
            raise ValueError("Image is already finalized.")

        self.annotations.created_at = int(time.time())
        self.annotations.total_blobs_count = total_blobs_count
        self.annotations.total_blobs_size = total_blobs_size

    def finalize_signing_image(self, force_sign: bool = False) -> None:
        """Finalize the signing of the OTA image by setting the `signed_at` annotation."""
        if not self.image_can_be_signed:
            raise ValueError(
                "Image cannot be signed. Ensure it is finalized and not already signed."
            )
        if self.image_signed and not force_sign:
            raise ValueError("Image is already signed. Use force_sign to override.")
        self.annotations.signed_at = int(time.time())

    def add_image(self, manifest_descriptor: ImageManifest.Descriptor) -> None:
        """Add a manifest of an image payload into the image index."""
        if self.image_finalized or self.image_signed:
            raise ValueError("Cannot add manifest to a finalized image.")

        _image_id = manifest_descriptor.image_identifier
        if self.find_image(_image_id) is not None:
            raise ValueError(
                f"image with {_image_id=} has already been added to the image, abort"
            )
        self.manifests.append(manifest_descriptor)

    def add_otaclient_package(
        self, manifest_descriptor: OTAClientPackageManifest.Descriptor
    ) -> None:
        """Add OTAClientPackage manifest into the image index."""
        self.manifests.append(manifest_descriptor)

    def update_resource_table(
        self,
        resource_table_descriptor: ResourceTableDescriptor
        | ZstdCompressedResourceTableDescriptor
        | None,
    ) -> ResourceTableDescriptor | ZstdCompressedResourceTableDescriptor | None:
        """Replace the old resource_table descriptor in the image_index.

        If no resource_table exists, the new one will be added.
        If no resource_table is provided, the existing one will be removed.

        This method is mainly for:
        1. Update the resource_table when adding multiple image payloads to the OTA image.
        2. Update the resource_table when finalizing the OTA image.

        Returns:
            The old resource_table descriptor if it exists, otherwise None.
        """
        _old, idx = None, -1
        for _count, _manifest in enumerate(self.manifests):
            if isinstance(
                _manifest,
                (ResourceTableDescriptor, ZstdCompressedResourceTableDescriptor),
            ):
                _old = _manifest
                idx = _count
                break

        if idx >= 0:
            self.manifests.pop(idx)
        if resource_table_descriptor is not None:
            self.manifests.append(resource_table_descriptor)
        return _old
