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
"""Parameter slots: the directories of the running base a parameter set replaces.

A parameter set names the slots it fills, each with how a change to it takes effect
(`apply`). The base declares nothing: a slot is a directory of the base, whose contents
there (none, when the base does not have it) are what the slot holds when no set fills
it. The checks of the slots, on their own, against the base and against the set's own
files, are here; the config that carries them is in schema.py. Specification:
spec/parameter_set.md.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import model_validator
from typing_extensions import Self

from ota_image_libs.common import AliasEnabledModel

SLOT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
APPLY_REBOOT = "reboot"
"""The `apply` that asks the consumer to reboot instead of running a command."""
WHITEOUT_PREFIX = ".wh."
"""What an OCI layer reads as a whiteout: no slot path has a component starting so."""


def is_within(path: str, directory: str) -> bool:
    """`path` is `directory` or below it; both normalized, absolute or both relative."""
    return path == directory or path.startswith(directory + "/")


def check_absolute_path(what: str, path: str) -> None:
    """An absolute, normalized POSIX path below `/`: what the consumer resolves on the
    running system, so nothing it would have to interpret."""
    if (
        not path.startswith("/")
        or path == "/"
        or posixpath.normpath(path) != path
        or path.startswith("//")
        or any(_c in path for _c in ("\0", "\n"))
    ):
        raise ValueError(
            f"{what} must be an absolute, normalized path below /: {path!r}"
        )


class ParameterSlotRef(AliasEnabledModel):
    """A slot's name and the directory it replaces: what the layer is written and
    read against."""

    name: str
    path: str

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not SLOT_NAME.fullmatch(self.name):
            raise ValueError(
                f"slot name {self.name!r}: 1 to 64 letters, digits, '_', '.' or '-', "
                "starting with a letter or digit"
            )
        check_absolute_path(f"slot {self.name!r} path", self.path)
        if any(_c.startswith(WHITEOUT_PREFIX) for _c in self.path.split("/")):
            raise ValueError(
                f"slot {self.name!r} path {self.path!r}: a component starting with "
                f"{WHITEOUT_PREFIX!r} would be read as a whiteout"
            )
        return self

    @property
    def relpath(self) -> str:
        """The path as a tar member or a tree relative to `/` names it."""
        return self.path[1:]


def slot_of(path: str, slots: Sequence[ParameterSlotRef]) -> ParameterSlotRef | None:
    """The slot a path relative to `/` belongs to: the slot's directory or below it."""
    for _s in slots:
        if is_within(path, _s.relpath):
            return _s
    return None


class ParameterSlot(ParameterSlotRef):
    """A slot as a parameter set fills it: also how a change to it takes effect.

    `apply` is the executable the consumer runs once the slot's new contents are in
    place: the file at that path then, the set's own when the path is inside a slot
    the set fills (see `apply_comes_with_set`), the base's otherwise; or `reboot`. It
    restarts what reads the slot and changes no file. Nothing runs when a slot is
    taken away: that takes effect when what reads it restarts.
    """

    apply: str

    @model_validator(mode="after")
    def _apply_well_formed(self) -> Self:
        if self.apply != APPLY_REBOOT:
            check_absolute_path(f"slot {self.name!r} apply", self.apply)
        return self


def apply_comes_with_set(
    slot: ParameterSlot, slots: Sequence[ParameterSlotRef]
) -> bool:
    """`slot`'s apply is inside one of `slots` (the slots of the set that names it):
    once the set is in place, what runs is a file of the set, not of the base."""
    return slot.apply != APPLY_REBOOT and slot_of(slot.apply[1:], slots) is not None


def check_slots_disjoint(what: str, slots: Iterable[ParameterSlotRef]) -> None:
    """Names unique, and no slot's directory inside another's: a file belongs to one
    slot, so that replacing a slot replaces exactly its own files."""
    _slots = list(slots)
    _names = [_s.name for _s in _slots]
    if len(set(_names)) != len(_names):
        raise ValueError(f"{what}: slot names must be unique: {_names}")
    for _a in _slots:
        for _b in _slots:
            if _a is not _b and is_within(_b.path, _a.path):
                raise ValueError(
                    f"{what}: slot {_b.name!r} ({_b.path}) is inside or the same as "
                    f"slot {_a.name!r} ({_a.path})"
                )


RESERVED_PATHS = ("/boot", "/etc/fstab", "/opt/ota", "/usr/share/ota")
"""What every consumer reads for itself, never a slot's: the boot files, the fstab that
mounts the slots, the consumer's store and trust anchors, and the image's version file.
A consumer passes what else it reads for itself to `check_slots_in_tree`."""


def _overlaps(a: str, b: str) -> bool:
    return is_within(a, b) or is_within(b, a)


def _check_not_reserved(
    what: str, slots: Iterable[ParameterSlotRef], reserved: Iterable[str]
) -> None:
    _reserved = list(reserved)
    for _slot in slots:
        for _path in _reserved:
            if _overlaps(_slot.path, _path):
                raise ValueError(
                    f"{what}: slot {_slot.name!r} ({_slot.path}) overlaps {_path}, "
                    "which a consumer reads for itself"
                )


def check_slots(what: str, slots: Iterable[ParameterSlot]) -> None:
    """The slots a set fills: disjoint, none over what the consumer reads for itself,
    and no `apply` that is a slot's directory. An `apply` may be inside a slot: the
    set then carries it."""
    _slots = list(slots)
    check_slots_disjoint(what, _slots)
    _check_not_reserved(what, _slots, RESERVED_PATHS)
    for _slot in _slots:
        if _slot.apply != APPLY_REBOOT and _slot.apply in {_s.path for _s in _slots}:
            raise ValueError(
                f"{what}: slot {_slot.name!r}'s apply {_slot.apply} is a slot's "
                "directory, not a file"
            )


def _check_apply(slot: ParameterSlot, where: str, root: str) -> None:
    """`slot`'s apply is an executable regular file of `where` (the base, or the set),
    whose tree is at `root` (a real path), at its real path: a symbolic link on the
    way could lead out of the tree, or into a slot."""
    _file = os.path.join(root, slot.apply[1:])
    if os.path.realpath(_file) != _file:
        raise ValueError(
            f"slot {slot.name!r}: apply {slot.apply} is behind a symbolic link in "
            f"{where}"
        )
    try:
        _st = os.stat(_file)
    except OSError as e:
        # also a component of the way that is a file (ENOTDIR)
        raise ValueError(
            f"slot {slot.name!r}: {where} has no apply {slot.apply}: {e.strerror}"
        ) from e
    if not stat.S_ISREG(_st.st_mode) or not _st.st_mode & 0o111:
        raise ValueError(
            f"slot {slot.name!r}: apply {slot.apply} is not an executable file of "
            f"{where}"
        )


MOUNT_POINT_MODE = 0o755
"""The mode of a slot directory the consumer makes as a mount point, and of each
missing parent it makes on the way: root's, readable and searchable by all."""


def _existing_ancestor(root: str, path: str) -> str:
    """The deepest of `path` and its ancestors up to `root` (a directory, real path)
    that exists; ValueError when one cannot be looked at (other than not being
    there)."""
    _at = path
    while _at != root:
        try:
            os.lstat(_at)
            return _at
        except (FileNotFoundError, NotADirectoryError):
            _at = os.path.dirname(_at)
        except OSError as e:
            raise ValueError(f"cannot look at {_at}: {e.strerror}") from e
    return root


def check_slots_in_tree(
    root: Path | str,
    slots: Iterable[ParameterSlot],
    *,
    reserved: Iterable[str] = (),
) -> None:
    """The base at `root` (a deployed tree, or `/` on the device) has room for the
    slots, and each `apply` that is the base's is there as an executable regular file.

    A slot's directory the base does not have is fine (the consumer makes it as the
    mount point); one it has is a directory, and the way to it is through directories
    only. An `apply` inside one of `slots` comes with the set and is not looked for
    here: `check_applies_in_set` checks it against the set's files. Both are taken at
    their real paths: a symbolic link on the way could lead out of the tree, or put the
    `apply` inside a slot after all. `reserved` names what the consumer reads for
    itself besides RESERVED_PATHS (absolute paths): a slot over one of them is refused
    too. Raises ValueError.
    """
    _slots = list(slots)
    _reserved = list(reserved)
    for _path in _reserved:
        check_absolute_path("reserved path", _path)
    _check_not_reserved("the consumer", _slots, _reserved)
    _root = os.path.realpath(root)
    if not os.path.isdir(_root):
        raise ValueError(f"the base {root} is not a directory")
    for _slot in _slots:
        _dir = os.path.join(_root, _slot.relpath)
        # also a link to a missing target: realpath follows it
        if os.path.realpath(_dir) != _dir:
            raise ValueError(
                f"slot {_slot.name!r}: {_slot.path} is behind a symbolic link in the "
                "base"
            )
        _existing = _existing_ancestor(_root, _dir)
        if not os.path.isdir(_existing):
            if _existing == _dir:
                raise ValueError(
                    f"slot {_slot.name!r}: {_slot.path} is not a directory in the base"
                )
            raise ValueError(
                f"slot {_slot.name!r}: {_slot.path} is behind a file in the base "
                f"(/{os.path.relpath(_existing, _root)})"
            )
        if _slot.apply == APPLY_REBOOT or apply_comes_with_set(_slot, _slots):
            continue
        _check_apply(_slot, "the base", _root)


def check_applies_in_set(set_root: Path | str, slots: Iterable[ParameterSlot]) -> None:
    """Each `apply` inside one of `slots` is an executable regular file of the set,
    whose files are at `set_root` at their paths relative to `/` (the unpacked layer,
    or the tree a set is made from), and others cannot write it: neither the file
    nor a directory from its slot's directory down to it. The consumer runs it as
    root. (The group is root's once a consumer lays the set, so its write bit is
    not looked at.) Raises ValueError."""
    _slots = list(slots)
    _root = os.path.realpath(set_root)
    for _slot in _slots:
        if not apply_comes_with_set(_slot, _slots):
            continue
        _check_apply(_slot, "the set", _root)
        _in = slot_of(_slot.apply[1:], _slots)
        assert _in is not None
        _top = os.path.join(_root, _in.relpath)
        _at = os.path.join(_root, _slot.apply[1:])
        while True:
            if os.lstat(_at).st_mode & stat.S_IWOTH:
                raise ValueError(
                    f"slot {_slot.name!r}: others can write apply {_slot.apply} of "
                    f"the set (/{os.path.relpath(_at, _root)}), which runs as root"
                )
            if _at == _top:
                break
            _at = os.path.dirname(_at)
