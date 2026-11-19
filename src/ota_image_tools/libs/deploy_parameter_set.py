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
holds the set's files and nothing of the base's, everything else is the base's.
It is deterministic, so a tree made here can be evaluated, the pair (base, set) being
what a release of the two is tested as.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier
from ota_image_libs.v1.parameter_set.layer import read_parameter_layer
from ota_image_libs.v1.parameter_set.schema import ParameterSetConfig
from ota_image_libs.v1.parameter_set.slots import check_slots_in_tree

logger = logging.getLogger(__name__)


class ParameterSetNotApplicable(Exception):
    """The parameter image has no set for this ECU, or one the base has no room for."""


def overlay_parameter_set(
    *,
    rootfs_dir: Path,
    parameter_image: Path,
    image_id: ImageIdentifier,
    tmp_dir: Path,
) -> ParameterSetConfig:
    """Replace the slots the set of `image_id` in `parameter_image` fills under
    `rootfs_dir`, a tree deployed from a base. Returns the set's config.

    As on a device, the base must have each slot's directory and each `apply`.
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
            check_slots_in_tree(rootfs_dir, _config.slots)
        except ValueError as e:
            raise ParameterSetNotApplicable(str(e)) from e

        logger.info(f"parameter set {_config.name} {_config.version} for {image_id}")
        if (_layer := _manifest.layer) is None:
            logger.info("an empty set: the base is left as it is")
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

    for _slot in _config.slots:
        # checked above: a real directory of the tree, not behind a link
        _dst = rootfs_dir / _slot.relpath
        shutil.rmtree(_dst)
        shutil.move(str(_unpacked / _slot.relpath), _dst)
        logger.info(f"slot {_slot.name!r} at {_slot.path} replaced")
    logger.info(
        f"{len(_info.files)} files ({_info.files_size} bytes) laid over the base"
    )
    return _config
