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
"""Tests for OTA image artifact reader module."""

import json
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import pytest

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import (
    ImageIdentifier,
    ImageManifest,
    OTAReleaseKey,
)
from ota_image_libs.v1.media_types import IMAGE_INDEX


@pytest.fixture
def reader():
    """Create an OTAImageArtifactReader instance."""
    with OTAImageArtifactReader(
        Path(__file__).parent / "data" / "ota-image.zip"
    ) as reader:
        yield reader


class TestOTAImageArtifactReaderValidation:
    """Tests for image validation."""

    def test_is_valid_image_true(self, reader: OTAImageArtifactReader):
        """Test is_valid_image returns True for valid OTA image."""
        assert reader.is_valid_image() is True

    def test_is_valid_image_false(self, tmp_path: Path):
        """Test is_valid_image returns False for invalid archive."""
        # Create a zip file without index.json
        invalid_zip = tmp_path / "invalid.zip"
        with ZipFile(invalid_zip, mode="w") as zf:
            zf.writestr("dummy.txt", "not an OTA image")

        with OTAImageArtifactReader(invalid_zip) as reader:
            assert reader.is_valid_image() is False


def test_parse_index(reader: OTAImageArtifactReader):
    """Test parsing the image index."""
    index = reader.parse_index()
    assert index.schemaVersion == 2
    assert index.mediaType == IMAGE_INDEX
    assert len(index.manifests) > 0

    jwt_raw = reader.retrieve_jwt_raw()
    # JWT may or may not be present depending on the test image
    if jwt_raw is not None:
        assert isinstance(jwt_raw, str)
        assert len(jwt_raw) > 0


class TestOTAImageArtifactReaderBlobs:
    """Tests for blob operations."""

    def test_open_blob_not_found(self, reader: OTAImageArtifactReader):
        """Test opening a non-existent blob raises FileNotFoundError."""
        fake_digest = "0" * 64
        with pytest.raises(FileNotFoundError, match="blob with sha256_digest"):
            reader.open_blob(fake_digest)

    def test_read_blob(self, reader: OTAImageArtifactReader):
        """Test reading a blob as bytes."""
        index = reader.parse_index()
        manifest_descriptor = index.manifests[0]
        digest = manifest_descriptor.digest.digest_hex

        data = reader.read_blob(digest)
        assert sha256(data).hexdigest() == digest

    def test_read_blob_as_text(self, reader: OTAImageArtifactReader):
        """Test reading a blob as text."""
        index = reader.parse_index()
        manifest_descriptor = index.manifests[0]
        digest = manifest_descriptor.digest.digest_hex

        text = reader.read_blob_as_text(digest)
        assert sha256(text.encode()).hexdigest() == digest

    def test_stream_blob(self, reader: OTAImageArtifactReader):
        """Test streaming a blob with default chunk size."""
        index = reader.parse_index()
        manifest_descriptor = index.manifests[0]
        digest = manifest_descriptor.digest.digest_hex

        data = b"".join(reader.stream_blob(digest))
        assert sha256(data).hexdigest() == digest


class TestOTAImageArtifactReaderImagePayload:
    """Tests for image payload selection."""

    def test_select_image_payload(self, reader: OTAImageArtifactReader):
        """Test selecting an image payload."""
        index = reader.parse_index()

        # Get the first manifest's image identifier
        first_manifest_descriptor = index.manifests[0]
        first_manifest = ImageManifest.parse_metafile(
            reader.read_blob_as_text(first_manifest_descriptor.digest.digest_hex)
        )
        image_id = first_manifest.image_identifier

        # Select the payload
        manifest = reader.select_image_payload(image_id, index)
        assert manifest is not None
        assert manifest.image_identifier == image_id

    def test_select_image_payload_not_found(self, reader: OTAImageArtifactReader):
        """Test selecting a non-existent image payload returns None."""
        index = reader.parse_index()
        fake_id = ImageIdentifier("nonexistent_ecu", OTAReleaseKey.dev)

        manifest = reader.select_image_payload(fake_id, index)
        assert manifest is None


def test_get_image_config(reader: OTAImageArtifactReader):
    """Test getting image configuration."""
    index = reader.parse_index()
    manifest_descriptor = index.manifests[0]
    manifest = ImageManifest.parse_metafile(
        reader.read_blob_as_text(manifest_descriptor.digest.digest_hex)
    )
    reader.get_image_config(manifest)


class TestOTAImageArtifactReaderTables:
    """Tests for file table and resource table operations."""

    def test_get_file_table(self, reader: OTAImageArtifactReader, tmp_path: Path):
        """Test extracting file table."""
        index = reader.parse_index()
        manifest_descriptor = index.manifests[0]
        manifest = ImageManifest.parse_metafile(
            reader.read_blob_as_text(manifest_descriptor.digest.digest_hex)
        )
        image_config, _ = reader.get_image_config(manifest)

        save_dst = tmp_path / "file_table.db"
        result = reader.get_file_table(image_config, save_dst)

        assert result.exists()
        assert result.stat().st_size > 0

    def test_get_resource_table(self, reader: OTAImageArtifactReader, tmp_path: Path):
        """Test extracting resource table."""
        index = reader.parse_index()

        save_dst = tmp_path / "resource_table.db"
        result = reader.get_resource_table(index, save_dst)

        assert result.exists()
        assert result.stat().st_size > 0

    def test_get_resource_table_not_found(self, tmp_path: Path):
        """Test get_resource_table raises ValueError when table is missing."""
        # Create a minimal index without resource table
        invalid_zip = tmp_path / "no_resource_table.zip"
        with ZipFile(invalid_zip, mode="w") as zf:
            # Create a minimal index without resource_table
            minimal_index = {
                "schemaVersion": 2,
                "mediaType": "application/vnd.oci.image.index.v1+json",
                "manifests": [],
                "annotations": {
                    "vnd.tier4.ota.ota-image-builder.version": "test-1.0.0"
                },
            }
            zf.writestr("index.json", json.dumps(minimal_index))

        with OTAImageArtifactReader(invalid_zip) as reader:
            index = reader.parse_index()
            save_dst = tmp_path / "resource_table.db"
            with pytest.raises(ValueError, match="invalid OTA image"):
                reader.get_resource_table(index, save_dst)


class TestOTAImageArtifactReaderIntegration:
    """Integration tests using the full workflow."""

    def test_complete_workflow(self, reader: OTAImageArtifactReader, tmp_path: Path):
        """Test complete workflow from index to extracting tables."""
        index = reader.parse_index()
        assert index is not None

        first_manifest_descriptor = index.manifests[0]
        first_manifest = ImageManifest.parse_metafile(
            reader.read_blob_as_text(first_manifest_descriptor.digest.digest_hex)
        )
        image_id = first_manifest.image_identifier

        manifest = reader.select_image_payload(image_id, index)
        assert manifest is not None

        image_config, _ = reader.get_image_config(manifest)
        assert image_config is not None

        file_table_path = tmp_path / "file_table.db"
        result_ft = reader.get_file_table(image_config, file_table_path)
        assert result_ft.exists()

        resource_table_path = tmp_path / "resource_table.db"
        result_rt = reader.get_resource_table(index, resource_table_path)
        assert result_rt.exists()

    def test_multiple_image_payloads(self, reader: OTAImageArtifactReader):
        """Test handling multiple image payloads if present."""
        index = reader.parse_index()
        for manifest_descriptor in index.manifests:
            if isinstance(manifest_descriptor, ImageManifest.Descriptor):
                manifest = ImageManifest.parse_metafile(
                    reader.read_blob_as_text(manifest_descriptor.digest.digest_hex)
                )

                image_id = manifest.image_identifier
                manifest = reader.select_image_payload(image_id, index)
                assert manifest is not None
                assert manifest.image_identifier == image_id
