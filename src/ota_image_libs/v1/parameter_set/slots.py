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
"""Parameter slots: the directories a base image lets a parameter set replace.

A base image declares them in its image config (`parameter_slots`); a parameter set
names the ones it fills. Kept apart from the parameter set schema so that the image
configs can import it without importing the manifests. Specification:
spec/parameter_set.md.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable

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
    """A slot as a parameter set names it: its name and the directory it replaces."""

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
    """A slot as a base image declares it: also how a change to it takes effect.

    `apply` is an executable in the base image that the consumer runs once the slot's
    new contents are in place, or `reboot`. It restarts what reads the parameters and
    changes no file.
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
