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

import itertools
from typing import ClassVar

import pytest
import zstandard

from ota_image_libs.common.oci_spec import OCIDescriptor, Sha256Digest


class TestSha256Digest:
    def test_sha256_digest_from_hex_string(self):
        """Test creating Sha256Digest from hex string."""
        test_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        digest = Sha256Digest(test_hash)

        assert digest.digest_hex == test_hash
        assert digest.digest == bytes.fromhex(test_hash)

    def test_sha256_digest_from_bytes(self):
        """Test creating Sha256Digest from bytes."""
        test_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        test_bytes = bytes.fromhex(test_hash)
        digest = Sha256Digest(test_bytes)

        assert digest.digest == test_bytes
        assert digest.digest_hex == test_hash

    def test_sha256_digest_hash(self):
        """Test Sha256Digest.__hash__."""
        test_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        digest1 = Sha256Digest(test_hash)
        digest2 = Sha256Digest(test_hash)

        assert hash(digest1) == hash(digest2)
        # Can be used in sets/dicts
        assert len({digest1, digest2}) == 1

    def test_sha256_digest_equality(self):
        """Test Sha256Digest.__eq__."""
        test_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        digest1 = Sha256Digest(test_hash)
        digest2 = Sha256Digest(bytes.fromhex(test_hash))

        assert digest1 == digest2

    def test_sha256_digest_inequality(self):
        """Test Sha256Digest inequality."""
        digest1 = Sha256Digest("aaabbb")
        digest2 = Sha256Digest("cccddd")

        assert digest1 != digest2
        assert digest1 != "not a digest"

    def test_sha256_digest_str_serialization(self):
        """Test Sha256Digest string serialization."""
        test_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        digest = Sha256Digest(test_hash)

        assert str(digest) == f"sha256:{test_hash}"
        assert repr(digest) == f"sha256:{test_hash}"

    def test_sha256_digest_from_str_validator(self):
        """Test Sha256Digest._from_str_validator."""
        test_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        digest_str = f"sha256:{test_hash}"

        result = Sha256Digest._from_str_validator(digest_str)

        assert isinstance(result, Sha256Digest)
        assert result.digest_hex == test_hash

    def test_sha256_digest_from_str_validator_with_instance(self):
        """Test _from_str_validator with existing instance."""
        digest = Sha256Digest("abcdef")

        result = Sha256Digest._from_str_validator(digest)

        assert result is digest

    def test_sha256_digest_from_str_validator_invalid_type(self):
        """Test _from_str_validator with invalid type."""
        with pytest.raises(ValueError):
            Sha256Digest._from_str_validator(123)

    def test_sha256_digest_from_str_validator_wrong_algorithm(self):
        """Test _from_str_validator with wrong algorithm."""
        with pytest.raises(AssertionError, match="Not a sha256 digest"):
            Sha256Digest._from_str_validator("md5:abc123")


class ConcreteOCIDescriptor(OCIDescriptor):
    """Concrete implementation for testing."""

    MediaType: ClassVar[str] = "application/vnd.oci.image.manifest.v1+json"
    ArtifactType: ClassVar[str] = "application/vnd.oci.image.config.v1+json"


class TestOCIDescriptor:
    def test_oci_descriptor_basic(self):
        """Test basic OCIDescriptor creation."""
        digest = Sha256Digest("abc123")
        descriptor = ConcreteOCIDescriptor(size=100, digest=digest)

        assert descriptor.size == 100
        assert descriptor.digest == digest
        assert descriptor.mediaType == "application/vnd.oci.image.manifest.v1+json"
        assert descriptor.artifactType == "application/vnd.oci.image.config.v1+json"

    def test_oci_descriptor_without_annotations(self):
        """Test OCIDescriptor without annotations."""
        digest = Sha256Digest("abc123")
        descriptor = ConcreteOCIDescriptor(size=100, digest=digest)

        assert descriptor.annotations is None

    def test_oci_descriptor_add_contents_to_resource_dir(self, tmp_path):
        """Test adding string contents to resource directory."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        contents = "test content"
        descriptor = ConcreteOCIDescriptor.add_contents_to_resource_dir(
            contents, resource_dir
        )

        assert descriptor.size == len(contents.encode("utf-8"))
        assert descriptor.digest is not None
        # Verify blob was created
        blob_path = resource_dir / descriptor.digest.digest_hex
        assert blob_path.exists()
        assert blob_path.read_bytes() == contents.encode("utf-8")

    def test_oci_descriptor_add_bytes_to_resource_dir(self, tmp_path):
        """Test adding bytes contents to resource directory."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        contents = b"test binary content"
        descriptor = ConcreteOCIDescriptor.add_contents_to_resource_dir(
            contents, resource_dir
        )

        assert descriptor.size == len(contents)
        blob_path = resource_dir / descriptor.digest.digest_hex
        assert blob_path.read_bytes() == contents

    def test_oci_descriptor_add_file_to_resource_dir(self, tmp_path):
        """Test adding file to resource directory."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()
        src_file = tmp_path / "test.txt"
        src_file.write_text("test file content")

        descriptor = ConcreteOCIDescriptor.add_file_to_resource_dir(
            src_file, resource_dir
        )

        assert descriptor.size > 0
        # Verify blob was created
        blob_path = resource_dir / descriptor.digest.digest_hex
        assert blob_path.exists()
        # Original file should still exist (remove_origin=False by default)
        assert src_file.exists()

    def test_oci_descriptor_add_file_remove_origin(self, tmp_path):
        """Test adding file with remove_origin=True."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()
        src_file = tmp_path / "test.txt"
        src_file.write_text("test file content")

        descriptor = ConcreteOCIDescriptor.add_file_to_resource_dir(
            src_file, resource_dir, remove_origin=True
        )

        # Original file should be removed
        assert not src_file.exists()
        # Blob should exist
        blob_path = resource_dir / descriptor.digest.digest_hex
        assert blob_path.exists()

    def test_oci_descriptor_get_blob_from_resource_dir(self, tmp_path):
        """Test getting blob from resource directory."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        contents = b"test content"
        descriptor = ConcreteOCIDescriptor.add_contents_to_resource_dir(
            contents, resource_dir
        )

        blob_path = descriptor.get_blob_from_resource_dir(resource_dir)

        assert blob_path.exists()
        assert blob_path.read_bytes() == contents

    def test_oci_descriptor_get_blob_not_found(self, tmp_path):
        """Test getting non-existent blob raises error."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        digest = Sha256Digest("0" * 64)  # Valid hex string
        descriptor = ConcreteOCIDescriptor(size=100, digest=digest)

        with pytest.raises(FileNotFoundError, match="not found in OTA image"):
            descriptor.get_blob_from_resource_dir(resource_dir)

    def test_oci_descriptor_retrieve_blob_contents(self, tmp_path):
        """Test retrieving blob contents."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        contents = b"test content"
        descriptor = ConcreteOCIDescriptor.add_contents_to_resource_dir(
            contents, resource_dir
        )

        retrieved = descriptor.retrieve_blob_contents_from_resource_dir(resource_dir)

        assert retrieved == contents

    def test_oci_descriptor_export_blob(self, tmp_path):
        """Test exporting blob to a destination."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()
        export_dir = tmp_path / "export"
        export_dir.mkdir()

        contents = b"test content"
        descriptor = ConcreteOCIDescriptor.add_contents_to_resource_dir(
            contents, resource_dir
        )

        export_path = export_dir / "exported.txt"
        result = descriptor.export_blob_from_resource_dir(resource_dir, export_path)

        assert result == export_path
        assert export_path.exists()
        assert export_path.read_bytes() == contents

    def test_oci_descriptor_remove_blob(self, tmp_path):
        """Test removing blob from resource directory."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        contents = b"test content"
        descriptor = ConcreteOCIDescriptor.add_contents_to_resource_dir(
            contents, resource_dir
        )

        blob_path = resource_dir / descriptor.digest.digest_hex
        assert blob_path.exists()

        descriptor.remove_blob_from_resource_dir(resource_dir)

        assert not blob_path.exists()


class ZstdOCIDescriptor(OCIDescriptor):
    """OCIDescriptor with zstd compression support."""

    MediaType: ClassVar[str] = "application/vnd.oci.image.layer.v1.tar+zstd"


class TestOCIDescriptorZstd:
    @pytest.mark.parametrize(
        "auto_decompress, compress_level",
        tuple(
            itertools.product(
                (True, False),
                (
                    6,
                    zstandard.ZstdCompressor(level=6),
                    zstandard.ZstdCompressor(level=6, write_checksum=True),
                ),
            )
        ),
    )
    def test_add_file_with_zstd_custom_compressor(
        self, tmp_path, auto_decompress: bool, compress_level
    ):
        """Test adding file with zstd compression, with custom compressor."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()
        src_file = tmp_path / "test.txt"
        test_content = b"test content " * 100  # Repeatable content compresses well
        src_file.write_bytes(test_content)

        descriptor = ZstdOCIDescriptor.add_file_to_resource_dir(
            src_file,
            resource_dir,
            zstd_compression_level=compress_level,
        )

        # Compressed size should be smaller than original
        assert descriptor.size < len(test_content)

        # Verify blob
        export_path = tmp_path / "exported.txt"
        descriptor.export_blob_from_resource_dir(
            resource_dir, export_path, auto_decompress=auto_decompress
        )
        if auto_decompress:
            # Decompressed content should match original
            assert export_path.read_bytes() == test_content
        else:
            assert zstandard.decompress(export_path.read_bytes()) == test_content
