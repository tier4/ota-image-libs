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

import itertools
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Generator, Optional

import zstandard
from typing_extensions import TypeAlias

from ota_image_libs._resource_filter import BundleFilter, CompressFilter, SliceFilter
from ota_image_libs.common import tmp_fname
from ota_image_libs.common.io import file_sha256, remove_file

from .db import ResourceTableDBHelper, ResourceTableORMPool
from .schema import ResourceTableManifest

# totally a worker thread will wait for 18 seconds
#   for the bundle to be prepared.
MAX_ITERS_FOR_WAITING_BUNDLE = 6  # seconds
WAITING_BUNDLE_INTERVAL = 3


class BundledRecreateFailed(Exception): ...


class SlicedRecreateFailed(Exception): ...


class CompressedRecreateFailed(Exception): ...


class _BundleReadyEventWithRevision:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._flag = False
        self._rev_counter = _counter = itertools.count(0)
        self._rev = next(_counter)

    def is_set(self) -> tuple[bool, int]:
        with self._lock:
            return self._flag, self._rev

    def set(self) -> int:
        with self._lock:
            self._flag = True
            self._rev = next(self._rev_counter)
            return self._rev

    def clear(self, rev: int) -> None:
        with self._lock:
            if rev != self._rev:
                return
            self._flag = False


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


PerBundleLock: TypeAlias = threading.Lock
BundleRecord: TypeAlias = (
    "tuple[ResourceTableManifest, PerBundleLock, _BundleReadyEventWithRevision]"
)


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
        self._bundle_per_locks: dict[int, BundleRecord] = {}

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

    def _prepare_one_bundle(
        self, _bundle_f: Path, _bundle_entry: ResourceTableManifest
    ):
        # try to re-use already prepared bundle file resource
        if (
            _bundle_f.is_file()
            and file_sha256(_bundle_f).digest() == _bundle_entry.digest
        ):
            return

        _bundle_save_tmp = self._download_dir / tmp_fname(
            str(_bundle_entry.resource_id)
        )
        yield from self._prepare_resource(_bundle_entry, _bundle_save_tmp)
        # unconditionally override the previous file
        os.replace(_bundle_save_tmp, _bundle_f)

    def _prepare_bundled_resource(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[ResourceDownloadInfo]:
        filter_cfg = entry.filter_applied
        assert isinstance(filter_cfg, BundleFilter)

        # NOTE: only do one query for each bundle
        bundle_rsid = filter_cfg.list_resource_id()
        with self._bundle_process_lock:
            if not (_bundle_info := self._bundle_per_locks.get(bundle_rsid)):
                _bundle_entry = self._orm_pool.orm_select_entry(resource_id=bundle_rsid)
                self._bundle_per_locks[bundle_rsid] = (
                    _bundle_entry,
                    _bundle_prepare_lock := PerBundleLock(),
                    _bundle_ready_event := _BundleReadyEventWithRevision(),
                )
            else:
                _bundle_entry, _bundle_prepare_lock, _bundle_ready_event = _bundle_info

        _bundle_f = self._download_dir / _bundle_entry.digest.hex()
        # Only trigger upper to download resources when _bundle_ready_event is not set.
        # To prevent other waiting threads just deadly waiting if the thread that does
        #   the downloading failed and raised exception, other waiting threads will also
        #   keep trying to get the _bundle_prepare_lock and prepare bundle.
        for _ in range(MAX_ITERS_FOR_WAITING_BUNDLE):
            _is_set, bundle_rev = _bundle_ready_event.is_set()
            if _is_set:
                break

            if _bundle_prepare_lock.acquire(blocking=False):
                try:
                    yield from self._prepare_one_bundle(_bundle_f, _bundle_entry)
                    bundle_rev = _bundle_ready_event.set()
                    break
                except Exception as e:
                    raise BundledRecreateFailed(
                        f"failed to prepare bundle {_bundle_entry}: {e!r}"
                    ) from e
                finally:
                    _bundle_prepare_lock.release()
            time.sleep(WAITING_BUNDLE_INTERVAL)
        else:
            raise BundledRecreateFailed(
                f"timeout waiting for bundle {_bundle_entry=} ready, will retry"
            )

        # NOTE: keep the bundle for later use, but if recreate from bundle failed,
        #       we clear the _bundle_ready_event and raise exception to upper to
        #       trigger a re-downloading of the resources.
        try:
            with open(_bundle_f, "rb") as src, open(save_dst, "wb") as dst:
                src.seek(filter_cfg.offset)
                dst.write(src.read(filter_cfg.len))
        except Exception as e:
            _bundle_ready_event.clear(bundle_rev)
            raise BundledRecreateFailed(
                f"failed to extract {entry} from bundle {_bundle_entry}: {e!r}"
            ) from e

    def _prepare_compressed_resources(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[ResourceDownloadInfo]:
        _filter_applied = entry.filter_applied
        assert isinstance(_filter_applied, CompressFilter)

        compressed_rsid = _filter_applied.list_resource_id()
        compressed_entry = self._orm_pool.orm_select_entry(resource_id=compressed_rsid)
        compressed_digest = compressed_entry.digest

        # NOTE(20250917): if the compressed entry is not sliced, we directly tell the upper
        #                 caller to decompress on-the-fly during downloading.
        if compressed_entry.filter_applied is None:
            yield ResourceDownloadInfo(
                digest=compressed_digest,
                size=compressed_entry.size,
                save_dst=save_dst,
                compression_alg=_filter_applied.compression_alg,
                compressed_origin_digest=entry.digest,
                compressed_origin_size=entry.size,
            )
            return

        # if the compressed entry is sliced, we still need to first recover from slices
        compressed_save_dst = self._download_dir / compressed_digest.hex()
        if (
            not compressed_save_dst.is_file()
            or file_sha256(compressed_save_dst).digest() != compressed_digest
        ):
            _compressed_save_tmp = self._download_dir / tmp_fname(str(compressed_rsid))
            yield from self._prepare_resource(compressed_entry, _compressed_save_tmp)
            os.replace(_compressed_save_tmp, compressed_save_dst)

        try:
            recreate_zstd_compressed_resource(
                entry,
                compressed_save_dst,
                save_dst,
                dctx=self._thread_local_dctx,
            )
        except Exception as e:
            _err_msg = f"failure during decompressing: {entry}: {e}"
            raise CompressedRecreateFailed(_err_msg) from e
        finally:
            compressed_save_dst.unlink(missing_ok=True)

    def _prepare_one_slice(
        self, slice_save_dst: Path, slice_entry: ResourceTableManifest
    ):
        # try to re-use previously prepared slice
        if (
            slice_save_dst.is_file()
            and file_sha256(slice_save_dst).digest() == slice_entry.digest
        ):
            return

        _slice_save_tmp = self._download_dir / tmp_fname(str(slice_entry.resource_id))
        yield ResourceDownloadInfo(
            digest=slice_entry.digest,
            size=slice_entry.size,
            save_dst=_slice_save_tmp,
        )
        os.replace(_slice_save_tmp, slice_save_dst)

    def _prepare_sliced_resources(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[ResourceDownloadInfo]:
        assert isinstance(entry.filter_applied, SliceFilter)
        slices_rsid = entry.filter_applied.list_resource_id()
        slices_fpaths: list[Path] = []
        for _slice_rsid in slices_rsid:
            _slice_entry = self._orm_pool.orm_select_entry(resource_id=_slice_rsid)
            # NOTE: slice SHOULD NOT be filtered again, it MUST be the leaves in the resource
            #       filter applying tree.
            assert _slice_entry.filter_applied is None

            # NOTE: in case when the slice is shared by multiple resources, we suffix
            #       the resource_id to the fname.
            _slice_save_dst = (
                self._download_dir / f"{_slice_entry.digest.hex()}_{entry.resource_id}"
            )
            yield from self._prepare_one_slice(_slice_save_dst, _slice_entry)
            slices_fpaths.append(_slice_save_dst)

        try:
            recreate_sliced_resource(entry, slices_fpaths, save_dst)
        except Exception as e:
            _err_msg = (
                f"failed to recreate sliced resource {entry}, remove all slices: {e}"
            )
            raise SlicedRecreateFailed(_err_msg) from e
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


SHA256DIGEST_HEX_LEN = 64


class ResumeOTADownloadHelper:
    def __init__(
        self,
        download_dir: Path,
        rst_helper: ResourceTableDBHelper,
        *,
        max_concurrent: int,
        db_conn_num: int = 1,  # serialize accessing
    ) -> None:
        self._download_dir = download_dir
        self._rst_orm_pool = rst_helper.get_orm_pool(db_conn_num)
        self._se = threading.Semaphore(max_concurrent)

    def _check_one_resource_at_thread(
        self,
        _fpath: Path,
        _digest: bytes,
        _sliced_target_rsid: str,
    ) -> None:
        try:
            if _sliced_target_rsid and not self._rst_orm_pool.orm_check_entry_exist(
                resource_id=int(_sliced_target_rsid)
            ):
                return remove_file(_fpath)

            if (
                not self._rst_orm_pool.orm_check_entry_exist(digest=_digest)
                or file_sha256(_fpath).digest() != _digest
            ):
                return remove_file(_fpath)
        except Exception:
            remove_file(_fpath)
        finally:
            self._se.release()

    def check_download_dir(self) -> int:
        """Scan through OTA download dir and try to recover resources."""
        _count = 0
        with ThreadPoolExecutor(
            thread_name_prefix="resume_ota_download"
        ) as pool, os.scandir(self._download_dir) as it:
            for entry in it:
                if (
                    not entry.is_file(follow_symlinks=False)
                    or len(entry.name) < SHA256DIGEST_HEX_LEN
                    or entry.name.startswith("tmp")
                ):
                    remove_file(Path(entry.path))
                    continue

                entry_fname = entry.name
                # NOTE: for slice, a suffix will be appended to the filename.
                _digest_hex = entry_fname[:SHA256DIGEST_HEX_LEN]
                # see L289-L291, a slice will be named as <slice_digest>_<target_resource_id>
                _sliced_target_rsid = entry_fname[SHA256DIGEST_HEX_LEN + 1 :]
                try:
                    _digest = bytes.fromhex(_digest_hex)
                except Exception:
                    remove_file(Path(entry.path))
                    continue

                self._se.acquire()
                _count += 1
                pool.submit(
                    self._check_one_resource_at_thread,
                    Path(entry.path),
                    _digest,
                    _sliced_target_rsid,
                )
        return _count
