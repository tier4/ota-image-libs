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
"""Schemas of the partition-based OTA image payload.

Whole partition images with an action per partition role, or one opaque vendor
package, instead of the files of a rootfs. Specification: spec/partition_image.md.
"""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Union

from pydantic import Field, ValidationInfo, model_validator
from typing_extensions import Self

from ota_image_libs import DIGEST_ALGORITHM
from ota_image_libs.common import (
    AliasEnabledModel,
    MediaType,
    MetaFileBase,
    MetaFileDescriptor,
    OCIDescriptor,
    SchemaVersion,
    StrEnum,
)
from ota_image_libs.common.model_spec import ArtifactType
from ota_image_libs.v1.annotation_keys import (
    OS,
    OS_VERSION,
    OTA_IMAGE_BLOBS_COUNT,
    OTA_IMAGE_BLOBS_SIZE,
    PARTITION_IMAGE_DELTA_ALGORITHM,
    PARTITION_IMAGE_DELTA_SOURCE_DIGEST,
    PARTITION_IMAGE_DELTA_SOURCE_SIZE,
    PARTITION_IMAGE_FILESYSTEM,
    PARTITION_IMAGE_FIRMWARE_FORMAT,
    PARTITION_IMAGE_UNCOMPRESSED_DIGEST,
    PARTITION_IMAGE_UNCOMPRESSED_SIZE,
    PARTITION_IMAGE_VENDOR_PACKAGE_FORMAT,
    PARTITION_IMAGE_VERITY_HASH_OFFSET,
    PARTITION_IMAGE_VERITY_ROOT_HASH,
    SYS_IMAGE_BASE_IMAGE,
)
from ota_image_libs.v1.image_config.sys_config import SysConfig
from ota_image_libs.v1.image_manifest.schema import (
    ImageIDMixin,
    ImageManifest,
    PayloadManifestDescriptor,
)
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    PARTITION_IMAGE_ARTIFACT,
    PARTITION_IMAGE_BLOB,
    PARTITION_IMAGE_BLOB_ZSTD,
    PARTITION_IMAGE_BOOT_FILES_TAR,
    PARTITION_IMAGE_CONFIG_JSON,
    PARTITION_IMAGE_DATA_IMAGE,
    PARTITION_IMAGE_DATA_IMAGE_ZSTD,
    PARTITION_IMAGE_DELTA,
    PARTITION_IMAGE_FIRMWARE_PACKAGE,
    PARTITION_IMAGE_FIRMWARE_PACKAGE_ZSTD,
    PARTITION_IMAGE_VENDOR_PACKAGE,
    PARTITION_IMAGE_VENDOR_PACKAGE_ZSTD,
)

DELTA_ALGORITHM_BLOCK_DIFF = "block-diff"  # ota_image_tools.libs.block_diff

_SHA256_DIGEST = r"^sha256:[0-9a-f]{64}$"
_HEX_DIGEST = re.compile(r"[0-9a-f]{32,128}")
# A data image or firmware name is a directory name on the device.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
# What a version range compares: dotted decimal numbers, `2.4.0` or `2026.10.1`.
_VERSION = re.compile(r"[0-9]+(\.[0-9]+)*")
# The key `requires` names the root image's version by: no data image or firmware
# takes it as its name.
REQUIRES_ROOTFS = "rootfs"


class DeliveryMode(StrEnum):
    direct = "direct"  # the update agent writes each partition itself
    vendor_package = "vendor-package"  # one opaque package, applied by the platform


class PartitionAction(StrEnum):
    write = "write"
    mkfs = "mkfs"
    keep = "keep"


class ActionPerformer(StrEnum):
    agent = "agent"
    package = "package"


# fmt: off
class _PartitionImageAnnotations(AliasEnabledModel):
    filesystem: Union[str, None] = Field(alias=PARTITION_IMAGE_FILESYSTEM, default=None)
    verity_root_hash: Union[str, None] = Field(alias=PARTITION_IMAGE_VERITY_ROOT_HASH, default=None)
    verity_hash_offset: Union[int, None] = Field(alias=PARTITION_IMAGE_VERITY_HASH_OFFSET, default=None)

    @model_validator(mode="after")
    def _verity_whole(self) -> Self:
        if (self.verity_root_hash is None) != (self.verity_hash_offset is None):
            raise ValueError("verity needs both a root hash and a hash offset, or neither")
        if self.verity_root_hash is not None and not _HEX_DIGEST.fullmatch(self.verity_root_hash):
            raise ValueError(f"verity root hash is not a hex digest: {self.verity_root_hash!r}")
        if self.verity_hash_offset is not None and self.verity_hash_offset <= 0:
            # The hash tree follows the data: at 0 it would overlap it.
            raise ValueError(f"verity hash offset must be positive: {self.verity_hash_offset}")
        return self


class _UncompressedAnnotations(AliasEnabledModel):
    """What a `+zstd` blob decodes to; the descriptor's digest and size are the stored bytes'."""

    uncompressed_digest: str = Field(alias=PARTITION_IMAGE_UNCOMPRESSED_DIGEST, pattern=_SHA256_DIGEST)
    uncompressed_size: int = Field(alias=PARTITION_IMAGE_UNCOMPRESSED_SIZE, ge=1)


class _StoredAsIs:
    """A blob stored as it is: the bytes the partition, the file or the platform's
    updater ends up with are the stored ones."""

    if TYPE_CHECKING:
        digest: Any
        size: int

    @property
    def image_digest(self) -> str:
        """The digest of the bytes the partition ends up holding."""
        return str(self.digest)

    @property
    def image_size(self) -> int:
        return self.size


class _StoredZstd:
    """A blob stored zstd-compressed: what it ends up as is in its annotations."""

    if TYPE_CHECKING:
        annotations: Any

    @property
    def image_digest(self) -> str:
        """The digest of the bytes the partition ends up holding."""
        return self.annotations.uncompressed_digest

    @property
    def image_size(self) -> int:
        return self.annotations.uncompressed_size


class PartitionImageBlobDescriptor(_StoredAsIs, OCIDescriptor):
    """A raw partition image, written to the partition as it is."""

    class Annotations(_PartitionImageAnnotations): ...

    MediaType = MediaType[PARTITION_IMAGE_BLOB]

    annotations: Union[Annotations, None] = None


class PartitionImageBlobZstdDescriptor(_StoredZstd, OCIDescriptor):
    """The same, stored zstd-compressed: decoded on the way to the partition."""

    class Annotations(_PartitionImageAnnotations, _UncompressedAnnotations): ...

    MediaType = MediaType[PARTITION_IMAGE_BLOB_ZSTD]

    annotations: Annotations = Field(...)


PARTITION_IMAGE_BLOB_TYPES = (PartitionImageBlobDescriptor, PartitionImageBlobZstdDescriptor)


class BootFilesDescriptor(OCIDescriptor):
    """A tar of the files that go into the slot's boot directory."""

    MediaType = MediaType[PARTITION_IMAGE_BOOT_FILES_TAR]


class PartitionDeltaDescriptor(OCIDescriptor):
    """A block diff that reconstructs an image from bytes the device holds, named by digest."""

    class Annotations(AliasEnabledModel):
        algorithm: str = Field(alias=PARTITION_IMAGE_DELTA_ALGORITHM)
        source_digest: str = Field(alias=PARTITION_IMAGE_DELTA_SOURCE_DIGEST, pattern=_SHA256_DIGEST)
        source_size: int = Field(alias=PARTITION_IMAGE_DELTA_SOURCE_SIZE, ge=1)

    MediaType = MediaType[PARTITION_IMAGE_DELTA]

    annotations: Annotations = Field(...)


class VendorPackageDescriptor(_StoredAsIs, OCIDescriptor):
    """One opaque package the platform's own updater applies."""

    class Annotations(AliasEnabledModel):
        format: Union[str, None] = Field(alias=PARTITION_IMAGE_VENDOR_PACKAGE_FORMAT, default=None)

    MediaType = MediaType[PARTITION_IMAGE_VENDOR_PACKAGE]

    annotations: Union[Annotations, None] = None

    @property
    def format(self) -> Union[str, None]:
        return self.annotations.format if self.annotations else None


class VendorPackageZstdDescriptor(_StoredZstd, OCIDescriptor):
    """The same, stored zstd-compressed: decoded while staging it for the platform."""

    class Annotations(_UncompressedAnnotations):
        format: Union[str, None] = Field(alias=PARTITION_IMAGE_VENDOR_PACKAGE_FORMAT, default=None)

    MediaType = MediaType[PARTITION_IMAGE_VENDOR_PACKAGE_ZSTD]

    annotations: Annotations = Field(...)

    @property
    def format(self) -> Union[str, None]:
        return self.annotations.format


class FirmwarePackageDescriptor(_StoredAsIs, OCIDescriptor):
    """A package the platform's own firmware updater applies, staged by the agent."""

    class Annotations(AliasEnabledModel):
        format: str = Field(alias=PARTITION_IMAGE_FIRMWARE_FORMAT)

    MediaType = MediaType[PARTITION_IMAGE_FIRMWARE_PACKAGE]

    annotations: Annotations = Field(...)

    @property
    def format(self) -> str:
        return self.annotations.format


class FirmwarePackageZstdDescriptor(_StoredZstd, OCIDescriptor):
    """The same, stored zstd-compressed: decoded while staging it."""

    class Annotations(_UncompressedAnnotations):
        format: str = Field(alias=PARTITION_IMAGE_FIRMWARE_FORMAT)

    MediaType = MediaType[PARTITION_IMAGE_FIRMWARE_PACKAGE_ZSTD]

    annotations: Annotations = Field(...)

    @property
    def format(self) -> str:
        return self.annotations.format


class DataImageBlobDescriptor(_StoredAsIs, OCIDescriptor):
    """A data image: a read-only filesystem image with its dm-verity hash tree appended,
    kept as a file outside the slots and mounted at a path. Written as it is."""

    class Annotations(_PartitionImageAnnotations): ...

    MediaType = MediaType[PARTITION_IMAGE_DATA_IMAGE]

    annotations: Union[Annotations, None] = None


class DataImageBlobZstdDescriptor(_StoredZstd, OCIDescriptor):
    """The same, stored zstd-compressed: decoded on the way to the file."""

    class Annotations(_PartitionImageAnnotations, _UncompressedAnnotations): ...

    MediaType = MediaType[PARTITION_IMAGE_DATA_IMAGE_ZSTD]

    annotations: Annotations = Field(...)


DATA_IMAGE_BLOB_TYPES = (DataImageBlobDescriptor, DataImageBlobZstdDescriptor)
# fmt: on


PayloadBlobDescriptor = Union[
    PartitionImageBlobDescriptor,
    PartitionImageBlobZstdDescriptor,
    BootFilesDescriptor,
    PartitionDeltaDescriptor,
    VendorPackageDescriptor,
    VendorPackageZstdDescriptor,
    DataImageBlobDescriptor,
    DataImageBlobZstdDescriptor,
    FirmwarePackageDescriptor,
    FirmwarePackageZstdDescriptor,
]


def _check_identity_delta(what: str, delta, image) -> None:
    """A delta may name the image itself as its source: that is how a release ships a
    partition it does not change. Then the source size must be the image's."""
    _src = delta.annotations
    if (
        _src.source_digest == image.image_digest
        and _src.source_size != image.image_size
    ):
        raise ValueError(
            f"{what}: the delta's source is the image itself but its size "
            f"{_src.source_size} is not the image's {image.image_size}"
        )


def _check_name_and_version(what: str, name: str, version: str) -> None:
    if not _NAME.fullmatch(name):
        raise ValueError(f"invalid {what} name: {name!r}")
    if name == REQUIRES_ROOTFS:
        raise ValueError(
            f"{what} {name!r}: the name is what `requires` calls the root image by"
        )
    if not version.strip():
        raise ValueError(f"{what} {name!r}: version must not be empty")


def version_key(version: str) -> Union[Tuple[int, ...], None]:
    """What a version range compares a version by: its dotted decimal numbers, so that
    `1.10.2` is after `1.9.0` and `1.0` is `1.0.0`. None for a version that is not
    dotted decimal numbers (`v1.2`, `2.4.0-rc1`): such a version is not guessed at."""
    if not _VERSION.fullmatch(version):
        return None
    _parts = [int(_c) for _c in version.split(".")]
    while len(_parts) > 1 and _parts[-1] == 0:
        _parts.pop()
    return tuple(_parts)


class PartitionEntry(AliasEnabledModel):
    """What happens to one partition role on an update.

    With a `delta` the payload ships only the delta; `image` still describes the result.
    """

    name: str
    action: PartitionAction
    image: Union[
        PartitionImageBlobDescriptor,
        PartitionImageBlobZstdDescriptor,
        BootFilesDescriptor,
        None,
    ] = None
    delta: Union[PartitionDeltaDescriptor, None] = None
    performed_by: ActionPerformer = ActionPerformer.agent

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not self.name or "/" in self.name or self.name in (".", ".."):
            raise ValueError(f"invalid partition name: {self.name!r}")
        if self.action != PartitionAction.write and self.image is not None:
            raise ValueError(
                f"partition {self.name!r}: action {self.action} takes no image"
            )
        if self.performed_by == ActionPerformer.package and self.image is not None:
            raise ValueError(
                f"partition {self.name!r}: an action performed by the package "
                "carries no image of its own"
            )
        if (
            self.action == PartitionAction.write
            and self.performed_by == ActionPerformer.agent
            and self.image is None
        ):
            raise ValueError(
                f"partition {self.name!r}: written by the agent but names no image"
            )
        if self.delta is not None:
            if self.action != PartitionAction.write:
                raise ValueError(
                    f"partition {self.name!r}: action {self.action} takes no delta"
                )
            if self.performed_by != ActionPerformer.agent:
                raise ValueError(
                    f"partition {self.name!r}: a delta is applied by the agent; an "
                    "action performed by the package carries its own"
                )
            if not isinstance(self.image, PARTITION_IMAGE_BLOB_TYPES):
                raise ValueError(
                    f"partition {self.name!r}: a delta reconstructs a partition image; "
                    "boot files are unpacked into a directory and have no bytes on the "
                    "device to patch"
                )
            _check_identity_delta(f"partition {self.name!r}", self.delta, self.image)
        return self


class VersionRange(AliasEnabledModel):
    """A half-open range of versions: `min` inclusive, `max` exclusive, either side open
    when absent. Both bounds are dotted decimal numbers, compared as `version_key`
    does; a version that is not is outside every range with a bound."""

    min: Union[str, None] = None
    max: Union[str, None] = None

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        for _side in (self.min, self.max):
            if _side is not None and version_key(_side) is None:
                raise ValueError(
                    f"a version bound is dotted decimal numbers, not {_side!r}"
                )
        if (
            self.min is not None
            and self.max is not None
            and version_key(self.min) >= version_key(self.max)  # type: ignore[operator]
        ):
            raise ValueError(
                f"an empty version range: min {self.min!r} is not below max {self.max!r}"
            )
        return self

    def allows(self, version: str) -> bool:
        if self.min is None and self.max is None:
            return True
        _v = version_key(version)
        if _v is None:
            return False
        if self.min is not None and _v < version_key(self.min):  # type: ignore[operator]
            return False
        if self.max is not None and _v >= version_key(self.max):  # type: ignore[operator]
            return False
        return True


class DataImageEntry(AliasEnabledModel):
    """A data image the payload carries: a file the device keeps outside the slots and
    mounts at `mount`, applied by the agent under either delivery.

    `requires` is keyed by `rootfs` or another data image's name; an agent refuses an
    image whose requirements the device does not meet. With a `delta` the payload ships
    only the delta; `image` still describes the result.
    """

    name: str
    version: str
    mount: str
    requires: Dict[str, VersionRange] = Field(default_factory=dict)
    image: Union[DataImageBlobDescriptor, DataImageBlobZstdDescriptor]
    delta: Union[PartitionDeltaDescriptor, None] = None

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        _check_name_and_version("data image", self.name, self.version)
        # In normal form, so that what is compared is what the device mounts on: `/.`
        # or `//` would be `/` itself.
        if (
            not self.mount.startswith("/")
            or self.mount.startswith("//")
            or posixpath.normpath(self.mount) != self.mount
            or self.mount == "/"
        ):
            raise ValueError(
                f"data image {self.name!r}: mount must be an absolute path below /, in "
                f"normal form, not {self.mount!r}"
            )
        if self.delta is not None:
            _check_identity_delta(f"data image {self.name!r}", self.delta, self.image)
        if self.name in self.requires:
            raise ValueError(f"data image {self.name!r} cannot require itself")
        return self


class FirmwareEntry(AliasEnabledModel):
    """A package for the platform's own firmware updater: what boots before any
    partition image is read. The agent stages it and the same trial boot judges it.

    `format` is opaque here; an agent applies the formats its platform takes.
    `requires` is as a data image's.
    """

    name: str
    version: str
    format: str
    requires: Dict[str, VersionRange] = Field(default_factory=dict)
    package: Union[FirmwarePackageDescriptor, FirmwarePackageZstdDescriptor]

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        _check_name_and_version("firmware", self.name, self.version)
        if not self.format.strip():
            raise ValueError(f"firmware {self.name!r}: format must not be empty")
        if self.package.format != self.format:
            raise ValueError(
                f"firmware {self.name!r}: the entry says format {self.format!r} but the "
                f"package's annotation says {self.package.format!r}"
            )
        if self.name in self.requires:
            raise ValueError(f"firmware {self.name!r} cannot require itself")
        return self


def payload_descriptors(
    partitions: List["PartitionEntry"],
    package: Union[VendorPackageDescriptor, VendorPackageZstdDescriptor, None],
    data_images: List[DataImageEntry] = (),  # type: ignore[assignment]
    firmware: Union[FirmwareEntry, None] = None,
) -> List[PayloadBlobDescriptor]:
    """The blobs a payload ships: per partition the delta if it has one, else the
    image; per data image the same; the firmware package; then the vendor package."""
    _res: List[PayloadBlobDescriptor] = [
        _p.delta or _p.image  # type: ignore[misc]
        for _p in partitions
        if _p.delta is not None or _p.image is not None
    ]
    _res.extend(_d.delta or _d.image for _d in data_images)
    if firmware is not None:
        _res.append(firmware.package)
    if package is not None:
        _res.append(package)
    return _res


class PartitionImageConfig(MetaFileBase):
    """Per-payload configuration of a partition-based OTA image payload."""

    class Descriptor(MetaFileDescriptor["PartitionImageConfig"]):
        MediaType = MediaType[PARTITION_IMAGE_CONFIG_JSON]

    # fmt: off
    class Annotations(AliasEnabledModel):
        base_image: str = Field(alias=SYS_IMAGE_BASE_IMAGE)
        os: Union[str, None] = Field(alias=OS, default=None)
        os_version: Union[str, None] = Field(alias=OS_VERSION, default=None)

        image_blobs_count: int = Field(alias=OTA_IMAGE_BLOBS_COUNT)
        image_blobs_size: int = Field(alias=OTA_IMAGE_BLOBS_SIZE)
    # fmt: on

    SchemaVersion = SchemaVersion[1]
    MediaType = MediaType[PARTITION_IMAGE_CONFIG_JSON]

    resource_digest_alg: str = Field(init=False, default=DIGEST_ALGORITHM)
    description: Union[str, None] = None
    created: Union[str, None] = None
    architecture: str
    os: Union[str, None] = None
    os_version: Union[str, None] = Field(alias="os.version", default=None)
    image_version: str
    delivery: DeliveryMode
    partitions: List[PartitionEntry]
    data_images: List[DataImageEntry] = Field(default_factory=list)
    firmware: Union[FirmwareEntry, None] = None
    package: Union[VendorPackageDescriptor, VendorPackageZstdDescriptor, None] = None
    sys_config: Union[SysConfig.Descriptor, None] = None
    labels: Annotations

    @model_validator(mode="after")
    def _well_formed(self) -> Self:
        if not self.image_version.strip():
            raise ValueError("image_version must not be empty")
        if not self.partitions:
            raise ValueError("partitions must not be empty")
        _names = [_p.name for _p in self.partitions]
        if len(set(_names)) != len(_names):
            raise ValueError(f"partition names must be unique: {_names}")
        _data_names = [_d.name for _d in self.data_images]
        if len(set(_data_names)) != len(_data_names):
            raise ValueError(f"data image names must be unique: {_data_names}")
        if self.firmware is not None and self.firmware.name in _data_names:
            raise ValueError(
                f"firmware {self.firmware.name!r} is named like a data image; "
                "the names are one namespace"
            )
        for _taken in _data_names + ([self.firmware.name] if self.firmware else []):
            if _taken in _names:
                raise ValueError(
                    f"{_taken!r} is a partition role; a data image or firmware cannot "
                    "be named after one (`requires` keys would be ambiguous)"
                )
        if (
            self.delivery == DeliveryMode.direct
            and all(_p.action == PartitionAction.keep for _p in self.partitions)
            and not self.data_images
            and self.firmware is None
        ):
            raise ValueError(
                "the payload keeps every partition and carries no data image and no "
                "firmware: there is nothing to install"
            )

        if self.delivery == DeliveryMode.direct:
            if self.package is not None:
                raise ValueError("delivery 'direct' carries no vendor package")
            for _p in self.partitions:
                if _p.performed_by != ActionPerformer.agent:
                    raise ValueError(
                        f"delivery 'direct': partition {_p.name!r} must be "
                        "performed by the agent"
                    )
        else:
            if self.package is None:
                raise ValueError("delivery 'vendor-package' needs the package")
            for _p in self.partitions:
                if (
                    _p.action == PartitionAction.write
                    and _p.performed_by != ActionPerformer.package
                ):
                    raise ValueError(
                        f"delivery 'vendor-package': partition {_p.name!r} is "
                        "written by the package, not by the agent"
                    )
        return self

    def partition(self, name: str) -> Union[PartitionEntry, None]:
        for _p in self.partitions:
            if _p.name == name:
                return _p
        return None

    def data_image(self, name: str) -> Union[DataImageEntry, None]:
        for _d in self.data_images:
            if _d.name == name:
                return _d
        return None

    @property
    def written_partitions(self) -> List[PartitionEntry]:
        return [_p for _p in self.partitions if _p.action == PartitionAction.write]

    @property
    def payload_descriptors(self) -> List[PayloadBlobDescriptor]:
        """Every blob this payload ships, in order: the manifest's `layers`."""
        return payload_descriptors(
            self.partitions, self.package, self.data_images, self.firmware
        )


class PartitionImageManifest(ImageIDMixin, MetaFileBase):
    """The OCI image manifest of a partition-based payload: the file-based payload's
    shape and annotations, told apart by its artifactType."""

    # fmt: off
    class Descriptor(PayloadManifestDescriptor["PartitionImageManifest"]):
        class Annotations(ImageManifest.Descriptor.Annotations): ...

        MediaType = MediaType[IMAGE_MANIFEST]
        ArtifactType = ArtifactType[PARTITION_IMAGE_ARTIFACT]

        annotations: Annotations = Field(...)

        @model_validator(mode="before")
        @classmethod
        def _artifact_type_present(cls, data: Any, info: ValidationInfo) -> Any:
            # The two payload kinds share a mediaType: an entry without artifactType is
            # the file-based payload's.
            if info.mode == "json" and isinstance(data, dict) and "artifactType" not in data:
                raise ValueError("a partition-based payload's descriptor carries artifactType")
            return data
    # fmt: on

    class Annotations(ImageManifest.Annotations): ...

    SchemaVersion = SchemaVersion[2]
    MediaType = MediaType[IMAGE_MANIFEST]
    ArtifactType = ArtifactType[PARTITION_IMAGE_ARTIFACT]

    config: PartitionImageConfig.Descriptor
    layers: List[PayloadBlobDescriptor]
    annotations: Annotations
