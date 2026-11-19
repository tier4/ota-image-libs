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
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier
from ota_image_libs.v1.parameter_set.layer import read_parameter_layer
from ota_image_libs.v1.parameter_set.schema import (
    ParameterSetConfig,
    ParameterSetManifest,
)
from ota_image_libs.v1.parameter_set.slots import check_slots_in_tree

logger = logging.getLogger(__name__)


class ParameterSetNotApplicable(Exception):
    """The parameter image has no set for this ECU, or one the base has no room for."""


class ParameterSetInvalid(Exception):
    """The parameter image, or the set in it, is not well formed.

    A broken layer raises ParameterLayerInvalid instead.
    """


def _read_set(
    reader: OTAImageArtifactReader, parameter_image: Path, image_id: ImageIdentifier
) -> tuple[ParameterSetManifest, ParameterSetConfig]:
    if not reader.is_valid_image():
        raise ParameterSetInvalid(f"{parameter_image} is not an OTA image")
    try:
        _manifest = reader.select_parameter_set_payload(image_id, reader.parse_index())
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        raise ParameterSetInvalid(f"{parameter_image}: {e}") from e
    if _manifest is None:
        raise ParameterSetNotApplicable(
            f"{parameter_image} carries no parameter set for {image_id}"
        )
    try:
        _config = reader.get_parameter_set_config(_manifest)
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        raise ParameterSetInvalid(f"{parameter_image}: {e}") from e
    return _manifest, _config


def open_parameter_set(
    parameter_image: Path, image_id: ImageIdentifier
) -> ParameterSetConfig:
    """Find the set of `image_id` in `parameter_image` and check it against its
    manifest, without a base: what can be told before deploying one. Returns the
    set's config.

    Raises ParameterSetInvalid, or ParameterSetNotApplicable when the image has no set
    for `image_id`.
    """
    try:
        with OTAImageArtifactReader(parameter_image) as _reader:
            return _read_set(_reader, parameter_image, image_id)[1]
    except (OSError, zipfile.BadZipFile) as e:
        raise ParameterSetInvalid(f"cannot open {parameter_image}: {e}") from e


def overlay_parameter_set(
    *,
    rootfs_dir: Path,
    parameter_image: Path,
    image_id: ImageIdentifier,
    tmp_dir: Path,
) -> ParameterSetConfig:
    """Replace the slots the set of `image_id` in `parameter_image` fills under
    `rootfs_dir`, a tree deployed from a base. Returns the set's config.

    As on a device, the base must have each slot's directory and each `apply`, and the
    whole layer is checked before the tree is changed.
    Raises ParameterSetInvalid, ParameterSetNotApplicable, or ParameterLayerInvalid
    for a broken layer.
    """
    try:
        _reader = OTAImageArtifactReader(parameter_image)
    except (OSError, zipfile.BadZipFile) as e:
        raise ParameterSetInvalid(f"cannot open {parameter_image}: {e}") from e
    with _reader:
        _manifest, _config = _read_set(_reader, parameter_image, image_id)
        try:
            check_slots_in_tree(rootfs_dir, _config.slots)
        except ValueError as e:
            raise ParameterSetNotApplicable(str(e)) from e

        logger.info(f"parameter set {_config.name} {_config.version} for {image_id}")
        if (_layer := _manifest.layer) is None:
            logger.info("an empty set: the base is left as it is")
            return _config

        _unpacked = tmp_dir / "parameter_set"
        _unpacked.mkdir()
        try:
            _blob = _reader.open_blob(_layer.digest.digest_hex)
        except FileNotFoundError as e:
            raise ParameterSetInvalid(f"{parameter_image}: {e}") from e
        with _blob:
            _info = read_parameter_layer(
                _blob,  # type: ignore[arg-type]
                _config.slots,
                extract_to=_unpacked,
                blob_digest=_layer.digest,
                diff_id=_config.diff_ids[0],
            )
        try:
            _config.check_files(_info.files)
        except ValueError as e:
            raise ParameterSetInvalid(str(e)) from e

    _replace_slots(rootfs_dir, _unpacked, _config)
    logger.info(
        f"{len(_info.files)} files ({_info.files_size} bytes) laid over the base"
    )
    return _config


def _replace_slots(
    rootfs_dir: Path, unpacked: Path, config: ParameterSetConfig
) -> None:
    # Each slot's new contents are moved next to the slot first, which copies them
    #   when the unpacked tree is on another filesystem, and only then swapped in by
    #   renames: the tree is not left with a slot gone when a copy fails.
    _staged: list[tuple[Path, Path]] = []
    try:
        for _slot in config.slots:
            # checked above: a real directory of the tree, not behind a link
            _dst = rootfs_dir / _slot.relpath
            _stage = Path(tempfile.mkdtemp(prefix=f".{_dst.name}.", dir=_dst.parent))
            _staged.append((_dst, _stage))
            shutil.move(str(unpacked / _slot.relpath), _stage / "new")
    except BaseException:
        for _, _stage in _staged:
            shutil.rmtree(_stage, ignore_errors=True)
        raise

    for (_dst, _stage), _slot in zip(_staged, config.slots, strict=True):
        os.rename(_dst, _stage / "old")
        os.rename(_stage / "new", _dst)
        shutil.rmtree(_stage)
        logger.info(f"slot {_slot.name!r} at {_slot.path} replaced")
