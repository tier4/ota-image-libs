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
"""Lay a parameter set over a deployed base tree, as a device would see it.

The result is the tree a vehicle runs with the set applied: each slot the set fills
holds the set's files and nothing of the base's, every other slot the base's defaults.
It is deterministic, so a tree made here can be evaluated or built into a full image,
and what was tested is told apart from what runs by the two manifests' digests.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ota_image_libs.common.oci_spec import Sha256Digest
from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier
from ota_image_libs.v1.parameter_set.layer import read_parameter_layer
from ota_image_libs.v1.parameter_set.schema import (
    ParameterSetConfig,
    check_against_base,
)
from ota_image_libs.v1.parameter_set.slots import ParameterSlot

logger = logging.getLogger(__name__)


class ParameterSetNotApplicable(Exception):
    """The parameter image has no set for this base, or one that does not fit it."""


def overlay_parameter_set(
    *,
    rootfs_dir: Path,
    parameter_image: Path,
    image_id: ImageIdentifier,
    base_manifest_digest: Sha256Digest,
    base_slots: list[ParameterSlot],
    tmp_dir: Path,
) -> ParameterSetConfig:
    """Replace the slots the set of `image_id` in `parameter_image` fills under
    `rootfs_dir`, a tree deployed from the base whose payload manifest has
    `base_manifest_digest` and which declares `base_slots`. Returns the set's config.

    Raises ParameterSetNotApplicable, or ParameterLayerInvalid for a broken layer.
    """
    with OTAImageArtifactReader(parameter_image) as _reader:
        if not _reader.is_valid_image():
            raise ParameterSetNotApplicable(f"{parameter_image} is not an OTA image")
        _manifest = _reader.select_parameter_set_payload(
            image_id, _reader.parse_index()
        )
        if _manifest is None:
            raise ParameterSetNotApplicable(
                f"{parameter_image} carries no parameter set for {image_id}"
            )
        try:
            _config = _reader.get_parameter_set_config(_manifest)
            _filled = check_against_base(
                _manifest,
                _config,
                base_manifest_digest=base_manifest_digest,
                base_slots=base_slots,
            )
        except ValueError as e:
            raise ParameterSetNotApplicable(str(e)) from e

        logger.info(f"parameter set {_config.name} {_config.version} for {image_id}")
        if (_layer := _manifest.layer) is None:
            logger.info("an empty set: every slot keeps the base's defaults")
            return _config

        _unpacked = tmp_dir / "parameter_set"
        _unpacked.mkdir()
        with _reader.open_blob(_layer.digest.digest_hex) as _blob:
            _info = read_parameter_layer(
                _blob,  # type: ignore[arg-type]
                _config.slots,
                extract_to=_unpacked,
                blob_digest=_layer.digest,
                diff_id=_config.diff_ids[0],
            )

    for _slot in _filled:
        _dst = rootfs_dir / _slot.relpath
        if _dst.is_symlink() or (_dst.exists() and not _dst.is_dir()):
            raise ParameterSetNotApplicable(
                f"slot {_slot.name!r}: {_dst} is not a directory"
            )
        if _dst.exists():
            shutil.rmtree(_dst)
        _dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(_unpacked / _slot.relpath), _dst)
        logger.info(f"slot {_slot.name!r} at {_slot.path} replaced")
    logger.info(
        f"{len(_info.files)} files ({_info.files_size} bytes) laid over the base"
    )
    return _config
