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
"""Schemas of the parameter set: the files of a few directories of the rootfs (its
slots), delivered in an OTA image of their own and laid over the running base instead
of written into a standby slot.

One OCI layer (tar+zstd) of the slots' directories, for one ECU. The set names its
slots and how a change to each takes effect; it names no base: which base it suits is
decided where the release is evaluated. Specification: spec/parameter_set.md.
"""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
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
    require_artifact_type,
)
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    OCI_LAYER_TAR_ZSTD,
    PARAMETER_SET_ARTIFACT,
    PARAMETER_SET_CONFIG_JSON,
)
from ota_image_libs.v1.update_agent_package.schema import EmptyConfigDescriptor

from .slots import SLOT_NAME, ParameterSlot, check_slots, slot_of

VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}")
"""A set's version: reported as it is, so nothing that would need escaping."""


#
# ------ the layer ------ #
#


class ParameterLayerDescriptor(OCIDescriptor):
    """The set's files: one OCI layer, a zstd-compressed tar (see layer.py)."""

    MediaType = MediaType[OCI_LAYER_TAR_ZSTD]


EmptyDescriptor = EmptyConfigDescriptor
"""The OCI empty descriptor: the one layer of an empty set."""


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
    """What a parameter set is: its name and version, the slots it fills with how a
    change to each takes effect, and the uncompressed digest of its layer."""

    class Descriptor(MetaFileDescriptor["ParameterSetConfig"]):
        MediaType = MediaType[PARAMETER_SET_CONFIG_JSON]

    SchemaVersion = SchemaVersion[1]
    MediaType = MediaType[PARAMETER_SET_CONFIG_JSON]

    name: str
    version: str
    description: str | None = None
    created: str | None = None
    slots: list[ParameterSlot] = Field(default_factory=list)
    diff_ids: list[Sha256Digest] = Field(default_factory=list)
    files: list[ParameterSetFileEntry] | None = None
    """The layer's regular files; None when the config does not list them."""

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not SLOT_NAME.fullmatch(self.name):
            raise ValueError(f"set name {self.name!r} is not a valid name")
        if not VERSION.fullmatch(self.version):
            raise ValueError(f"set version {self.version!r} is not a valid version")
        check_slots("parameter set", self.slots)
        _layers = 1 if self.slots else 0
        if len(self.diff_ids) != _layers:
            raise ValueError(
                f"a set with {len(self.slots)} slot(s) has {_layers} diff_id(s), "
                f"not {len(self.diff_ids)}"
            )
        _seen: set[str] = set()
        for _f in self.files or ():
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

    def slot(self, name: str) -> ParameterSlot | None:
        for _s in self.slots:
            if _s.name == name:
                return _s
        return None

    def check_files(self, files: Iterable[ParameterSetFileEntry]) -> None:
        """The layer's regular files (as `read_parameter_layer` returns them) are
        exactly the ones the config lists, by path, size and digest, when it lists
        them. Raises ValueError otherwise."""
        if self.files is None:
            return
        _listed = {(_f.path, _f.size, _f.digest.digest_hex) for _f in self.files}
        _held = {(_f.path, _f.size, _f.digest.digest_hex) for _f in files}
        if _listed != _held:
            _diff = sorted(_p for _p, _, _ in _listed ^ _held)
            raise ValueError(
                f"the config lists other files than the layer holds: {_diff[:5]}"
                + (f" and {len(_diff) - 5} more" if len(_diff) > 5 else "")
            )


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
            return require_artifact_type("a parameter set's descriptor", data, info)

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
