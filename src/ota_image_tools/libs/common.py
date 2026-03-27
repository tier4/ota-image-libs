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
from ota_image_libs.v1.consts import RESOURCE_DIR
from ota_image_libs.v1.image_index.utils import ImageIndexHelper
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier, ImageManifest
from ota_image_tools._utils import exit_with_err_msg


def resolve_image_from_folder(
    image_root: Path, image_id: ImageIdentifier
) -> tuple[ImageManifest.Descriptor, Path]:
    """Resolve the image manifest descriptor from an OTA image folder.

    Returns:
        A tuple of (manifest_descriptor, resource_dir).
    """
    _index_helper = ImageIndexHelper(image_root)
    image_index = _index_helper.image_index

    _image_manifest_descriptor = image_index.find_image(image_id)
    if not _image_manifest_descriptor:
        exit_with_err_msg(f"failed to find image with {image_id=}")

    _resource_dir = image_root / RESOURCE_DIR
    return _image_manifest_descriptor, _resource_dir


def resolve_image_from_artifact(
    artifact_reader: OTAImageArtifactReader, image_id: ImageIdentifier
) -> ImageManifest:
    """Resolve the image manifest from an OTA image artifact.

    Returns:
        The parsed ImageManifest.
    """
    image_index = artifact_reader.parse_index()
    image_manifest = artifact_reader.select_image_payload(image_id, image_index)
    if not image_manifest:
        exit_with_err_msg(f"failed to find image with {image_id=}")

    return image_manifest
