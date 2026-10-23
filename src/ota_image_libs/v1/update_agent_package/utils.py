# Copyright 2026 TIER IV, INC. All rights reserved.
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
"""Putting an update agent release package into an OTA image."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Tuple, Union

from ota_image_libs.v1.annotation_keys import (
    UPDATE_AGENT_ARCH,
    UPDATE_AGENT_TYPE,
    UPDATE_AGENT_VERSION,
)
from ota_image_libs.v1.update_agent_package.schema import (
    EMPTY_JSON,
    EmptyConfigDescriptor,
    UpdateAgentBundleDescriptor,
    UpdateAgentPackageManifest,
)


def add_update_agent_package(
    bundles: Iterable[Tuple[Path, str, str, Union[str, None]]],
    *,
    resource_dir: Path,
) -> UpdateAgentPackageManifest.Descriptor:
    """Add the manifest of one entry carrying every bundle given, with its blobs, and
    return its descriptor for the index.

    Each bundle is (file, type, version, architecture); at most one per type and
    architecture, and one without an architecture is the only one of its type.
    """
    _layers = []
    for _file, _type, _version, _arch in bundles:
        _annotations = {UPDATE_AGENT_TYPE: _type, UPDATE_AGENT_VERSION: _version}
        if _arch:
            _annotations[UPDATE_AGENT_ARCH] = _arch
        _layers.append(
            UpdateAgentBundleDescriptor.add_file_to_resource_dir(
                _file, resource_dir, annotations=_annotations
            )
        )
    if not _layers:
        raise ValueError("an update agent package with no bundles carries nothing")
    _manifest = UpdateAgentPackageManifest(
        config=EmptyConfigDescriptor.add_contents_to_resource_dir(
            EMPTY_JSON, resource_dir
        ),
        layers=_layers,
    )
    return UpdateAgentPackageManifest.Descriptor.export_metafile_to_resource_dir(
        _manifest, resource_dir
    )
