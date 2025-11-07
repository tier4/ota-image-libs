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
"""Test database utilities."""

from ota_image_libs.common.db_utils import count_blobs_in_dir


class TestDBUtils:
    """Test database utility functions."""

    def test_count_blobs_in_empty_dir(self, tmp_path):
        """Test counting blobs in an empty directory."""
        count, size = count_blobs_in_dir(tmp_path)
        assert count == 0
        assert size == 0

    def test_count_blobs_in_dir_with_multiple_files(self, tmp_path):
        """Test counting multiple blobs."""
        # Create multiple test files
        for i in range(5):
            (tmp_path / f"blob{i}.dat").write_bytes(b"x" * (i + 1) * 100)

        count, size = count_blobs_in_dir(tmp_path)

        assert count == 5
        assert size == sum((i + 1) * 100 for i in range(5))
