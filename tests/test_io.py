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

import hashlib

from ota_image_libs.common.io import (
    cal_file_digest,
    file_sha256,
    remove_file,
)


class TestCalFileDigest:
    def test_cal_file_digest_sha256(self, temp_dir):
        """Test file digest calculation with sha256."""
        test_file = temp_dir / "test.txt"
        test_content = b"Hello, World!"
        test_file.write_bytes(test_content)

        result = cal_file_digest(test_file, hashlib.sha256)
        expected = hashlib.sha256(test_content).hexdigest()

        assert result.hexdigest() == expected

    def test_cal_file_digest_empty_file(self, temp_dir):
        """Test digest calculation on empty file."""
        test_file = temp_dir / "empty.txt"
        test_file.write_bytes(b"")

        result = cal_file_digest(test_file, hashlib.sha256)
        expected = hashlib.sha256(b"").hexdigest()

        assert result.hexdigest() == expected


class TestFileSha256:
    def test_file_sha256_basic(self, temp_dir):
        """Test file_sha256 convenience function."""
        test_file = temp_dir / "test.txt"
        test_content = b"Test content for sha256"
        test_file.write_bytes(test_content)

        result = file_sha256(test_file)
        expected = hashlib.sha256(test_content).hexdigest()

        assert result.hexdigest() == expected


class TestRemoveFile:
    def test_remove_file_regular_file(self, temp_dir):
        """Test removing a regular file."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("content")
        assert test_file.exists()

        remove_file(test_file)
        assert not test_file.exists()

    def test_remove_file_directory(self, temp_dir):
        """Test removing a directory."""
        test_dir = temp_dir / "test_dir"
        test_dir.mkdir()
        test_file = test_dir / "file.txt"
        test_file.write_text("content")
        assert test_dir.exists()

        remove_file(test_dir)
        assert not test_dir.exists()
