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
contents there are what the slot holds when no set fills it. Kept apart from the
parameter set schema so that the layer can import it without the manifests.
Specification: spec/parameter_set.md.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
from collections.abc import Iterable
from pathlib import Path

from pydantic import model_validator
from typing_extensions import Self

from ota_image_libs.common import AliasEnabledModel

SLOT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
APPLY_REBOOT = "reboot"
"""The `apply` that asks the consumer to reboot instead of running a command."""


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
        return self

    @property
    def relpath(self) -> str:
        """The path as a tar member or a tree relative to `/` names it."""
        return self.path[1:]


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
            if _a is not _b and (
                _a.path == _b.path or _b.path.startswith(_a.path + "/")
            ):
                raise ValueError(
                    f"{what}: slot {_b.name!r} ({_b.path}) is inside or the same as "
                    f"slot {_a.name!r} ({_a.path})"
                )


RESERVED_PATHS = ("/boot", "/etc/fstab", "/opt/ota", "/usr/share/ota")
"""What a consumer reads for itself, never a slot's: its boot files, the fstab that
mounts the slots, its own store and trust anchors, and the image's version file."""


def _overlaps(a: str, b: str) -> bool:
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def check_slots(what: str, slots: Iterable[ParameterSlot]) -> None:
    """The slots a set fills: disjoint, none over what the consumer reads for itself,
    and no `apply` inside a slot, where a set would replace it: what runs as the
    consumer is the base's, and it is there to run again when the set is gone."""
    _slots = list(slots)
    check_slots_disjoint(what, _slots)
    for _slot in _slots:
        for _reserved in RESERVED_PATHS:
            if _overlaps(_slot.path, _reserved):
                raise ValueError(
                    f"{what}: slot {_slot.name!r} ({_slot.path}) overlaps {_reserved}, "
                    "which a consumer reads for itself"
                )
        for _other in _slots:
            if _slot.apply != APPLY_REBOOT and _overlaps(_slot.apply, _other.path):
                raise ValueError(
                    f"{what}: slot {_slot.name!r}'s apply {_slot.apply} is in slot "
                    f"{_other.name!r} ({_other.path}), which a set replaces"
                )


def check_slots_in_tree(root: Path | str, slots: Iterable[ParameterSlot]) -> None:
    """The base at `root` (a deployed tree, or `/` on the device) has what the slots
    need: each slot's directory, and each `apply` as an executable regular file.

    Both are taken at their real paths: a symbolic link on the way could lead out of
    the tree, or put the `apply` inside a slot after all. Raises ValueError.
    """
    _root = os.path.realpath(root)
    for _slot in slots:
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
        except FileNotFoundError:
            raise ValueError(
                f"slot {_slot.name!r}: the base has no apply {_slot.apply}"
            ) from None
        if not stat.S_ISREG(_st.st_mode) or not _st.st_mode & 0o111:
            raise ValueError(
                f"slot {_slot.name!r}: apply {_slot.apply} is not an executable file"
            )
