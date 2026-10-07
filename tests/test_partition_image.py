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
"""Tests for the partition-based OTA image payload."""

from __future__ import annotations

import io
import json
import tarfile
from hashlib import sha256
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest
from pydantic import ValidationError

from ota_image_libs.v1.annotation_keys import (
    BUILD_TOOL_VERSION,
    OTA_IMAGE_BLOBS_COUNT,
    OTA_IMAGE_BLOBS_SIZE,
    OTA_RELEASE_KEY,
    PARTITION_IMAGE_DELTA_ALGORITHM,
    PARTITION_IMAGE_DELTA_SOURCE_DIGEST,
    PARTITION_IMAGE_DELTA_SOURCE_SIZE,
    PARTITION_IMAGE_FILESYSTEM,
    PARTITION_IMAGE_FIRMWARE_FORMAT,
    PARTITION_IMAGE_UNCOMPRESSED_DIGEST,
    PARTITION_IMAGE_UNCOMPRESSED_SIZE,
    PARTITION_IMAGE_VERITY_HASH_OFFSET,
    PARTITION_IMAGE_VERITY_ROOT_HASH,
    PLATFORM_ECU,
    PLATFORM_ECU_ARCH,
    SYS_IMAGE_BASE_IMAGE,
)
from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.consts import IMAGE_INDEX_FNAME, RESOURCE_DIR
from ota_image_libs.v1.image_index.schema import ImageIndex
from ota_image_libs.v1.image_manifest.schema import (
    ImageIdentifier,
    ImageManifest,
    OTAReleaseKey,
)
from ota_image_libs.v1.media_types import (
    IMAGE_MANIFEST,
    PARTITION_IMAGE_ARTIFACT,
    PARTITION_IMAGE_BLOB_ZSTD,
    PARTITION_IMAGE_CONFIG_JSON,
    PARTITION_IMAGE_DATA_IMAGE,
    PARTITION_IMAGE_DATA_IMAGE_ZSTD,
    PARTITION_IMAGE_DELTA,
    PARTITION_IMAGE_FIRMWARE_PACKAGE,
    PARTITION_IMAGE_VENDOR_PACKAGE_ZSTD,
)
from ota_image_libs.v1.partition_image.schema import (
    DELTA_ALGORITHM_BLOCK_DIFF,
    ActionPerformer,
    BootFilesDescriptor,
    DataImageBlobDescriptor,
    DataImageBlobZstdDescriptor,
    DataImageEntry,
    DeliveryMode,
    FirmwareEntry,
    FirmwarePackageDescriptor,
    PartitionAction,
    PartitionDeltaDescriptor,
    PartitionEntry,
    PartitionImageBlobDescriptor,
    PartitionImageBlobZstdDescriptor,
    PartitionImageConfig,
    PartitionImageManifest,
    VendorPackageDescriptor,
    VendorPackageZstdDescriptor,
    VersionRange,
)
from ota_image_libs.v1.update_agent_package.schema import UpdateAgentPackageManifest
from ota_image_tools.cmds.list_image import _render_output

ROOT_HASH = "194fde591ff4d762eb379215fa650c61f359d9ea66dc4c3be9b27e9a02726abc"
ROOTFS_BYTES = b"\x01" * 8192 + b"\x02" * 4096  # "data" then "hash tree"
HASH_OFFSET = 8192


def boot_tar_bytes() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in (
            ("vmlinuz", b"kernel"),
            ("initrd.img", b"initrd"),
            ("grub.cfg", b"linux /${slot}/vmlinuz root=/dev/mapper/vroot\n"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def resource_dir(tmp_path: Path) -> Path:
    _d = tmp_path / RESOURCE_DIR
    _d.mkdir(parents=True)
    return _d


def make_blobs(resource_dir: Path):
    rootfs = tmp_file(resource_dir.parents[1], "rootfs.img", ROOTFS_BYTES)
    boot = tmp_file(resource_dir.parents[1], "boot.tar", boot_tar_bytes())
    rootfs_descriptor = PartitionImageBlobDescriptor.add_file_to_resource_dir(
        rootfs,
        resource_dir,
        annotations={
            PARTITION_IMAGE_FILESYSTEM: "ext4",
            PARTITION_IMAGE_VERITY_ROOT_HASH: ROOT_HASH,
            PARTITION_IMAGE_VERITY_HASH_OFFSET: HASH_OFFSET,
        },
    )
    boot_descriptor = BootFilesDescriptor.add_file_to_resource_dir(boot, resource_dir)
    return rootfs_descriptor, boot_descriptor


def tmp_file(parent: Path, name: str, data: bytes) -> Path:
    _f = parent / name
    _f.write_bytes(data)
    return _f


def direct_config(
    rootfs_descriptor, boot_descriptor, data_images=()
) -> PartitionImageConfig:
    return PartitionImageConfig(
        architecture="x86_64",
        os="linux",
        os_version="24.04",  # type: ignore[call-arg]
        image_version="1.2.0",
        delivery=DeliveryMode.direct,
        data_images=list(data_images),
        partitions=[
            PartitionEntry(
                name="rootfs", action=PartitionAction.write, image=rootfs_descriptor
            ),
            PartitionEntry(
                name="boot", action=PartitionAction.write, image=boot_descriptor
            ),
            PartitionEntry(name="scratch", action=PartitionAction.mkfs),
            PartitionEntry(name="identity", action=PartitionAction.keep),
            PartitionEntry(name="optdata", action=PartitionAction.keep),
        ],
        labels=PartitionImageConfig.Annotations.model_validate(
            {
                SYS_IMAGE_BASE_IMAGE: "ubuntu:24.04",
                OTA_IMAGE_BLOBS_COUNT: 2,
                OTA_IMAGE_BLOBS_SIZE: rootfs_descriptor.size + boot_descriptor.size,
            }
        ),
    )


MANIFEST_ANNOTATIONS = {
    PLATFORM_ECU: "autoware",
    OTA_RELEASE_KEY: "dev",
    PLATFORM_ECU_ARCH: "x86_64",
}


class TestPartitionEntry:
    def test_write_by_the_agent_needs_an_image(self):
        with pytest.raises(ValidationError, match="names no image"):
            PartitionEntry(name="rootfs", action=PartitionAction.write)

    def test_mkfs_and_keep_take_no_image(self, resource_dir):
        rootfs_descriptor, _ = make_blobs(resource_dir)
        for action in (PartitionAction.mkfs, PartitionAction.keep):
            with pytest.raises(ValidationError, match="takes no image"):
                PartitionEntry(name="scratch", action=action, image=rootfs_descriptor)

    def test_the_package_carries_no_image_of_its_own(self, resource_dir):
        rootfs_descriptor, _ = make_blobs(resource_dir)
        with pytest.raises(ValidationError, match="carries no image"):
            PartitionEntry(
                name="rootfs",
                action=PartitionAction.write,
                image=rootfs_descriptor,
                performed_by=ActionPerformer.package,
            )

    @pytest.mark.parametrize("name", ["", "a/b", ".", ".."])
    def test_a_role_is_a_name_not_a_path(self, name):
        with pytest.raises(ValidationError, match="invalid partition name"):
            PartitionEntry(name=name, action=PartitionAction.keep)


def delta_descriptor(
    resource_dir: Path,
    *,
    source_digest: str = "sha256:" + "cd" * 32,
    source_size: int = 4096,
    algorithm: str = DELTA_ALGORITHM_BLOCK_DIFF,
    data: bytes = b"a delta",
) -> PartitionDeltaDescriptor:
    blob = tmp_file(resource_dir.parents[1], "rootfs.delta", data)
    return PartitionDeltaDescriptor.add_file_to_resource_dir(
        blob,
        resource_dir,
        annotations={
            PARTITION_IMAGE_DELTA_ALGORITHM: algorithm,
            PARTITION_IMAGE_DELTA_SOURCE_DIGEST: source_digest,
            PARTITION_IMAGE_DELTA_SOURCE_SIZE: source_size,
        },
    )


class TestPartitionDelta:
    """A delta reconstructs the image beside it from bytes the device already has."""

    def test_a_delta_rides_beside_the_image_it_reconstructs(self, resource_dir):
        rootfs_descriptor, _ = make_blobs(resource_dir)
        entry = PartitionEntry(
            name="rootfs",
            action=PartitionAction.write,
            image=rootfs_descriptor,
            delta=delta_descriptor(resource_dir),
        )
        assert entry.delta is not None
        assert entry.delta.annotations.algorithm == "block-diff"
        assert entry.delta.annotations.source_size == 4096

    def test_a_delta_needs_the_image_it_reconstructs(self, resource_dir):
        """`image` is what the partition must end up holding; without it the agent has
        nothing to verify the reconstruction against."""
        with pytest.raises(ValidationError, match="names no image"):
            PartitionEntry(
                name="rootfs",
                action=PartitionAction.write,
                delta=delta_descriptor(resource_dir),
            )

    def test_a_delta_from_the_image_itself_says_the_device_holds_it(self, resource_dir):
        """The smallest statement that nothing changed: a release whose rootfs did not
        change ships it this way beside the firmware that did."""
        rootfs_descriptor, _ = make_blobs(resource_dir)
        _e = PartitionEntry(
            name="rootfs",
            action=PartitionAction.write,
            image=rootfs_descriptor,
            delta=delta_descriptor(
                resource_dir,
                source_digest=rootfs_descriptor.image_digest,
                source_size=rootfs_descriptor.image_size,
            ),
        )
        assert _e.delta is not None
        assert _e.delta.annotations.source_digest == _e.image.image_digest

    @pytest.mark.parametrize("action", [PartitionAction.mkfs, PartitionAction.keep])
    def test_only_a_written_partition_takes_a_delta(self, action, resource_dir):
        with pytest.raises(ValidationError, match="takes no delta"):
            PartitionEntry(
                name="scratch", action=action, delta=delta_descriptor(resource_dir)
            )

    def test_the_package_applies_its_own_delta(self, resource_dir):
        """A vendor package carries whatever delta it needs inside itself."""
        rootfs_descriptor, _ = make_blobs(resource_dir)
        with pytest.raises(ValidationError, match="package"):
            PartitionEntry(
                name="rootfs",
                action=PartitionAction.write,
                image=rootfs_descriptor,
                delta=delta_descriptor(resource_dir),
                performed_by=ActionPerformer.package,
            )

    @pytest.mark.parametrize(
        "missing",
        [
            PARTITION_IMAGE_DELTA_ALGORITHM,
            PARTITION_IMAGE_DELTA_SOURCE_DIGEST,
            PARTITION_IMAGE_DELTA_SOURCE_SIZE,
        ],
    )
    def test_the_source_and_the_algorithm_are_required(self, resource_dir, missing):
        """A delta whose source or algorithm is unnamed could be applied to the wrong
        bytes, or with the wrong tool."""
        payload = delta_descriptor(resource_dir).model_dump(mode="json", by_alias=True)
        del payload["annotations"][missing]
        with pytest.raises(ValidationError):
            PartitionDeltaDescriptor.model_validate(payload)

    def test_a_partition_with_a_delta_ships_the_delta_and_not_the_image(
        self, resource_dir
    ):
        """What makes a delta campaign small: the image bytes stay on the device."""
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        delta = delta_descriptor(resource_dir)
        config = direct_config(rootfs_descriptor, boot_descriptor)
        config.partitions[0] = PartitionEntry(
            name="rootfs",
            action=PartitionAction.write,
            image=rootfs_descriptor,
            delta=delta,
        )
        shipped = {str(d.digest) for d in config.payload_descriptors}
        assert str(delta.digest) in shipped
        assert str(rootfs_descriptor.digest) not in shipped
        assert str(boot_descriptor.digest) in shipped

    def test_boot_files_take_no_delta(self, resource_dir):
        """The boot files are unpacked into a directory; nothing on the device is the
        byte stream a patch would apply to."""
        _, boot_descriptor = make_blobs(resource_dir)
        with pytest.raises(ValidationError, match="reconstructs a partition image"):
            PartitionEntry(
                name="boot",
                action=PartitionAction.write,
                image=boot_descriptor,
                delta=delta_descriptor(resource_dir),
            )

    def test_the_descriptor_carries_the_delta_media_type(self, resource_dir):
        """What tells a reader that these bytes are a patch and not an image."""
        payload = delta_descriptor(resource_dir).model_dump(mode="json", by_alias=True)
        assert payload["mediaType"] == PARTITION_IMAGE_DELTA
        assert payload["annotations"][PARTITION_IMAGE_DELTA_SOURCE_SIZE] == 4096


class TestCompressedBlobs:
    """A blob may be stored zstd-compressed; what the partition ends up holding is then
    in the annotations, and that is what a delta and a reconstruction refer to."""

    def _zstd_rootfs(self, resource_dir):
        rootfs = tmp_file(resource_dir.parents[1], "rootfs.img", ROOTFS_BYTES)
        return PartitionImageBlobZstdDescriptor.add_file_to_resource_dir(
            rootfs,
            resource_dir,
            annotations={
                PARTITION_IMAGE_FILESYSTEM: "ext4",
                PARTITION_IMAGE_UNCOMPRESSED_DIGEST: "sha256:"
                + sha256(ROOTFS_BYTES).hexdigest(),
                PARTITION_IMAGE_UNCOMPRESSED_SIZE: len(ROOTFS_BYTES),
            },
        )

    def test_the_stored_bytes_are_compressed_and_the_image_is_named(self, resource_dir):
        desc = self._zstd_rootfs(resource_dir)
        assert desc.mediaType == PARTITION_IMAGE_BLOB_ZSTD
        stored = (resource_dir / desc.digest.digest_hex).read_bytes()
        assert stored[:4] == b"\x28\xb5\x2f\xfd"  # a zstd frame
        assert desc.size == len(stored) != len(ROOTFS_BYTES)
        assert desc.image_size == len(ROOTFS_BYTES)
        assert desc.image_digest == "sha256:" + sha256(ROOTFS_BYTES).hexdigest()

    def test_a_compressed_image_needs_to_say_what_it_decodes_to(self, resource_dir):
        rootfs = tmp_file(resource_dir.parents[1], "rootfs.img", ROOTFS_BYTES)
        with pytest.raises(ValidationError, match="uncompressed"):
            PartitionImageBlobZstdDescriptor.add_file_to_resource_dir(
                rootfs, resource_dir, annotations={PARTITION_IMAGE_FILESYSTEM: "ext4"}
            )

    def test_an_entry_takes_a_compressed_image(self, resource_dir):
        desc = self._zstd_rootfs(resource_dir)
        entry = PartitionEntry(name="rootfs", action=PartitionAction.write, image=desc)
        raw = entry.model_dump(mode="json", by_alias=True)
        again = PartitionEntry.model_validate(raw)
        assert isinstance(again.image, PartitionImageBlobZstdDescriptor)
        assert again.image.image_size == len(ROOTFS_BYTES)

    def test_a_delta_from_a_compressed_images_own_bytes_is_the_same_statement(
        self, resource_dir
    ):
        desc = self._zstd_rootfs(resource_dir)
        _e = PartitionEntry(
            name="rootfs",
            action=PartitionAction.write,
            image=desc,
            delta=delta_descriptor(
                resource_dir,
                source_digest=desc.image_digest,
                source_size=desc.image_size,
            ),
        )
        assert (
            _e.delta is not None
            and _e.delta.annotations.source_digest == desc.image_digest
        )

    def test_a_vendor_package_may_be_compressed_too(self, resource_dir):
        package = tmp_file(resource_dir.parents[1], "package.bin", b"p" * 8192)
        desc = VendorPackageZstdDescriptor.add_file_to_resource_dir(
            package,
            resource_dir,
            annotations={
                "vnd.tier4.ota.partition-image.vendor-package.format": "example",
                PARTITION_IMAGE_UNCOMPRESSED_DIGEST: "sha256:"
                + sha256(b"p" * 8192).hexdigest(),
                PARTITION_IMAGE_UNCOMPRESSED_SIZE: 8192,
            },
        )
        assert desc.mediaType == PARTITION_IMAGE_VENDOR_PACKAGE_ZSTD
        assert desc.format == "example"
        assert desc.size < 8192
        config = PartitionImageConfig(
            architecture="x86_64",
            image_version="1.0.0",
            delivery=DeliveryMode.vendor_package,
            partitions=[
                PartitionEntry(
                    name="rootfs",
                    action=PartitionAction.write,
                    performed_by=ActionPerformer.package,
                ),
            ],
            package=desc,
            labels=PartitionImageConfig.Annotations.model_validate(
                {
                    SYS_IMAGE_BASE_IMAGE: "x",
                    OTA_IMAGE_BLOBS_COUNT: 1,
                    OTA_IMAGE_BLOBS_SIZE: desc.size,
                }
            ),
        )
        assert config.payload_descriptors == [desc]


class TestDataImages:
    """A data image is a read-only filesystem image the device keeps as a file outside
    the slots and mounts; it rides in the config beside the partitions and can be the
    only thing a payload carries."""

    @staticmethod
    def data_descriptor(resource_dir, data: bytes = b"\x07" * 8192, **annotations):
        _f = resource_dir / "ml.img"
        _f.write_bytes(data)
        _a = {
            PARTITION_IMAGE_FILESYSTEM: "squashfs",
            PARTITION_IMAGE_VERITY_ROOT_HASH: ROOT_HASH,
            PARTITION_IMAGE_VERITY_HASH_OFFSET: 4096,
            **annotations,
        }
        return DataImageBlobDescriptor.add_file_to_resource_dir(
            _f, resource_dir, annotations=_a
        )

    def entry(self, resource_dir, **overrides):
        _kw = dict(
            name="ml_package",
            version="2026.9.1",
            mount="/opt/autoware/ml",
            image=self.data_descriptor(resource_dir),
        )
        _kw.update(overrides)
        return DataImageEntry(**_kw)

    def test_an_entry_names_the_image_and_where_it_mounts(self, resource_dir):
        _e = self.entry(resource_dir)
        assert _e.image.mediaType == PARTITION_IMAGE_DATA_IMAGE
        assert _e.image.image_size == 8192
        assert _e.image.annotations is not None
        assert _e.image.annotations.filesystem == "squashfs"
        assert _e.requires == {}

    @pytest.mark.parametrize("name", ["", "a/b", "..", ".", "x" * 65, "-lead"])
    def test_the_name_is_a_directory_name(self, resource_dir, name):
        with pytest.raises(ValidationError, match="invalid data image name"):
            self.entry(resource_dir, name=name)

    @pytest.mark.parametrize("mount", ["opt/ml", "/", "/opt/../etc", ""])
    def test_the_mount_is_an_absolute_path(self, resource_dir, mount):
        with pytest.raises(ValidationError, match="mount must be"):
            self.entry(resource_dir, mount=mount)

    def test_a_compressed_data_image_names_what_it_decodes_to(self, resource_dir):
        _raw = b"\x07" * 8192
        _f = resource_dir / "ml.img"
        _f.write_bytes(_raw)
        _d = DataImageBlobZstdDescriptor.add_file_to_resource_dir(
            _f,
            resource_dir,
            annotations={
                PARTITION_IMAGE_UNCOMPRESSED_DIGEST: f"sha256:{sha256(_raw).hexdigest()}",
                PARTITION_IMAGE_UNCOMPRESSED_SIZE: len(_raw),
            },
            zstd_compression_level=3,
        )
        assert _d.mediaType == PARTITION_IMAGE_DATA_IMAGE_ZSTD
        assert _d.image_size == len(_raw) and _d.size < len(_raw)
        _e = self.entry(resource_dir, image=_d)
        assert _e.image.image_digest == f"sha256:{sha256(_raw).hexdigest()}"

    def test_a_delta_rides_beside_the_image_and_replaces_it_in_the_payload(
        self, resource_dir
    ):
        _e = self.entry(resource_dir, delta=delta_descriptor(resource_dir))
        assert _e.delta is not None
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        config = direct_config(rootfs_descriptor, boot_descriptor, data_images=[_e])
        assert config.payload_descriptors == [
            rootfs_descriptor,
            boot_descriptor,
            _e.delta,
        ]

    def test_a_delta_from_the_image_itself_says_the_device_holds_it(self, resource_dir):
        _img = self.data_descriptor(resource_dir)
        _delta_file = resource_dir / "d.tar"
        _delta_file.write_bytes(b"ops")
        _delta = PartitionDeltaDescriptor.add_file_to_resource_dir(
            _delta_file,
            resource_dir,
            annotations={
                PARTITION_IMAGE_DELTA_ALGORITHM: DELTA_ALGORITHM_BLOCK_DIFF,
                PARTITION_IMAGE_DELTA_SOURCE_DIGEST: str(_img.digest),
                PARTITION_IMAGE_DELTA_SOURCE_SIZE: _img.image_size,
            },
        )
        # allowed: the smallest statement that the device already holds this image
        _e = self.entry(resource_dir, image=_img, delta=_delta)
        assert _e.delta is not None and _e.delta.annotations.source_digest == str(
            _img.digest
        )

    def test_requirements_are_version_ranges(self, resource_dir):
        _e = self.entry(
            resource_dir, requires={"rootfs": {"min": "2.4.0", "max": "3.0.0"}}
        )
        _r = _e.requires["rootfs"]
        assert _r.allows("2.4.0") and _r.allows("2.10.7")
        assert not _r.allows("2.3.9") and not _r.allows("3.0.0")
        assert VersionRange().allows("anything")
        with pytest.raises(ValidationError, match="must not be blank"):
            VersionRange(min=" ")

    def test_a_config_may_carry_only_data_images(self, resource_dir):
        """Every partition kept, one data image: how a data image is updated on its
        own, without a slot written or a reboot into another slot."""
        _e = self.entry(resource_dir)
        config = PartitionImageConfig(
            architecture="x86_64",
            image_version="2026.9.1",
            delivery=DeliveryMode.direct,
            partitions=[
                PartitionEntry(name=_n, action=PartitionAction.keep)
                for _n in ("rootfs", "boot", "scratch", "identity", "optdata")
            ],
            data_images=[_e],
            labels=PartitionImageConfig.Annotations.model_validate(
                {
                    SYS_IMAGE_BASE_IMAGE: "ubuntu:24.04",
                    OTA_IMAGE_BLOBS_COUNT: 1,
                    OTA_IMAGE_BLOBS_SIZE: _e.image.size,
                }
            ),
        )
        assert config.written_partitions == []
        assert config.payload_descriptors == [_e.image]
        parsed = PartitionImageConfig.parse_metafile(config.export_metafile())
        assert parsed == config
        assert parsed.data_image("ml_package") is not None
        assert parsed.data_image("maps") is None
        _raw = json.loads(config.export_metafile())
        assert _raw["data_images"][0]["mount"] == "/opt/autoware/ml"

    def test_names_must_be_unique(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        _e = self.entry(resource_dir)
        with pytest.raises(ValidationError, match="data image names must be unique"):
            direct_config(rootfs_descriptor, boot_descriptor, data_images=[_e, _e])

    def test_an_old_config_without_data_images_still_parses(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        _raw = json.loads(
            direct_config(rootfs_descriptor, boot_descriptor).export_metafile()
        )
        assert "data_images" in _raw
        del _raw["data_images"]
        parsed = PartitionImageConfig.model_validate(_raw)
        assert parsed.data_images == []


class TestPartitionImageConfig:
    def test_round_trip(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        config = direct_config(rootfs_descriptor, boot_descriptor)

        exported = config.export_metafile()
        raw = json.loads(exported)
        assert raw["schemaVersion"] == 1
        assert raw["mediaType"] == PARTITION_IMAGE_CONFIG_JSON
        assert raw["delivery"] == "direct"
        assert raw["image_version"] == "1.2.0"
        assert raw["os.version"] == "24.04"
        assert [p["name"] for p in raw["partitions"]] == [
            "rootfs",
            "boot",
            "scratch",
            "identity",
            "optdata",
        ]
        assert "image" not in raw["partitions"][2]
        assert (
            raw["partitions"][0]["image"]["annotations"][
                PARTITION_IMAGE_VERITY_ROOT_HASH
            ]
            == ROOT_HASH
        )

        parsed = PartitionImageConfig.parse_metafile(exported)
        assert parsed == config
        rootfs = parsed.partition("rootfs")
        assert rootfs is not None and isinstance(
            rootfs.image, PartitionImageBlobDescriptor
        )
        assert rootfs.image.annotations is not None
        assert rootfs.image.annotations.verity_hash_offset == HASH_OFFSET
        boot = parsed.partition("boot")
        assert boot is not None and isinstance(boot.image, BootFilesDescriptor)
        assert parsed.partition("nothing") is None
        assert [p.name for p in parsed.written_partitions] == ["rootfs", "boot"]
        assert parsed.payload_descriptors == [rootfs_descriptor, boot_descriptor]

    def test_direct_delivery_takes_no_package(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        config = direct_config(rootfs_descriptor, boot_descriptor)
        package = VendorPackageDescriptor.add_contents_to_resource_dir(
            b"pkg", resource_dir
        )
        with pytest.raises(ValidationError, match="carries no vendor package"):
            PartitionImageConfig(**dict(config, package=package))

    def test_vendor_package_delivery(self, resource_dir):
        package = VendorPackageDescriptor.add_contents_to_resource_dir(
            b"pkg",
            resource_dir,
            annotations={
                "vnd.tier4.ota.partition-image.vendor-package.format": "example"
            },
        )
        config = PartitionImageConfig(
            architecture="aarch64",
            image_version="1.0.0",
            delivery=DeliveryMode.vendor_package,
            package=package,
            partitions=[
                PartitionEntry(
                    name="rootfs",
                    action=PartitionAction.write,
                    performed_by=ActionPerformer.package,
                ),
                PartitionEntry(name="identity", action=PartitionAction.keep),
            ],
            labels=PartitionImageConfig.Annotations.model_validate(
                {
                    SYS_IMAGE_BASE_IMAGE: "vendor-base",
                    OTA_IMAGE_BLOBS_COUNT: 1,
                    OTA_IMAGE_BLOBS_SIZE: 3,
                }
            ),
        )
        parsed = PartitionImageConfig.parse_metafile(config.export_metafile())
        assert parsed.package is not None
        assert parsed.package.annotations is not None
        assert parsed.package.annotations.format == "example"
        assert parsed.payload_descriptors == [package]

        with pytest.raises(ValidationError, match="needs the package"):
            PartitionImageConfig(**dict(config, package=None))
        with pytest.raises(ValidationError, match="written by the package"):
            PartitionImageConfig(
                **dict(
                    config,
                    partitions=[
                        PartitionEntry(
                            name="rootfs",
                            action=PartitionAction.write,
                            image=make_blobs(resource_dir)[0],
                        )
                    ],
                )
            )

    def test_names_must_be_unique_and_version_non_empty(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        config = direct_config(rootfs_descriptor, boot_descriptor)
        with pytest.raises(ValidationError, match="must be unique"):
            PartitionImageConfig(
                **dict(config, partitions=config.partitions + [config.partitions[-1]])
            )
        with pytest.raises(ValidationError, match="must not be empty"):
            PartitionImageConfig(**dict(config, image_version=" "))
        with pytest.raises(ValidationError, match="must not be empty"):
            PartitionImageConfig(**dict(config, partitions=[]))


def build_image(resource_dir: Path, *, with_file_based: bool = False) -> Path:
    """An OTA image folder holding one partition-based payload (and, optionally, a
    file-based one for another ECU) — what the builder would write."""
    rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
    config = direct_config(rootfs_descriptor, boot_descriptor)
    config_descriptor = PartitionImageConfig.Descriptor.export_metafile_to_resource_dir(
        config, resource_dir
    )
    manifest = PartitionImageManifest(
        config=config_descriptor,
        layers=[rootfs_descriptor, boot_descriptor],
        annotations=PartitionImageManifest.Annotations.model_validate(
            MANIFEST_ANNOTATIONS
        ),
    )
    manifest_descriptor = (
        PartitionImageManifest.Descriptor.export_metafile_to_resource_dir(
            manifest, resource_dir, annotations=MANIFEST_ANNOTATIONS
        )
    )
    index = ImageIndex(
        manifests=[],
        annotations=ImageIndex.Annotations.model_validate({BUILD_TOOL_VERSION: "test"}),
    )
    index.add_image(manifest_descriptor)

    if with_file_based:
        # borrow a real file-based manifest descriptor from the fixture image
        fixture = Path(__file__).parent / "data" / "ota-image.zip"
        with ZipFile(fixture) as zf:
            fixture_index = ImageIndex.parse_metafile(
                zf.read(IMAGE_INDEX_FNAME).decode()
            )
            file_based = next(
                d
                for d in fixture_index.manifests
                if isinstance(d, ImageManifest.Descriptor)
            )
            (resource_dir / file_based.digest.digest_hex).write_bytes(
                zf.read(f"{RESOURCE_DIR}/{file_based.digest.digest_hex}")
            )
        # a different ECU, so both can live in one index
        file_based = ImageManifest.Descriptor(
            size=file_based.size,
            digest=file_based.digest,
            annotations=ImageManifest.Descriptor.Annotations.model_validate(
                {PLATFORM_ECU: "perception", OTA_RELEASE_KEY: "dev"}
            ),
        )
        index.add_image(file_based)

    image_root = resource_dir.parents[1]  # RESOURCE_DIR is blobs/sha256
    (image_root / IMAGE_INDEX_FNAME).write_text(index.export_metafile())
    return image_root


def pack(image_root: Path, artifact: Path) -> Path:
    with ZipFile(artifact, "w", compression=ZIP_STORED) as zf:
        zf.write(image_root / IMAGE_INDEX_FNAME, IMAGE_INDEX_FNAME)
        for blob in sorted((image_root / RESOURCE_DIR).iterdir()):
            zf.write(blob, f"{RESOURCE_DIR}/{blob.name}")
    return artifact


class TestManifestAndIndex:
    def test_the_manifest_is_an_oci_manifest_with_its_own_artifact_type(
        self, resource_dir
    ):
        image_root = build_image(resource_dir)
        index = ImageIndex.parse_metafile((image_root / IMAGE_INDEX_FNAME).read_text())
        descriptor = index.manifests[0]
        assert isinstance(descriptor, PartitionImageManifest.Descriptor)
        raw = json.loads((image_root / IMAGE_INDEX_FNAME).read_text())
        assert raw["manifests"][0]["mediaType"] == IMAGE_MANIFEST
        assert raw["manifests"][0]["artifactType"] == PARTITION_IMAGE_ARTIFACT

        manifest = descriptor.load_metafile_from_resource_dir(resource_dir)
        assert isinstance(manifest, PartitionImageManifest)
        assert manifest.schemaVersion == 2
        assert manifest.ArtifactType == PARTITION_IMAGE_ARTIFACT
        assert manifest.ecu_id == "autoware"
        assert manifest.ota_release_key == OTAReleaseKey.dev
        assert len(manifest.layers) == 2

    def test_the_index_tells_the_two_payload_kinds_apart(self, resource_dir):
        image_root = build_image(resource_dir, with_file_based=True)
        index = ImageIndex.parse_metafile((image_root / IMAGE_INDEX_FNAME).read_text())

        partition = index.find_image_payload(
            ImageIdentifier("autoware", OTAReleaseKey.dev)
        )
        file_based = index.find_image_payload(
            ImageIdentifier("perception", OTAReleaseKey.dev)
        )
        assert isinstance(partition, PartitionImageManifest.Descriptor)
        assert isinstance(file_based, ImageManifest.Descriptor)
        assert (
            index.find_partition_image(ImageIdentifier("perception", OTAReleaseKey.dev))
            is None
        )
        assert index.find_image(ImageIdentifier("autoware", OTAReleaseKey.dev)) is None
        assert isinstance(
            index.find_image(ImageIdentifier("perception", OTAReleaseKey.dev)),
            ImageManifest.Descriptor,
        )
        assert {i.ecu_id for i in index.image_identifiers} == {"autoware", "perception"}

    def test_an_entry_without_artifact_type_is_the_file_based_payloads(
        self, resource_dir
    ):
        # The two kinds share a mediaType; older indexes name only the file-based one.
        image_root = build_image(resource_dir, with_file_based=True)
        raw = json.loads((image_root / IMAGE_INDEX_FNAME).read_text())
        for entry in raw["manifests"]:
            entry.pop("artifactType", None)
        index = ImageIndex.parse_metafile(json.dumps(raw))
        assert all(
            isinstance(entry, ImageManifest.Descriptor)
            for entry in index.manifests
            if entry.mediaType == IMAGE_MANIFEST
        )
        with pytest.raises(ValidationError, match="artifactType"):
            PartitionImageManifest.Descriptor.model_validate_json(
                json.dumps(raw["manifests"][0])
            )

    def test_one_update_agent_package_per_image(self, resource_dir):
        image_root = build_image(resource_dir)
        index = ImageIndex.parse_metafile((image_root / IMAGE_INDEX_FNAME).read_text())
        package = UpdateAgentPackageManifest.Descriptor(
            size=1, digest=index.manifests[0].digest
        )
        index.add_update_agent_package(package)
        assert index.find_update_agent_package() is package
        with pytest.raises(ValueError, match="already been added"):
            index.add_update_agent_package(package)

    def test_one_identifier_names_one_payload_of_either_kind(self, resource_dir):
        image_root = build_image(resource_dir)
        index = ImageIndex.parse_metafile((image_root / IMAGE_INDEX_FNAME).read_text())
        duplicate = ImageManifest.Descriptor(
            size=1,
            digest=index.manifests[0].digest,
            annotations=ImageManifest.Descriptor.Annotations.model_validate(
                MANIFEST_ANNOTATIONS
            ),
        )
        with pytest.raises(ValueError, match="already been added"):
            index.add_image(duplicate)

    def test_list_image_names_the_kind(self, resource_dir):
        image_root = build_image(resource_dir, with_file_based=True)
        index = ImageIndex.parse_metafile((image_root / IMAGE_INDEX_FNAME).read_text())
        out = _render_output(
            [
                d
                for d in index.manifests
                if isinstance(
                    d, (ImageManifest.Descriptor, PartitionImageManifest.Descriptor)
                )
            ]
        )
        assert "ecu_id='autoware'" in out and "kind='partition-based'" in out
        assert "ecu_id='perception'" in out and "kind='file-based'" in out


class TestArtifactReader:
    def test_select_and_stream_a_partition_based_payload(self, resource_dir, tmp_path):
        image_root = build_image(resource_dir, with_file_based=True)
        artifact = pack(image_root, tmp_path / "artifact.zip")

        with OTAImageArtifactReader(artifact) as reader:
            index = reader.parse_index()
            manifest = reader.select_image_payload(
                ImageIdentifier("autoware", OTAReleaseKey.dev), index
            )
            assert isinstance(manifest, PartitionImageManifest)
            config, sys_config = reader.get_partition_image_config(manifest)
            assert sys_config is None
            assert config.image_version == "1.2.0"

            rootfs = config.partition("rootfs")
            assert rootfs is not None and rootfs.image is not None
            data = b"".join(reader.stream_blob(rootfs.image.digest.digest_hex))
            assert data == ROOTFS_BYTES
            assert sha256(data).hexdigest() == rootfs.image.digest.digest_hex

            boot = config.partition("boot")
            assert boot is not None and boot.image is not None
            with tarfile.open(
                fileobj=io.BytesIO(reader.read_blob(boot.image.digest.digest_hex))
            ) as tar:
                assert sorted(tar.getnames()) == ["grub.cfg", "initrd.img", "vmlinuz"]

            other = reader.select_image_payload(
                ImageIdentifier("perception", OTAReleaseKey.dev), index
            )
            assert isinstance(other, ImageManifest)
            assert (
                reader.select_image_payload(
                    ImageIdentifier("nothing", OTAReleaseKey.dev), index
                )
                is None
            )


class TestFirmware:
    """A firmware package rides in the config for the platform's own updater: the
    bootloader and what boots before any partition image is read. Opaque here; what
    is checked is that it is well described and travels with the payload."""

    @staticmethod
    def firmware_descriptor(
        resource_dir, data: bytes = b"\xca\x05" * 2048, **annotations
    ):
        _f = resource_dir / "TEGRA_BL.Cap"
        _f.write_bytes(data)
        _a = {
            PARTITION_IMAGE_FIRMWARE_FORMAT: "example-updater.capsule.v1",
            **annotations,
        }
        return FirmwarePackageDescriptor.add_file_to_resource_dir(
            _f, resource_dir, annotations=_a
        )

    def entry(self, resource_dir, **overrides):
        _kw = dict(
            name="bsp",
            version="39.2.0",
            format="example-updater.capsule.v1",
            package=self.firmware_descriptor(resource_dir),
        )
        _kw.update(overrides)
        return FirmwareEntry(**_kw)

    def test_an_entry_names_the_package_and_its_format(self, resource_dir):
        _e = self.entry(resource_dir)
        assert _e.package.mediaType == PARTITION_IMAGE_FIRMWARE_PACKAGE
        assert _e.package.format == "example-updater.capsule.v1"
        assert _e.requires == {}

    @pytest.mark.parametrize("name", ["", "a/b", "..", "x" * 65])
    def test_the_name_is_a_directory_name(self, resource_dir, name):
        with pytest.raises(ValidationError, match="invalid firmware name"):
            self.entry(resource_dir, name=name)

    def test_the_format_must_be_the_packages(self, resource_dir):
        with pytest.raises(ValidationError, match="package's annotation says"):
            self.entry(resource_dir, format="another.format")

    def test_the_package_needs_a_format_annotation(self, resource_dir):
        _f = resource_dir / "fw.bin"
        _f.write_bytes(b"\x01" * 64)
        with pytest.raises(ValidationError):
            FirmwarePackageDescriptor.add_file_to_resource_dir(_f, resource_dir)

    def test_it_ships_with_the_payload_and_counts_as_a_blob(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        _fw = self.entry(resource_dir)
        _cfg = direct_config(rootfs_descriptor, boot_descriptor)
        _cfg = _cfg.model_copy(update={"firmware": _fw})
        assert _cfg.payload_descriptors[-1] is _fw.package
        assert len(_cfg.payload_descriptors) == 3
        _round = PartitionImageConfig.model_validate_json(
            _cfg.model_dump_json(by_alias=True)
        )
        assert _round.firmware is not None
        assert _round.firmware.version == "39.2.0"
        assert _round.firmware.package.format == "example-updater.capsule.v1"

    def test_its_name_shares_the_namespace_with_the_data_images(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        _di = TestDataImages().entry(resource_dir, name="bsp")
        _fw = self.entry(resource_dir)
        _doc = direct_config(
            rootfs_descriptor, boot_descriptor, data_images=[_di]
        ).model_dump(by_alias=True)
        _doc["firmware"] = _fw.model_dump(by_alias=True)
        with pytest.raises(ValidationError, match="named like a data image"):
            PartitionImageConfig.model_validate(_doc)


class TestTightenedValidators:
    """What the schema refuses beyond shape: contradictions no agent could apply."""

    def test_an_identity_delta_must_name_the_images_own_size(self, resource_dir):
        rootfs_descriptor, _ = make_blobs(resource_dir)
        with pytest.raises(
            ValidationError, match="source is the image itself but its size"
        ):
            PartitionEntry(
                name="rootfs",
                action=PartitionAction.write,
                image=rootfs_descriptor,
                delta=delta_descriptor(
                    resource_dir,
                    source_digest=rootfs_descriptor.image_digest,
                    source_size=rootfs_descriptor.image_size + 4096,
                ),
            )

    def test_verity_annotations_come_whole_or_not_at_all(self):
        from ota_image_libs.v1.annotation_keys import (
            PARTITION_IMAGE_VERITY_HASH_OFFSET,
            PARTITION_IMAGE_VERITY_ROOT_HASH,
        )
        from ota_image_libs.v1.partition_image.schema import _PartitionImageAnnotations

        ok = _PartitionImageAnnotations.model_validate(
            {
                PARTITION_IMAGE_VERITY_ROOT_HASH: "ab" * 32,
                PARTITION_IMAGE_VERITY_HASH_OFFSET: 4096,
            }
        )
        assert ok.verity_hash_offset == 4096
        with pytest.raises(ValidationError, match="both a root hash and a hash offset"):
            _PartitionImageAnnotations.model_validate(
                {PARTITION_IMAGE_VERITY_ROOT_HASH: "ab" * 32}
            )
        with pytest.raises(ValidationError, match="not a hex digest"):
            _PartitionImageAnnotations.model_validate(
                {
                    PARTITION_IMAGE_VERITY_ROOT_HASH: "zz" * 32,
                    PARTITION_IMAGE_VERITY_HASH_OFFSET: 0,
                }
            )
        with pytest.raises(ValidationError, match="must not be negative"):
            _PartitionImageAnnotations.model_validate(
                {
                    PARTITION_IMAGE_VERITY_ROOT_HASH: "ab" * 32,
                    PARTITION_IMAGE_VERITY_HASH_OFFSET: -1,
                }
            )

    def test_an_empty_version_range_is_refused(self):
        from ota_image_libs.v1.partition_image.schema import VersionRange

        assert VersionRange(min="1.0", max="2.0").allows("1.5")
        with pytest.raises(ValidationError, match="empty version range"):
            VersionRange(min="3.0.0", max="2.0.0")
        with pytest.raises(ValidationError, match="empty version range"):
            VersionRange(min="2.0", max="2.0")

    def test_a_payload_that_does_nothing_is_refused(self, resource_dir):
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        cfg = direct_config(rootfs_descriptor, boot_descriptor)
        kept = [
            PartitionEntry(name=p.name, action=PartitionAction.keep)
            for p in cfg.partitions
        ]
        with pytest.raises(ValidationError, match="nothing to install"):
            cfg.model_copy(update={"partitions": kept}).model_validate(
                cfg.model_copy(update={"partitions": kept}).model_dump(by_alias=True)
            )

    def test_a_data_image_cannot_be_named_after_a_partition_role_or_require_itself(
        self, resource_dir
    ):
        from ota_image_libs.v1.partition_image.schema import (
            DataImageEntry,
            VersionRange,
        )

        img = TestDataImages.data_descriptor(resource_dir)
        with pytest.raises(ValidationError, match="cannot require itself"):
            DataImageEntry(
                name="ml",
                version="1",
                mount="/opt/ml",
                image=img,
                requires={"ml": VersionRange(min="1")},
            )
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        cfg = direct_config(rootfs_descriptor, boot_descriptor)
        entry = DataImageEntry(name="rootfs", version="1", mount="/opt/ml", image=img)
        with pytest.raises(ValidationError, match="is a partition role"):
            PartitionImageConfig.model_validate(
                cfg.model_copy(update={"data_images": [entry]}).model_dump(
                    by_alias=True
                )
            )


class TestFirmwareCompressed:
    """The compressed form of a firmware package: what the updater is handed is the
    decoded bytes, named by the uncompressed annotations like a compressed partition
    image's."""

    def test_the_compressed_descriptor_names_what_it_decodes_to(self, resource_dir):
        from ota_image_libs.v1.annotation_keys import (
            PARTITION_IMAGE_FIRMWARE_FORMAT,
            PARTITION_IMAGE_UNCOMPRESSED_DIGEST,
            PARTITION_IMAGE_UNCOMPRESSED_SIZE,
        )
        from ota_image_libs.v1.media_types import PARTITION_IMAGE_FIRMWARE_PACKAGE_ZSTD
        from ota_image_libs.v1.partition_image.schema import (
            FirmwarePackageZstdDescriptor,
        )

        _f = resource_dir / "TEGRA_BL.Cap.zst"
        _f.write_bytes(b"\x28\xb5\x2f\xfd" + b"\x00" * 60)
        _d = FirmwarePackageZstdDescriptor.add_file_to_resource_dir(
            _f,
            resource_dir,
            annotations={
                PARTITION_IMAGE_FIRMWARE_FORMAT: "example-updater.capsule.v1",
                PARTITION_IMAGE_UNCOMPRESSED_DIGEST: "sha256:" + "ab" * 32,
                PARTITION_IMAGE_UNCOMPRESSED_SIZE: 4096,
            },
        )
        assert _d.mediaType == PARTITION_IMAGE_FIRMWARE_PACKAGE_ZSTD
        assert _d.image_digest == "sha256:" + "ab" * 32 and _d.image_size == 4096
        assert _d.format == "example-updater.capsule.v1"
        with pytest.raises(ValidationError):
            FirmwarePackageZstdDescriptor.add_file_to_resource_dir(
                _f, resource_dir, annotations={PARTITION_IMAGE_FIRMWARE_FORMAT: "x"}
            )
        _e = FirmwareEntry(
            name="bsp",
            version="39.2.1",
            format="example-updater.capsule.v1",
            package=_d,
        )
        rootfs_descriptor, boot_descriptor = make_blobs(resource_dir)
        _cfg = direct_config(rootfs_descriptor, boot_descriptor)
        _cfg = _cfg.model_copy(update={"firmware": _e})
        # listed after the partitions and the data images, before nothing: the last blob
        assert _cfg.payload_descriptors[-1] is _d
