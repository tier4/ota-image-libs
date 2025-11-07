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

import json

from ota_image_libs.v1.consts import (
    IMAGE_INDEX_FNAME,
    OCI_LAYOUT_CONTENT,
    OCI_LAYOUT_FNAME,
    RESOURCE_DIR,
)
from ota_image_libs.v1.utils import check_if_valid_ota_image


class TestCheckIfValidOTAImage:
    def test_valid_ota_image(self, tmp_path):
        """Test validation of a valid OTA image."""
        # Create valid OTA image structure
        oci_layout_f = tmp_path / OCI_LAYOUT_FNAME
        oci_layout_f.write_text(json.dumps(OCI_LAYOUT_CONTENT))

        index_f = tmp_path / IMAGE_INDEX_FNAME
        index_f.write_text("{}")

        resource_dir = tmp_path / RESOURCE_DIR
        resource_dir.mkdir(parents=True)

        assert check_if_valid_ota_image(tmp_path) is True

    def test_missing_oci_layout(self, tmp_path):
        """Test validation fails when oci-layout is missing."""
        index_f = tmp_path / IMAGE_INDEX_FNAME
        index_f.write_text("{}")

        resource_dir = tmp_path / RESOURCE_DIR
        resource_dir.mkdir(parents=True)

        assert check_if_valid_ota_image(tmp_path) is False

    def test_invalid_oci_layout_content(self, tmp_path):
        """Test validation fails with invalid oci-layout content."""
        oci_layout_f = tmp_path / OCI_LAYOUT_FNAME
        oci_layout_f.write_text('{"imageLayoutVersion": "2.0.0"}')

        index_f = tmp_path / IMAGE_INDEX_FNAME
        index_f.write_text("{}")

        resource_dir = tmp_path / RESOURCE_DIR
        resource_dir.mkdir(parents=True)

        assert check_if_valid_ota_image(tmp_path) is False

    def test_missing_index_file(self, tmp_path):
        """Test validation fails when index.json is missing."""
        oci_layout_f = tmp_path / OCI_LAYOUT_FNAME
        oci_layout_f.write_text(json.dumps(OCI_LAYOUT_CONTENT))

        resource_dir = tmp_path / RESOURCE_DIR
        resource_dir.mkdir(parents=True)

        assert check_if_valid_ota_image(tmp_path) is False

    def test_missing_resource_dir(self, tmp_path):
        """Test validation fails when resource directory is missing."""
        oci_layout_f = tmp_path / OCI_LAYOUT_FNAME
        oci_layout_f.write_text(json.dumps(OCI_LAYOUT_CONTENT))

        index_f = tmp_path / IMAGE_INDEX_FNAME
        index_f.write_text("{}")

        assert check_if_valid_ota_image(tmp_path) is False

    def test_resource_dir_is_file(self, tmp_path):
        """Test validation fails when resource_dir is a file instead of directory."""
        oci_layout_f = tmp_path / OCI_LAYOUT_FNAME
        oci_layout_f.write_text(json.dumps(OCI_LAYOUT_CONTENT))

        index_f = tmp_path / IMAGE_INDEX_FNAME
        index_f.write_text("{}")

        resource_file = tmp_path / RESOURCE_DIR
        resource_file.parent.mkdir(parents=True, exist_ok=True)
        resource_file.write_text("not a directory")

        assert check_if_valid_ota_image(tmp_path) is False
