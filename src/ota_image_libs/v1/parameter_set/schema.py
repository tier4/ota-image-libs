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
"""Schemas of the parameter set: the files of a base image's parameter slots, delivered
in an OTA image of their own and laid over the running base instead of written into a
standby slot.

One OCI layer (tar+zstd) of the slots' directories, bound to the one base payload it
was made for by the OCI 1.1 `subject`. Specification: spec/parameter_set.md.
"""

from __future__ import annotations

import posixpath
import re
from typing import Any

from pydantic import Field, ValidationInfo, computed_field, model_validator
from typing_extensions import Self

from ota_image_libs.common import (
    AliasEnabledModel,
    MediaType,
    MetaFileBase,
    MetaFileDescriptor,
    OCIDescriptor,
    SchemaVersion,
)
from ota_image_libs.common.model_spec import ArtifactType
from ota_image_libs.common.oci_spec import Sha256Digest
from ota_image_libs.v1.annotation_keys import (
    OTA_RELEASE_KEY,
    PARAMETER_SET_VERSION,
    PLATFORM_ECU,
)
from ota_image_libs.v1.image_manifest.schema import (
    ImageIDMixin,
    ImageManifest,
    OTAReleaseKey,
    PayloadManifestDescriptor,
)
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    OCI_LAYER_TAR_ZSTD,
    OTA_IMAGE_ARTIFACT,
    PARAMETER_SET_ARTIFACT,
    PARAMETER_SET_CONFIG_JSON,
    PARTITION_IMAGE_ARTIFACT,
)
from ota_image_libs.v1.update_agent_package.schema import EmptyConfigDescriptor

from .slots import SLOT_NAME, ParameterSlot, ParameterSlotRef, check_slots_disjoint

VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}")
"""A set's version: reported as it is, so nothing that would need escaping."""


def _require_artifact_type(cls: type, data: Any, info: ValidationInfo) -> Any:
    # A descriptor told apart from another of the same mediaType by its artifactType
    # carries one: without it, it would read as the file-based payload's.
    if info.mode == "json" and isinstance(data, dict) and "artifactType" not in data:
        raise ValueError(f"{cls.__name__} carries artifactType")
    return data


def slot_of(path: str, slots: list[ParameterSlotRef]) -> ParameterSlotRef | None:
    """The slot a path relative to `/` belongs to: the slot's directory or below it."""
    for _s in slots:
        if path == _s.relpath or path.startswith(_s.relpath + "/"):
            return _s
    return None


#
# ------ the layer ------ #
#


class ParameterLayerDescriptor(OCIDescriptor):
    """The set's files: one OCI layer, a zstd-compressed tar (see layer.py)."""

    MediaType = MediaType[OCI_LAYER_TAR_ZSTD]


EmptyDescriptor = EmptyConfigDescriptor
"""The OCI empty descriptor: the one layer of an empty set."""


#
# ------ the subject ------ #
#


class FileBasedSubjectDescriptor(OCIDescriptor):
    """The base payload a set was made for, a file-based one."""

    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[OTA_IMAGE_ARTIFACT]

    @model_validator(mode="before")
    @classmethod
    def _artifact_type_present(cls, data: Any, info: ValidationInfo) -> Any:
        return _require_artifact_type(cls, data, info)


class PartitionBasedSubjectDescriptor(OCIDescriptor):
    """The base payload a set was made for, a partition-based one."""

    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[PARTITION_IMAGE_ARTIFACT]

    @model_validator(mode="before")
    @classmethod
    def _artifact_type_present(cls, data: Any, info: ValidationInfo) -> Any:
        return _require_artifact_type(cls, data, info)


SubjectDescriptor = FileBasedSubjectDescriptor | PartitionBasedSubjectDescriptor


#
# ------ the config ------ #
#


class ParameterSetFileEntry(AliasEnabledModel):
    """One regular file of the set, as the layer carries it."""

    path: str
    """Relative to `/`, under one of the set's slots."""
    size: int = Field(ge=0)
    digest: Sha256Digest


class ParameterSetConfig(MetaFileBase):
    """What a parameter set is: its name and version, the slots it fills, and the
    uncompressed digest of its layer."""

    class Descriptor(MetaFileDescriptor["ParameterSetConfig"]):
        MediaType = MediaType[PARAMETER_SET_CONFIG_JSON]

    SchemaVersion = SchemaVersion[1]
    MediaType = MediaType[PARAMETER_SET_CONFIG_JSON]

    name: str
    version: str
    description: str | None = None
    created: str | None = None
    slots: list[ParameterSlotRef] = Field(default_factory=list)
    diff_ids: list[Sha256Digest] = Field(default_factory=list)
    files: list[ParameterSetFileEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not SLOT_NAME.fullmatch(self.name):
            raise ValueError(f"set name {self.name!r} is not a valid name")
        if not VERSION.fullmatch(self.version):
            raise ValueError(f"set version {self.version!r} is not a valid version")
        check_slots_disjoint("parameter set", self.slots)
        _layers = 1 if self.slots else 0
        if len(self.diff_ids) != _layers:
            raise ValueError(
                f"a set with {len(self.slots)} slot(s) has {_layers} diff_id(s), "
                f"not {len(self.diff_ids)}"
            )
        _seen: set[str] = set()
        for _f in self.files:
            if (
                posixpath.normpath(_f.path) != _f.path
                or _f.path.startswith("/")
                or slot_of(_f.path, self.slots) is None
            ):
                raise ValueError(
                    f"file {_f.path!r} is not under one of the set's slots"
                )
            if _f.path in _seen:
                raise ValueError(f"file {_f.path!r} is listed twice")
            _seen.add(_f.path)
        return self

    @property
    def is_empty(self) -> bool:
        """An empty set fills no slot: applied, every slot holds the base's defaults."""
        return not self.slots

    def slot(self, name: str) -> ParameterSlotRef | None:
        for _s in self.slots:
            if _s.name == name:
                return _s
        return None


#
# ------ the manifest ------ #
#


class ParameterSetManifest(ImageIDMixin, MetaFileBase):
    """The OCI image manifest of a parameter set: the payload of an ECU in a parameter
    image, told apart from a base payload by its artifactType."""

    # fmt: off
    class Descriptor(PayloadManifestDescriptor["ParameterSetManifest"]):
        class Annotations(ImageManifest.Descriptor.Annotations):
            parameter_set_version: str | None = Field(alias=PARAMETER_SET_VERSION, default=None)

        MediaType = MediaType[IMAGE_MANIFEST]
        ArtifactType = ArtifactType[PARAMETER_SET_ARTIFACT]

        annotations: Annotations = Field(...)

        @model_validator(mode="before")
        @classmethod
        def _artifact_type_present(cls, data: Any, info: ValidationInfo) -> Any:
            return _require_artifact_type(cls, data, info)

    class Annotations(AliasEnabledModel):
        pilot_auto_platform_ecu: str = Field(alias=PLATFORM_ECU)
        ota_release_key: OTAReleaseKey = Field(alias=OTA_RELEASE_KEY, default=OTAReleaseKey.dev)
        parameter_set_version: str = Field(alias=PARAMETER_SET_VERSION)
    # fmt: on

    SchemaVersion = SchemaVersion[2]
    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[PARAMETER_SET_ARTIFACT]

    config: ParameterSetConfig.Descriptor
    layers: list[ParameterLayerDescriptor | EmptyDescriptor]
    subject: SubjectDescriptor
    annotations: Annotations

    @computed_field
    @property
    def artifactType(self) -> str:
        return self.ArtifactType

    @model_validator(mode="after")
    def _one_layer(self) -> Self:
        if len(self.layers) != 1:
            raise ValueError(
                "a parameter set carries exactly one layer: its tar+zstd, or the empty "
                f"descriptor for an empty set; got {len(self.layers)}"
            )
        return self

    @property
    def layer(self) -> ParameterLayerDescriptor | None:
        """The set's layer, or None for an empty set."""
        _layer = self.layers[0]
        return _layer if isinstance(_layer, ParameterLayerDescriptor) else None

    @property
    def version(self) -> str:
        return self.annotations.parameter_set_version

    def check_config(self, config: ParameterSetConfig) -> None:
        """The config agrees with the manifest: the same version, and a layer exactly
        when the set fills a slot. Raises ValueError otherwise."""
        if config.version != self.version:
            raise ValueError(
                f"the config says version {config.version!r}, the manifest "
                f"{self.version!r}"
            )
        if config.is_empty != (self.layer is None):
            raise ValueError(
                "an empty set carries the empty descriptor and a set that fills a "
                "slot carries its layer"
            )


def check_against_base(
    manifest: ParameterSetManifest,
    config: ParameterSetConfig,
    *,
    base_manifest_digest: Sha256Digest,
    base_slots: list[ParameterSlot],
) -> list[ParameterSlot]:
    """The base's slots this set fills, once the set is known to be for this base.

    The set's `subject` names the base payload's manifest by digest: a set made for
    another base is refused, whatever its contents, since it was tested on that one.
    Each slot the set fills must be one the base declares, at the same path.
    Raises ValueError.
    """
    manifest.check_config(config)
    if manifest.subject.digest != base_manifest_digest:
        raise ValueError(
            f"the set is for base {manifest.subject.digest}, not {base_manifest_digest}"
        )
    _filled: list[ParameterSlot] = []
    for _slot in config.slots:
        _base = next((_b for _b in base_slots if _b.name == _slot.name), None)
        if _base is None:
            raise ValueError(f"the base declares no slot {_slot.name!r}")
        if _base.path != _slot.path:
            raise ValueError(
                f"slot {_slot.name!r} is {_base.path} in the base, not {_slot.path}"
            )
        _filled.append(_base)
    return _filled
