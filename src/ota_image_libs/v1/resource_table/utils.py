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

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

import zstandard

from ota_image_libs._resource_filter import BundleFilter, CompressFilter, SliceFilter
from ota_image_libs.common import tmp_fname

from .db import ResourceTableORMPool
from .schema import ResourceTableManifest

logger = logging.getLogger(__name__)


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


@dataclass
class ResourceDownloadInfo:
    digest: bytes
    size: int
    save_dst: Path
    compression_alg: Optional[str] = None
    compressed_origin_digest: Optional[bytes] = None
    compressed_origin_size: Optional[int] = None


class PrepareResourceHelper:
    """Helper for processing resources.

    This class is for multi-threads use.
    """

    def __init__(
        self,
        orm_pool: ResourceTableORMPool,
        *,
        resource_dir: Path,
        download_tmp_dir: Path,
    ):
        self._orm_pool = orm_pool
        self._resource_dir = resource_dir
        self._download_dir = download_tmp_dir

        # for bundled entries, only allow one task to actually rebuild the bundle,
        self._bundle_process_lock = threading.Lock()
        self._bundle: dict[int, Path] = {}

        self._thread_local = threading.local()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._orm_pool.orm_pool_shutdown()
        return False

    @property
    def _thread_local_dctx(self) -> zstandard.ZstdDecompressor:
        # NOTE: should access the thread_local directly by self._thread_local
        try:
            return self._thread_local.dctx
        except AttributeError:
            dctx = zstandard.ZstdDecompressor()
            self._thread_local.dctx = dctx
            return dctx

    def _prepare_bundled_resource(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[ResourceDownloadInfo]:
        assert isinstance(entry.filter_applied, BundleFilter)
        # NOTE: prevent the same bundle being prepared again and again
        bundle_rsid = entry.filter_applied.list_resource_id()
        with self._bundle_process_lock:
            if bundle_rsid not in self._bundle:
                bundle_entry = self._orm_pool.orm_select_entry(resource_id=bundle_rsid)
                logger.debug(f"Requesting bundle({bundle_rsid=}): {bundle_entry}")
                _bundle_save_tmp = self._download_dir / tmp_fname(str(bundle_rsid))
                bundle_save_dst = self._download_dir / bundle_entry.digest.hex()

                yield from self._prepare_resource(bundle_entry, _bundle_save_tmp)
                os.replace(_bundle_save_tmp, bundle_save_dst)
                self._bundle[bundle_rsid] = bundle_save_dst
            bundle_fpath = self._bundle[bundle_rsid]

        # NOTE: keep the bundle for later use, but if recreate from bundle failed, we delete the bundle
        #       to let otaclient do the re-downloading.
        try:
            recreate_bundled_resource(entry, bundle_fpath, save_dst)
        except Exception as e:
            logger.error(
                f"failed to get resource {entry} from bundle: {e}, remove the bundle!",
                exc_info=e,
            )
            bundle_fpath.unlink(missing_ok=True)
            raise

    def _prepare_compressed_resources(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[ResourceDownloadInfo]:
        _filter_applied = entry.filter_applied
        assert isinstance(_filter_applied, CompressFilter)

        compressed_rsid = _filter_applied.list_resource_id()
        compressed_entry = self._orm_pool.orm_select_entry(resource_id=compressed_rsid)

        # NOTE(20250917): if the compressed entry is not sliced, we directly tell the upper
        #                 caller to decompress on-the-fly during downloading.
        if compressed_entry.filter_applied is None:
            yield ResourceDownloadInfo(
                digest=compressed_entry.digest,
                size=compressed_entry.size,
                save_dst=save_dst,
                compression_alg=_filter_applied.compression_alg,
                compressed_origin_digest=entry.digest,
                compressed_origin_size=entry.size,
            )
        # if the compressed entry is sliced, we still need to first recover from slices
        else:
            _compressed_save_tmp = self._download_dir / tmp_fname(str(compressed_rsid))
            compressed_save_dst = self._download_dir / compressed_entry.digest.hex()
            yield from self._prepare_resource(compressed_entry, _compressed_save_tmp)
            os.replace(_compressed_save_tmp, compressed_save_dst)

            try:
                recreate_zstd_compressed_resource(
                    entry, compressed_save_dst, save_dst, dctx=self._thread_local_dctx
                )
            except Exception as e:
                logger.error(f"failure during decompressing: {entry}: {e}", exc_info=e)
                raise
            finally:
                compressed_save_dst.unlink(missing_ok=True)

    def _prepare_sliced_resources(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[ResourceDownloadInfo]:
        assert isinstance(entry.filter_applied, SliceFilter)
        slices_rsid = entry.filter_applied.list_resource_id()
        slices_fpaths: list[Path] = []
        for _slice_rsid in slices_rsid:
            _slice_entry: ResourceTableManifest = self._orm_pool.orm_select_entry(
                resource_id=_slice_rsid
            )
            _slice_digest = _slice_entry.digest.hex()

            _slice_save_tmp = self._download_dir / tmp_fname(str(_slice_rsid))
            # NOTE: in case when the slice is shared by multiple resources, we suffix
            #       the resource_id to the fname.
            _slice_save_dst = (
                self._download_dir / f"{_slice_digest}_{entry.resource_id}"
            )
            slices_fpaths.append(_slice_save_dst)

            # NOTE: slice SHOULD NOT be filtered again, it MUST be the leaves in the resource
            #       filter applying tree.
            assert _slice_entry.filter_applied is None
            yield ResourceDownloadInfo(
                digest=_slice_entry.digest,
                size=_slice_entry.size,
                save_dst=_slice_save_tmp,
            )
            os.replace(_slice_save_tmp, _slice_save_dst)

        try:
            recreate_sliced_resource(entry, slices_fpaths, save_dst)
        except Exception as e:
            logger.error(
                f"failed to recreate sliced resource, remove all slices: {e}",
                exc_info=e,
            )
            raise
        finally:
            # after recovering the target resource, cleanup the slices.
            # also, if combination failed, also cleanup the slices to let
            #   otaclient does the downloading again.
            for _slice in slices_fpaths:
                _slice.unlink(missing_ok=True)

    def _prepare_resource(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[ResourceDownloadInfo]:
        filter_applied = entry.filter_applied
        if filter_applied is None:  # reaching the leaf
            yield ResourceDownloadInfo(
                digest=entry.digest,
                size=entry.size,
                save_dst=save_dst,
            )
        elif isinstance(filter_applied, BundleFilter):
            yield from self._prepare_bundled_resource(entry, save_dst)
        elif isinstance(filter_applied, CompressFilter):
            yield from self._prepare_compressed_resources(entry, save_dst)
        elif isinstance(filter_applied, SliceFilter):
            yield from self._prepare_sliced_resources(entry, save_dst)
        else:
            raise NotImplementedError

    def prepare_resource_at_thread(
        self, digest: bytes
    ) -> tuple[ResourceTableManifest, Generator[ResourceDownloadInfo]]:
        """Prepare resource for the given digest.

        NOTE that the `resource_id` in the resource_table is NOT the same as
            `resource_id` in the file_table!

        This method guides the caller to download all the needed resources to get the
        resource with the given digest. For example, if the resource is a
        compressed archive, it may require the caller to download the archive.

        Raises:
            Raises ValueError when the requested digest is not found in the db.
        """
        target_entry = self._orm_pool.orm_select_entry(digest=digest)
        if target_entry is None:
            raise ValueError(
                f"resource with {digest.hex()} is not found in the rs_table!"
            )

        def _gen():
            # NOTE: only the resource we finally need will be placed to resource dir.
            #       all other intermediates resources will be placed to download tmp.
            yield from self._prepare_resource(
                target_entry, self._resource_dir / digest.hex()
            )

        return target_entry, _gen()
