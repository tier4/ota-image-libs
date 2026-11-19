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
(`apply`). The base declares nothing: a slot is a directory the base ships, and its
contents there are what the slot holds when no set fills it. The checks of the slots,
on their own and against a tree, are here; the config that carries them is in
schema.py. Specification: spec/parameter_set.md.
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

    `apply` is an executable of the running base, outside every slot, that the
    consumer runs once the slot's new contents are in place, and again once they are
    taken away; or `reboot`. It restarts what reads the slot and changes no file.
    """

    apply: str

    @model_validator(mode="after")
    def _apply_well_formed(self) -> Self:
        if self.apply != APPLY_REBOOT:
            check_absolute_path(f"slot {self.name!r} apply", self.apply)
        return self


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
    and no `apply` inside a slot, where a set would replace it: what runs as the
    consumer is the base's, and it is there to run again when the set is gone."""
    _slots = list(slots)
    check_slots_disjoint(what, _slots)
    _check_not_reserved(what, _slots, RESERVED_PATHS)
    for _slot in _slots:
        for _other in _slots:
            if _slot.apply != APPLY_REBOOT and _overlaps(_slot.apply, _other.path):
                raise ValueError(
                    f"{what}: slot {_slot.name!r}'s apply {_slot.apply} is in slot "
                    f"{_other.name!r} ({_other.path}), which a set replaces"
                )


def check_slots_in_tree(
    root: Path | str,
    slots: Iterable[ParameterSlot],
    *,
    reserved: Iterable[str] = (),
) -> None:
    """The base at `root` (a deployed tree, or `/` on the device) has what the slots
    need: each slot's directory, and each `apply` as an executable regular file.

    Both are taken at their real paths: a symbolic link on the way could lead out of
    the tree, or put the `apply` inside a slot after all. `reserved` names what the
    consumer reads for itself besides RESERVED_PATHS (absolute paths): a slot over one
    of them is refused too. Raises ValueError.
    """
    _slots = list(slots)
    _reserved = list(reserved)
    for _path in _reserved:
        check_absolute_path("reserved path", _path)
    _check_not_reserved("the consumer", _slots, _reserved)
    _root = os.path.realpath(root)
    for _slot in _slots:
        _dir = os.path.join(_root, _slot.relpath)
        if os.path.realpath(_dir) != _dir:
            raise ValueError(
                f"slot {_slot.name!r}: {_slot.path} is behind a symbolic link"
            )
        if not os.path.isdir(_dir):
            raise ValueError(
                f"slot {_slot.name!r}: the base has no directory {_slot.path}"
            )
        if _slot.apply == APPLY_REBOOT:
            continue
        _apply = os.path.join(_root, _slot.apply[1:])
        if os.path.realpath(_apply) != _apply:
            raise ValueError(
                f"slot {_slot.name!r}: apply {_slot.apply} is behind a symbolic link"
            )
        try:
            _st = os.stat(_apply)
        except OSError as e:
            # also a component of the way that is a file (ENOTDIR)
            raise ValueError(
                f"slot {_slot.name!r}: the base has no apply {_slot.apply}: "
                f"{e.strerror}"
            ) from e
        if not stat.S_ISREG(_st.st_mode) or not _st.st_mode & 0o111:
            raise ValueError(
                f"slot {_slot.name!r}: apply {_slot.apply} is not an executable file"
            )
