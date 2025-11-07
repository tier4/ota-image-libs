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

"""Integration tests for otaclient_package utilities."""

import json

from ota_image_libs.v1.otaclient_package.utils import add_otaclient_package


class TestOTAClientPackageUtils:
    def test_add_otaclient_package(self, tmp_path):
        """Test adding otaclient package to OTA image."""
        release_dir = tmp_path / "release"
        release_dir.mkdir()
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        # Create a minimal manifest.json
        manifest_data = {
            "date": "2025-01-15T00:00:00Z",
            "packages": [
                {
                    "type": "squashfs",
                    "filename": "payload1.squashfs",
                    "version": "1.0.0",
                    "architecture": "x86_64",
                    "size": 1024,
                    "checksum": "sha256:" + "0" * 64,
                }
            ],
        }

        manifest_path = release_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        # Create a dummy payload file
        payload_path = release_dir / "payload1.squashfs"
        payload_path.write_bytes(b"dummy squashfs content")

        # Add package
        descriptor = add_otaclient_package(release_dir, resource_dir)

        # Verify descriptor
        assert descriptor is not None
        assert descriptor.mediaType is not None
        assert descriptor.digest is not None
        assert descriptor.size > 0

    def test_add_otaclient_package_multiple_payloads(self, tmp_path):
        """Test adding otaclient package with multiple payloads."""
        release_dir = tmp_path / "release"
        release_dir.mkdir()
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        # Create manifest with multiple packages
        manifest_data = {
            "date": "2025-01-15T00:00:00Z",
            "packages": [
                {
                    "type": "squashfs",
                    "filename": "payload1.squashfs",
                    "version": "1.0.0",
                    "architecture": "x86_64",
                    "size": 1024,
                    "checksum": "sha256:" + "0" * 64,
                },
                {
                    "type": "squashfs",
                    "filename": "payload2.squashfs",
                    "version": "1.0.0",
                    "architecture": "arm64",
                    "size": 2048,
                    "checksum": "sha256:" + "1" * 64,
                },
            ],
        }

        manifest_path = release_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        # Create dummy payload files
        (release_dir / "payload1.squashfs").write_bytes(b"payload1")
        (release_dir / "payload2.squashfs").write_bytes(b"payload2")

        # Add package
        descriptor = add_otaclient_package(release_dir, resource_dir)

        # Verify descriptor
        assert descriptor is not None
        assert descriptor.mediaType is not None
