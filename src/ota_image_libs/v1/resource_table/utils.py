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
"""Helper functions for resource operations."""

from __future__ import annotations

import os
from pathlib import Path

import zstandard

from ota_image_libs._resource_filter import BundleFilter, CompressFilter, SliceFilter
from ota_image_libs.common import tmp_fname

from .schema import ResourceTableManifest


def recreate_bundled_resource(
    entry: ResourceTableManifest, bundle_fpath: Path, save_dst: Path
) -> None:
    filter_cfg = entry.filter_applied
    assert isinstance(filter_cfg, BundleFilter)
    with open(bundle_fpath, "rb") as src, open(save_dst, "wb") as dst:
        src.seek(filter_cfg.offset)
        dst.write(src.read(filter_cfg.len))


def recreate_sliced_resource(
    entry: ResourceTableManifest, slices: list[Path], save_dst: Path
) -> None:
    filter_cfg = entry.filter_applied
    assert isinstance(filter_cfg, SliceFilter)

    tmp_save_dst = save_dst.parent / tmp_fname(str(entry.resource_id))
    with open(tmp_save_dst, "wb") as dst:
        for _slice in slices:
            dst.write(_slice.read_bytes())
    os.replace(tmp_save_dst, save_dst)


def recreate_zstd_compressed_resource(
    entry: ResourceTableManifest,
    compressed: Path,
    save_dst: Path,
    dctx: zstandard.ZstdDecompressor,
) -> None:
    filter_cfg = entry.filter_applied
    assert isinstance(filter_cfg, CompressFilter)
    tmp_save_dst = save_dst.parent / tmp_fname(str(entry.resource_id))

    with open(compressed, "rb") as src, open(tmp_save_dst, "wb") as dst:
        dctx.copy_stream(src, dst)
    os.replace(tmp_save_dst, save_dst)
