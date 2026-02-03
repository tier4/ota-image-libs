# Copyright 2022 TIER IV, INC. All rights reserved.
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

import os
import stat
from pathlib import Path
from shutil import copyfileobj
from typing import Any, Callable

from ota_image_libs.common import MsgPackedDict
from ota_image_libs.v1.file_table.db import DirRow, NonRegularFileRow, RegularFileRow

DEFAULT_PERMISSIONS = 0o100644


def _copyfile_slim(src: Path, dst: Path) -> None:  # pragma: no cover
    """A simple wrapper around shutil.copyfileobj."""
    with open(src, "rb") as _src, open(dst, "wb") as _dst:
        copyfileobj(_src, _dst)


class PrepareEntryFailed(Exception):  # pragma: no cover
    entry: Any
    """The entry that caused the failure."""

    def __init__(self, entry: Any, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry = entry

    def __str__(self) -> str:
        return f"failed to process {self.entry} due to: {self.__cause__}"


def _set_xattr(path: Path, _in: MsgPackedDict) -> None:  # pragma: no cover
    for k, v in _in.items():
        os.setxattr(path, k, v, follow_symlinks=False)


def fpath_on_target(
    _canonical_path: Path, target_mnt: Path, *, canonical_root="/"
) -> Path:  # pragma: no cover
    """Return the fpath of self joined to `target_mnt`."""
    _target_on_mnt = target_mnt / _canonical_path.relative_to(canonical_root)
    return _target_on_mnt


def prepare_dir(entry: DirRow, *, target_mnt: Path) -> None:
    _target_on_mnt = fpath_on_target(Path(entry.path), target_mnt=target_mnt)
    try:
        _target_on_mnt.mkdir(exist_ok=True, parents=True)
        os.chown(_target_on_mnt, uid=entry.uid, gid=entry.gid)
        os.chmod(_target_on_mnt, mode=entry.mode)
        if xattrs := entry.xattrs:
            _set_xattr(_target_on_mnt, xattrs)
    except Exception as e:
        raise PrepareEntryFailed(entry) from e


def prepare_non_regular(entry: NonRegularFileRow, *, target_mnt: Path) -> None:
    _target_on_mnt = fpath_on_target(Path(entry.path), target_mnt=target_mnt)
    try:
        if stat.S_ISLNK(entry.mode):
            _symlink_target_raw = entry.meta
            assert _symlink_target_raw, (
                f"{entry!r} is symlink, but no symlink target is defined"
            )

            _symlink_target = _symlink_target_raw.decode()
            _target_on_mnt.symlink_to(_symlink_target)

            # NOTE(20241213): chown will reset the sticky bit of the file!!!
            #   Remember to always put chown before chmod !!!
            os.chown(
                _target_on_mnt,
                uid=entry.uid,
                gid=entry.gid,
                follow_symlinks=False,
            )
            # NOTE: changing mode of symlink is not needed and uneffective, and on some platform
            #   changing mode of symlink will even result in exception raised.

        elif stat.S_ISCHR(entry.mode):
            # NOTE: we only support placeholder char file with 0,0 devnode.
            os.mknod(_target_on_mnt, mode=entry.mode | stat.S_IFCHR, device=0)
            os.chown(
                _target_on_mnt,
                uid=entry.uid,
                gid=entry.gid,
                follow_symlinks=False,
            )
        else:
            return  # silently ignore unknown file type

        if xattrs := entry.xattrs:
            _set_xattr(_target_on_mnt, xattrs)
    except Exception as e:
        raise PrepareEntryFailed(entry) from e


def prepare_regular_copy(
    entry: RegularFileRow,
    _rs: Path,
    *,
    target_mnt: Path,
    copyfile_util: Callable[[Path, Path], None] = _copyfile_slim,
) -> Path:
    _uid, _gid, _mode = entry.uid, entry.gid, entry.mode
    _target_on_mnt = fpath_on_target(Path(entry.path), target_mnt=target_mnt)
    try:
        _target_on_mnt.touch(exist_ok=True, mode=_mode)
        copyfile_util(_rs, _target_on_mnt)
        if not (_uid == 0 and _gid == 0):
            # NOTE: if owner is changed, the sticky bit will be reset.
            #       Remember to always put chown before chmod !!!
            os.chown(_target_on_mnt, uid=_uid, gid=_gid)
            os.chmod(_target_on_mnt, mode=_mode)

        if _xattr := entry.xattrs:
            _set_xattr(_target_on_mnt, _in=_xattr)
        return _target_on_mnt
    except Exception as e:
        _target_on_mnt.unlink(missing_ok=True)
        raise PrepareEntryFailed(entry) from e


def prepare_regular_inlined(entry: RegularFileRow, *, target_mnt: Path) -> Path:
    _contents = entry.contents
    _uid, _gid, _mode = entry.uid, entry.gid, entry.mode
    _target_on_mnt = fpath_on_target(Path(entry.path), target_mnt=target_mnt)
    try:
        assert _contents or entry.size == 0, "not an inlined entry!"

        _target_on_mnt.touch(exist_ok=True, mode=_mode)
        if _contents:
            _target_on_mnt.write_bytes(_contents)

        if not (_uid == 0 and _gid == 0):
            # NOTE: if owner is changed, the sticky bit will be reset.
            #       Remember to always put chown before chmod !!!
            os.chown(_target_on_mnt, uid=_uid, gid=_gid)
            os.chmod(_target_on_mnt, mode=_mode)

        if _xattr := entry.xattrs:
            _set_xattr(_target_on_mnt, _in=_xattr)
        return _target_on_mnt
    except Exception as e:
        _target_on_mnt.unlink(missing_ok=True)
        raise PrepareEntryFailed(entry) from e


def prepare_regular_hardlink(
    entry: RegularFileRow,
    _rs: Path,
    *,
    target_mnt: Path,
    hardlink_skip_apply_permission: bool = False,
) -> Path:
    _target_on_mnt = fpath_on_target(Path(entry.path), target_mnt=target_mnt)
    try:
        # NOTE: os.link will make dst a hardlink to src.
        os.link(_rs, _target_on_mnt)
        if not hardlink_skip_apply_permission:
            os.chown(_target_on_mnt, uid=entry.uid, gid=entry.gid)
            os.chmod(_target_on_mnt, mode=entry.mode)
            if _xattr := entry.xattrs:
                _set_xattr(_target_on_mnt, _in=_xattr)
        return _target_on_mnt
    except Exception as e:
        _target_on_mnt.unlink(missing_ok=True)
        raise PrepareEntryFailed(entry) from e
