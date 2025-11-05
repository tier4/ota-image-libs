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

"""Tests for resource_table utils module."""

import zstandard

from ota_image_libs._resource_filter import CompressFilter, SliceFilter
from ota_image_libs.v1.resource_table.schema import ResourceTableManifest
from ota_image_libs.v1.resource_table.utils import (
    recreate_sliced_resource,
    recreate_zstd_compressed_resource,
)


class TestRecreateSlicedResource:
    def test_recreate_sliced_resource_single_slice(self, temp_dir):
        """Test recreating resource from a single slice."""
        # Create test slices
        slice1 = temp_dir / "slice1.bin"
        slice1.write_bytes(b"Hello, World!")

        # Create entry with slice filter
        entry = ResourceTableManifest(
            resource_id=1,
            digest=b"sha256:" + b"0" * 64,
            size=13,
            filter_applied=SliceFilter(slices=[100]),  # resource_id 100 for slice
        )

        save_dst = temp_dir / "output.bin"

        recreate_sliced_resource(entry, [slice1], save_dst)

        assert save_dst.exists()
        assert save_dst.read_bytes() == b"Hello, World!"

    def test_recreate_sliced_resource_multiple_slices(self, temp_dir):
        """Test recreating resource from multiple slices."""
        # Create test slices
        slice1 = temp_dir / "slice1.bin"
        slice1.write_bytes(b"Part 1 ")

        slice2 = temp_dir / "slice2.bin"
        slice2.write_bytes(b"Part 2 ")

        slice3 = temp_dir / "slice3.bin"
        slice3.write_bytes(b"Part 3")

        # Create entry with slice filter
        entry = ResourceTableManifest(
            resource_id=2,
            digest=b"sha256:" + b"1" * 64,
            size=21,
            filter_applied=SliceFilter(slices=[101, 102, 103]),  # 3 slice resource_ids
        )

        save_dst = temp_dir / "output.bin"

        recreate_sliced_resource(entry, [slice1, slice2, slice3], save_dst)

        assert save_dst.exists()
        assert save_dst.read_bytes() == b"Part 1 Part 2 Part 3"


class TestRecreateZstdCompressedResource:
    def test_recreate_zstd_compressed_resource(self, temp_dir):
        """Test recreating resource from zstd compressed file."""
        # Create original data
        original_data = b"This is test data for zstd compression. " * 10

        # Compress the data
        compressed_file = temp_dir / "compressed.zst"
        cctx = zstandard.ZstdCompressor()
        compressed_data = cctx.compress(original_data)
        compressed_file.write_bytes(compressed_data)

        # Create entry with compress filter
        entry = ResourceTableManifest(
            resource_id=3,
            digest=b"sha256:" + b"2" * 64,
            size=len(original_data),
            filter_applied=CompressFilter(
                resource_id=200,  # compressed resource id
                compression_alg="zstd",
            ),
        )

        save_dst = temp_dir / "output.bin"
        dctx = zstandard.ZstdDecompressor()

        recreate_zstd_compressed_resource(entry, compressed_file, save_dst, dctx)

        assert save_dst.exists()
        assert save_dst.read_bytes() == original_data

    def test_recreate_zstd_compressed_resource_large_file(self, temp_dir):
        """Test recreating resource from large zstd compressed file."""
        # Create larger original data
        original_data = b"Large test data. " * 1000  # ~17KB

        # Compress the data
        compressed_file = temp_dir / "compressed_large.zst"
        cctx = zstandard.ZstdCompressor()
        compressed_data = cctx.compress(original_data)
        compressed_file.write_bytes(compressed_data)

        # Create entry
        entry = ResourceTableManifest(
            resource_id=4,
            digest=b"sha256:" + b"3" * 64,
            size=len(original_data),
            filter_applied=CompressFilter(
                resource_id=201,  # compressed resource id
                compression_alg="zstd",
            ),
        )

        save_dst = temp_dir / "output_large.bin"
        dctx = zstandard.ZstdDecompressor()

        recreate_zstd_compressed_resource(entry, compressed_file, save_dst, dctx)

        assert save_dst.exists()
        assert save_dst.read_bytes() == original_data
