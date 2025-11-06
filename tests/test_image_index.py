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

"""Integration tests for image_index module."""

import json

import pytest

from ota_image_libs.v1.consts import IMAGE_INDEX_FNAME, RESOURCE_DIR
from ota_image_libs.v1.image_index.schema import ImageIndex
from ota_image_libs.v1.image_index.utils import ImageIndexHelper


@pytest.fixture
def sample_image_index():
    """Create a sample ImageIndex for testing."""
    from ota_image_libs.v1.annotation_keys import BUILD_TOOL_VERSION
    from ota_image_libs.v1.image_index.schema import ImageIndex

    return ImageIndex.model_validate(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [],
            "annotations": {
                BUILD_TOOL_VERSION: "test-1.0.0",
            },
        }
    )


class TestImageIndexHelper:
    def test_init_with_valid_index(self, tmp_path, sample_image_index):
        """Test ImageIndexHelper initialization with valid index."""
        # Create image structure
        index_file = tmp_path / IMAGE_INDEX_FNAME
        index_file.write_text(sample_image_index.export_metafile())

        resource_dir = tmp_path / RESOURCE_DIR
        resource_dir.mkdir(parents=True)

        helper = ImageIndexHelper(tmp_path)

        assert helper.image_index is not None
        assert helper.image_index.schemaVersion == 2

    def test_image_index_property(self, tmp_path, sample_image_index):
        """Test image_index property returns the index."""
        index_file = tmp_path / IMAGE_INDEX_FNAME
        index_file.write_text(sample_image_index.export_metafile())

        helper = ImageIndexHelper(tmp_path)

        assert isinstance(helper.image_index, ImageIndex)

    def test_image_index_json_property(self, tmp_path, sample_image_index):
        """Test image_index_json property returns JSON string."""
        index_file = tmp_path / IMAGE_INDEX_FNAME
        index_file.write_text(sample_image_index.export_metafile())

        helper = ImageIndexHelper(tmp_path)

        json_str = helper.image_index_json
        assert isinstance(json_str, str)
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert "schemaVersion" in parsed

    def test_image_index_fpath_property(self, tmp_path, sample_image_index):
        """Test image_index_fpath property returns correct path."""
        index_file = tmp_path / IMAGE_INDEX_FNAME
        index_file.write_text(sample_image_index.export_metafile())

        helper = ImageIndexHelper(tmp_path)

        assert helper.image_index_fpath == index_file

    def test_image_resource_dir_property(self, tmp_path, sample_image_index):
        """Test image_resource_dir property returns correct path."""
        index_file = tmp_path / IMAGE_INDEX_FNAME
        index_file.write_text(sample_image_index.export_metafile())

        helper = ImageIndexHelper(tmp_path)

        expected_dir = tmp_path / RESOURCE_DIR
        assert helper.image_resource_dir == expected_dir

    def test_sync_index(self, tmp_path, sample_image_index):
        """Test sync_index writes updated index back to file."""
        index_file = tmp_path / IMAGE_INDEX_FNAME
        index_file.write_text(sample_image_index.export_metafile())

        helper = ImageIndexHelper(tmp_path)

        # Modify the index
        helper.image_index.manifests = []

        # Sync to file
        synced_index, descriptor = helper.sync_index()

        assert synced_index is helper.image_index
        assert descriptor.size > 0
        assert descriptor.digest is not None

        # Verify file was updated
        updated_content = index_file.read_text()
        parsed = json.loads(updated_content)
        assert "schemaVersion" in parsed


class TestImageIndexIntegration:
    def test_parse_and_export_roundtrip_with_annotations(self, tmp_path):
        """Test parsing and exporting ImageIndex with annotations maintains data."""
        from ota_image_libs.v1.annotation_keys import (
            BUILD_TOOL_VERSION,
            OTA_IMAGE_CREATED_AT,
        )

        original_data = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [],
            "annotations": {
                BUILD_TOOL_VERSION: "test-1.0.0",
                OTA_IMAGE_CREATED_AT: 1704067200,
            },
        }

        # Parse from JSON
        index = ImageIndex.parse_metafile(json.dumps(original_data))

        # Verify parsed annotations
        assert index.annotations is not None
        assert index.annotations.created_at == 1704067200

        # Export back to JSON
        exported = index.export_metafile()
        parsed_back = json.loads(exported)

        # Verify roundtrip maintains all data
        assert parsed_back["schemaVersion"] == 2
        assert parsed_back["mediaType"] == "application/vnd.oci.image.index.v1+json"
        assert "annotations" in parsed_back
        assert parsed_back["annotations"][BUILD_TOOL_VERSION] == "test-1.0.0"
        assert parsed_back["annotations"][OTA_IMAGE_CREATED_AT] == 1704067200
