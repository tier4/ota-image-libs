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
"""Lay an overlay over a deployed base tree, as a device would see it.

The result is the tree a vehicle runs with the overlay applied: each slot the overlay
fills holds the overlay's files and nothing of the base's, everything else is the
base's. It is deterministic, so a tree made here can be evaluated, the pair (base,
overlay) being what a release of the two is tested as.
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
from ota_image_libs.v1.overlay.layer import read_overlay_layer
from ota_image_libs.v1.overlay.schema import (
    OverlayConfig,
    OverlayManifest,
)
from ota_image_libs.v1.overlay.slots import (
    MOUNT_POINT_MODE,
    check_applies_in_overlay,
    check_slots_in_tree,
)

logger = logging.getLogger(__name__)


class OverlayNotApplicable(Exception):
    """The overlay image has no overlay for this ECU, or one the base has no room
    for."""


class OverlayInvalid(Exception):
    """The overlay image, or the overlay in it, is not well formed.

    A broken layer raises OverlayLayerInvalid instead.
    """


def _read_overlay(
    reader: OTAImageArtifactReader, overlay_image: Path, image_id: ImageIdentifier
) -> tuple[OverlayManifest, OverlayConfig]:
    if not reader.is_valid_image():
        raise OverlayInvalid(f"{overlay_image} is not an OTA image")
    try:
        _manifest = reader.select_overlay_payload(image_id, reader.parse_index())
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        raise OverlayInvalid(f"{overlay_image}: {e}") from e
    if _manifest is None:
        raise OverlayNotApplicable(f"{overlay_image} carries no overlay for {image_id}")
    try:
        _config = reader.get_overlay_config(_manifest)
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        raise OverlayInvalid(f"{overlay_image}: {e}") from e
    return _manifest, _config


def open_overlay(overlay_image: Path, image_id: ImageIdentifier) -> OverlayConfig:
    """Find the overlay of `image_id` in `overlay_image` and check it against its
    manifest, without a base: what can be told before deploying one. Returns the
    overlay's config.

    Raises OverlayInvalid, or OverlayNotApplicable when the image has no overlay for
    `image_id`.
    """
    try:
        with OTAImageArtifactReader(overlay_image) as _reader:
            return _read_overlay(_reader, overlay_image, image_id)[1]
    except (OSError, zipfile.BadZipFile) as e:
        raise OverlayInvalid(f"cannot open {overlay_image}: {e}") from e


def lay_overlay(
    *,
    rootfs_dir: Path,
    overlay_image: Path,
    image_id: ImageIdentifier,
    tmp_dir: Path,
) -> OverlayConfig:
    """Replace the slots the overlay of `image_id` in `overlay_image` fills under
    `rootfs_dir`, a tree deployed from a base. Returns the overlay's config.

    As on a device, the base must have room for each slot (a directory it does not have
    is made) and each `apply` that is not the overlay's own, the overlay must carry the
    ones inside its slots, and the whole layer is checked before the tree is changed.
    Raises OverlayInvalid, OverlayNotApplicable, or OverlayLayerInvalid for a broken
    layer.
    """
    try:
        _reader = OTAImageArtifactReader(overlay_image)
    except (OSError, zipfile.BadZipFile) as e:
        raise OverlayInvalid(f"cannot open {overlay_image}: {e}") from e
    with _reader:
        _manifest, _config = _read_overlay(_reader, overlay_image, image_id)
        try:
            check_slots_in_tree(rootfs_dir, _config.slots)
        except ValueError as e:
            raise OverlayNotApplicable(str(e)) from e

        logger.info(f"overlay {_config.name} {_config.version} for {image_id}")
        if (_layer := _manifest.layer) is None:
            logger.info("an empty overlay: the base is left as it is")
            return _config

        _unpacked = tmp_dir / "overlay"
        _unpacked.mkdir()
        try:
            _blob = _reader.open_blob(_layer.digest.digest_hex)
        except FileNotFoundError as e:
            raise OverlayInvalid(f"{overlay_image}: {e}") from e
        with _blob:
            _info = read_overlay_layer(
                _blob,  # type: ignore[arg-type]
                _config.slots,
                extract_to=_unpacked,
                blob_digest=_layer.digest,
                diff_id=_config.diff_ids[0],
            )
        try:
            _config.check_files(_info.files)
            check_applies_in_overlay(_unpacked, _config.slots)
        except ValueError as e:
            raise OverlayInvalid(str(e)) from e

    _replace_slots(rootfs_dir, _unpacked, _config)
    logger.info(
        f"{len(_info.files)} files ({_info.files_size} bytes) laid over the base"
    )
    return _config


def _make_missing_dirs(rootfs_dir: Path, relpath: str) -> list[Path]:
    """Make the directories of `relpath` under `rootfs_dir` that are not there, each
    MOUNT_POINT_MODE whatever the umask, as a consumer makes a slot's mount point.
    Returns the ones made, the top first."""
    _made: list[Path] = []
    _at = rootfs_dir
    for _component in relpath.split("/"):
        _at = _at / _component
        # checked before: no link on the way, and what is there is a directory
        if not _at.is_dir():
            _at.mkdir()
            os.chmod(_at, MOUNT_POINT_MODE)
            _made.append(_at)
    return _made


def _replace_slots(rootfs_dir: Path, unpacked: Path, config: OverlayConfig) -> None:
    # Each slot's new contents are moved next to the slot first, which copies them
    #   when the unpacked tree is on another filesystem, and only then swapped in by
    #   renames: the tree is not left with a slot gone when a copy fails, nor with
    #   the directories made for it.
    _staged: list[tuple[Path, Path]] = []
    _made: list[Path] = []
    try:
        for _slot in config.slots:
            _dst = rootfs_dir / _slot.relpath
            _new = _make_missing_dirs(rootfs_dir, _slot.relpath)
            _made.extend(_new)
            if _new:
                logger.warning(
                    f"slot {_slot.name!r}: the base has no {_slot.path}, made as the "
                    "mount point"
                )
            _stage = Path(tempfile.mkdtemp(prefix=f".{_dst.name}.", dir=_dst.parent))
            _staged.append((_dst, _stage))
            shutil.move(str(unpacked / _slot.relpath), _stage / "new")
    except BaseException:
        for _, _stage in _staged:
            shutil.rmtree(_stage, ignore_errors=True)
        for _dir in reversed(_made):
            try:
                _dir.rmdir()
            except OSError:
                pass
        raise

    for (_dst, _stage), _slot in zip(_staged, config.slots, strict=True):
        os.rename(_dst, _stage / "old")
        os.rename(_stage / "new", _dst)
        shutil.rmtree(_stage)
        logger.info(f"slot {_slot.name!r} at {_slot.path} replaced")
