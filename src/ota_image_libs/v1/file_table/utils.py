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

import os
import shutil
import stat
from pathlib import Path

from ota_image_libs.common.model_spec import MsgPackedDict, StrOrPath

from .db import DirTypedDict, NonRegularFileTypedDict, RegularFileTypedDict

CANONICAL_ROOT = "/"


def _set_xattr(path: StrOrPath, _in: MsgPackedDict) -> None:
    for k, v in _in.items():
        os.setxattr(path, k, v, follow_symlinks=False)


def fpath_on_target(_canonical_path: StrOrPath, target_mnt: StrOrPath) -> Path:
    """Return the fpath of self joined to <target_mnt>."""
    _canonical_path = Path(_canonical_path)
    _target_on_mnt = Path(target_mnt) / _canonical_path.relative_to(CANONICAL_ROOT)
    return _target_on_mnt


def prepare_dir(entry: DirTypedDict, *, target_mnt: StrOrPath) -> Path:
    _target_on_mnt = fpath_on_target(entry["path"], target_mnt=target_mnt)
    _target_on_mnt.mkdir(exist_ok=True, parents=True)
    os.chown(_target_on_mnt, uid=entry["uid"], gid=entry["gid"])
    os.chmod(_target_on_mnt, mode=entry["mode"])
    if xattrs := entry["xattrs"]:
        _set_xattr(_target_on_mnt, xattrs)
    return _target_on_mnt


def prepare_non_regular(
    entry: NonRegularFileTypedDict, *, target_mnt: StrOrPath
) -> Path:
    _target_on_mnt = fpath_on_target(entry["path"], target_mnt=target_mnt)
    if stat.S_ISLNK(entry["mode"]):
        _symlink_target_raw = entry["meta"]
        assert _symlink_target_raw, (
            f"{dict(entry)} is symlink, but no symlink target is defined"
        )

        _symlink_target = _symlink_target_raw.decode("utf-8")
        _target_on_mnt.symlink_to(_symlink_target)

        # NOTE(20241213): chown will reset the sticky bit of the file!!!
        #   Remember to always put chown before chmod !!!
        os.chown(
            _target_on_mnt,
            uid=entry["uid"],
            gid=entry["gid"],
            follow_symlinks=False,
        )
        # NOTE: changing mode of symlink is not needed and uneffective, and on some platform
        #   changing mode of symlink will even result in exception raised.
    elif stat.S_ISCHR(entry["mode"]):
        # NOTE: we only support placeholder char file with 0,0 devnode.
        os.mknod(_target_on_mnt, mode=entry["mode"] | stat.S_IFCHR, device=0)
        os.chown(
            _target_on_mnt,
            uid=entry["uid"],
            gid=entry["gid"],
            follow_symlinks=False,
        )
    else:
        return _target_on_mnt  # silently ignore unknown file type

    if xattrs := entry["xattrs"]:
        _set_xattr(_target_on_mnt, xattrs)
    return _target_on_mnt


def prepare_regular_copy(
    entry: RegularFileTypedDict, _rs: StrOrPath, *, target_mnt: StrOrPath
) -> Path:
    _target_on_mnt = fpath_on_target(entry["path"], target_mnt=target_mnt)
    shutil.copyfile(_rs, _target_on_mnt, follow_symlinks=False)
    os.chown(_target_on_mnt, uid=entry["uid"], gid=entry["gid"])
    os.chmod(_target_on_mnt, mode=entry["mode"])
    if _xattr := entry["xattrs"]:
        _set_xattr(_target_on_mnt, _in=_xattr)
    return _target_on_mnt


def prepare_regular_hardlink(
    entry: RegularFileTypedDict,
    _rs: StrOrPath,
    *,
    target_mnt: StrOrPath,
    hardlink_skip_apply_permission: bool = False,
) -> Path:
    # NOTE: os.link will make dst a hardlink to src.
    _target_on_mnt = fpath_on_target(entry["path"], target_mnt=target_mnt)
    os.link(_rs, _target_on_mnt)
    if not hardlink_skip_apply_permission:
        os.chown(_target_on_mnt, uid=entry["uid"], gid=entry["gid"])
        os.chmod(_target_on_mnt, mode=entry["mode"])
        if _xattr := entry["xattrs"]:
            _set_xattr(_target_on_mnt, _in=_xattr)
    return _target_on_mnt


def prepare_regular_move(
    entry: RegularFileTypedDict, _rs: StrOrPath, *, target_mnt: StrOrPath
) -> Path:
    _target_on_mnt = fpath_on_target(entry["path"], target_mnt=target_mnt)
    os.replace(str(_rs), _target_on_mnt)
    os.chown(_target_on_mnt, uid=entry["uid"], gid=entry["gid"])
    os.chmod(_target_on_mnt, mode=entry["mode"])
    if _xattr := entry["xattrs"]:
        _set_xattr(_target_on_mnt, _in=_xattr)
    return _target_on_mnt
