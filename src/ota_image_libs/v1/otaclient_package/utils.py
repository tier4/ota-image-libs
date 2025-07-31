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
"""Utils to import otaclient package release into OTA image."""

from __future__ import annotations

from pathlib import Path

from .schema import (
    SQUASHFS,
    OTAClientOriginManifest,
    OTAClientPackageManifest,
    OTAClientPayloadDescriptor,
)

MANIFEST_JSON = "manifest.json"


def add_otaclient_package(
    release_dir: Path, resource_dir: Path
) -> OTAClientPackageManifest.Descriptor:
    _origin_manifest = OTAClientOriginManifest.model_validate_json(
        (release_dir / MANIFEST_JSON).read_text()
    )
    origin_manifest_descriptor = (
        OTAClientOriginManifest.Descriptor.add_file_to_resource_dir(
            release_dir / MANIFEST_JSON, resource_dir
        )
    )

    loaded_payload: list[OTAClientPayloadDescriptor] = []
    for _payload in _origin_manifest.packages:
        if _payload.type != SQUASHFS:
            continue
        _payload_descriptor = OTAClientPayloadDescriptor.add_file_to_resource_dir(
            release_dir / _payload.filename, resource_dir
        )
        _payload_descriptor.annotations = OTAClientPayloadDescriptor.Annotations(
            version=_payload.version,
            architecture=_payload.architecture,
            size=_payload.size,
            checksum=_payload.checksum,
        )
        loaded_payload.append(_payload_descriptor)

    manifest = OTAClientPackageManifest(
        config=origin_manifest_descriptor,
        layers=loaded_payload,
        annotations=OTAClientPackageManifest.Annotations(
            date=_origin_manifest.date,
        ),
    )

    return OTAClientPackageManifest.Descriptor.export_metafile_to_resource_dir(
        manifest, resource_dir
    )
