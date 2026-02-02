# Copyright 2022 TIER IV, INC. All rights reserved.
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
"""Core implementation of OTA image artifact."""

from __future__ import annotations

import os
import shutil
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import zstandard

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.file_table import FILE_TABLE_FNAME
from ota_image_libs.v1.file_table.db import FileTableDBHelper, RegularFileRow
from ota_image_libs.v1.file_table.utils import (
    prepare_dir,
    prepare_non_regular,
    prepare_regular_copy,
    prepare_regular_hardlink,
    prepare_regular_inlined,
)
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier
from ota_image_libs.v1.resource_table import RESOURCE_TABLE_FNAME
from ota_image_libs.v1.resource_table.db import ResourceTableDBHelper
from ota_image_libs.v1.resource_table.utils import PrepareResourceHelper
from ota_image_tools._utils import exit_with_err_msg

IMAGE_MANIFEST_SAVE_FNAME = "image_manifest.json"
IMAGE_CONFIG_SAVE_FNAME = "image_config.json"
SYS_CONFIG_SAVE_FNAME = "sys_config.json"

WORKERS_NUM = min(8, (os.cpu_count() or 1) + 4)
CONCURRENT_JOBS = 1024
READ_SIZE = 1 * 1024**2  # 1MiB


class SetupWorkDirFailed(Exception): ...


class DeployResourcesFailed(Exception): ...


class SetupRootfsFailed(Exception): ...


class OTAImageDeployerSetup:
    """Prepare the workdir for deploying the OTA image artifact."""

    def __init__(
        self, _image_id: ImageIdentifier, *, artifact: Path, workdir: Path
    ) -> None:
        self._image_id = _image_id
        self.artifact = artifact
        self.workdir = workdir

        self._ft_db = workdir / FILE_TABLE_FNAME
        self._rst_db = workdir / RESOURCE_TABLE_FNAME

        try:
            # Prepare workdir with all necessary metadata files extracted from the OTA image artifact
            with OTAImageArtifactReader(self.artifact) as artifact_reader:
                self.image_index = _image_index = artifact_reader.parse_index()

                rst_descriptor = _image_index.image_resource_table
                if not rst_descriptor:
                    exit_with_err_msg("invalid OTA image: resource_table not found!")
                with artifact_reader.open_blob(
                    rst_descriptor.digest.digest_hex
                ) as _blob_fp:
                    rst_descriptor.export_blob_from_bytes_stream(
                        _blob_fp, self._rst_db, auto_decompress=True
                    )
                    self._rst_db_helper = ResourceTableDBHelper(self._rst_db)

                self.image_manifest = _image_manifest = (
                    artifact_reader.select_image_payload(self._image_id, _image_index)
                )
                if not _image_manifest:
                    exit_with_err_msg(
                        f"image payload specified by {self._image_id} not found!"
                    )

                self.image_config, self.sys_config = artifact_reader.get_image_config(
                    _image_manifest
                )

                ft_descriptor = _image_manifest.image_file_table
                with artifact_reader.open_blob(
                    ft_descriptor.digest.digest_hex
                ) as _blob_fp:
                    ft_descriptor.export_blob_from_bytes_stream(
                        _blob_fp, self._ft_db, auto_decompress=True
                    )
                    self._ft_db_helper = FileTableDBHelper(self._ft_db)
        except Exception as e:
            raise SetupWorkDirFailed(
                f"failed to setup workdir for OTA image deploy: {e!r}"
            ) from e

    def open_artifact(self) -> OTAImageArtifactReader:
        return OTAImageArtifactReader(self.artifact)


class ResourcesDeployer:
    """Deploy the OTA image resources to the `resource_dir`, for later `RootfsDeployer` use."""

    def __init__(
        self,
        *,
        workdir_setup: OTAImageDeployerSetup,
        resource_dir: Path,
        tmp_dir: Path,
        rst_db_conn: int = 3,
        workers_num: int,
        concurrent_jobs: int,
        read_size: int,
    ) -> None:
        self._read_size = read_size
        self._workers_num = workers_num

        self._workdir_setup = workdir_setup
        self._concurrent_se = threading.Semaphore(concurrent_jobs)
        self._worker_finalize_barrier = threading.Barrier(workers_num)

        self._last_exc = None

        # NOTE: this helper is capable for used in multi-thread environment
        self._rst_helper = PrepareResourceHelper(
            workdir_setup._rst_db_helper.get_orm_pool(db_conn_num=rst_db_conn),
            resource_dir=resource_dir,
            download_tmp_dir=tmp_dir,
        )
        self._thread_local = threading.local()

    def _thread_initializer(self) -> None:
        _thread_local = self._thread_local
        _thread_local.dctx = zstandard.ZstdDecompressor()
        _thread_local.artifact_reader = self._workdir_setup.open_artifact()

    def _thread_worker_finalizer(self) -> None:
        _thread_local = self._thread_local
        artifact_reader: OTAImageArtifactReader = _thread_local.artifact_reader
        artifact_reader.close()
        self._worker_finalize_barrier.wait()  # wait for all other workers finalized

    def _get_resource_zstd_decompress(self, _digest: bytes, _dst: Path) -> None:
        """Get a compressed resource from the artifact with decompressing it."""
        dctx: zstandard.ZstdDecompressor = self._thread_local.dctx
        artifact_reader: OTAImageArtifactReader = self._thread_local.artifact_reader
        with artifact_reader.open_blob(_digest.hex()) as _blob, open(
            _dst, "wb"
        ) as _dst_fp:
            dctx.copy_stream(_blob, _dst_fp, read_size=self._read_size)

    def _get_resource(self, _digest: bytes, _dst: Path) -> None:
        """Get a resource from the artifact as it."""
        artifact_reader: OTAImageArtifactReader = self._thread_local.artifact_reader
        with artifact_reader.open_blob(_digest.hex()) as _blob, open(
            _dst, "wb"
        ) as _dst_fp:
            shutil.copyfileobj(_blob, _dst_fp, length=self._read_size)

    def _prepare_one_resource_at_thread(self, _digest: bytes):
        _, _gen = self._rst_helper.prepare_resource_at_thread(_digest)
        for _dl_info in _gen:
            _digest, _save_dst = _dl_info.digest, _dl_info.save_dst
            if _compression_alg := _dl_info.compression_alg:
                if _compression_alg != "zstd":
                    raise SetupRootfsFailed(
                        f"invalid OTA image, detect unknown compression alg: {_compression_alg}"
                    )
                self._get_resource_zstd_decompress(_digest, _save_dst)
            else:
                self._get_resource(_digest, _save_dst)

    def _worker_cb(self, _fut: Future):
        self._concurrent_se.release()
        if _exc := _fut.exception():
            self._last_exc = _exc

    def deploy_resources(self) -> tuple[int, int]:
        ft_helper = self._workdir_setup._ft_db_helper
        with ThreadPoolExecutor(
            max_workers=self._workers_num,
            initializer=self._thread_initializer,
            thread_name_prefix="ota_image_deployer",
        ) as pool:
            count, size = 0, 0
            for _digest, _size in ft_helper.select_all_digests_with_size(
                exclude_inlined=True
            ):
                count += 1
                size += _size

                if self._last_exc:
                    break

                self._concurrent_se.acquire()
                pool.submit(
                    self._prepare_one_resource_at_thread,
                    _digest,
                ).add_done_callback(self._worker_cb)

            # for worker finalizing
            for _ in range(self._workers_num):
                pool.submit(self._thread_worker_finalizer)

        if _exc := self._last_exc:
            raise DeployResourcesFailed(f"failure during processing: {_exc}") from _exc
        return count, size


class RootfsDeployer:
    """
    Mostly copied from otaclient, a stripped version of `UpdateStandbySlot`.
    """

    def __init__(
        self,
        *,
        file_table_db_helper: FileTableDBHelper,
        rootfs_dir: Path,
        resource_dir: Path,
        max_workers: int,
        concurrent_tasks: int,
    ) -> None:
        self._fst_db_helper = file_table_db_helper

        self._rootfs_dir = rootfs_dir
        self._resource_dir = resource_dir

        self.max_workers = max_workers
        self._se = threading.Semaphore(concurrent_tasks)
        self._last_exc = None

        self._hardlink_group_lock = threading.Lock()
        self._hardlink_group: dict[int, Path] = {}

    def _task_done_cb(self, _fut: Future):
        self._se.release()  # release se first
        if _exc := _fut.exception():
            self._last_exc = _exc

    def _process_hardlinked_file_at_thread(
        self, _digest_hex: str, _entry: RegularFileRow, first_to_prepare: bool
    ):
        _inode_id, _entry_size = _entry.inode_id, _entry.size
        _inlined = _entry.contents or _entry_size == 0
        with self._hardlink_group_lock:
            _link_group_head = self._hardlink_group.get(_inode_id)
            if _link_group_head is not None:
                prepare_regular_hardlink(
                    _entry,
                    _rs=_link_group_head,
                    target_mnt=self._rootfs_dir,
                    hardlink_skip_apply_permission=True,
                )
                return

            if _inlined:
                self._hardlink_group[_inode_id] = prepare_regular_inlined(
                    _entry, target_mnt=self._rootfs_dir
                )
                return

            if first_to_prepare:
                self._hardlink_group[_inode_id] = prepare_regular_hardlink(
                    _entry,
                    _rs=self._resource_dir / _digest_hex,
                    target_mnt=self._rootfs_dir,
                )
            else:
                self._hardlink_group[_inode_id] = prepare_regular_copy(
                    _entry,
                    _rs=self._resource_dir / _digest_hex,
                    target_mnt=self._rootfs_dir,
                )

    def _process_normal_file_at_thread(
        self, _digest_hex: str, _entry: RegularFileRow, first_to_prepare: bool
    ):
        _entry_size = _entry.size
        _inlined = _entry.contents or _entry_size == 0
        if _inlined:
            prepare_regular_inlined(_entry, target_mnt=self._rootfs_dir)
            return

        if first_to_prepare:
            prepare_regular_hardlink(
                _entry,
                _rs=self._resource_dir / _digest_hex,
                target_mnt=self._rootfs_dir,
            )
        else:
            prepare_regular_copy(
                _entry,
                _rs=self._resource_dir / _digest_hex,
                target_mnt=self._rootfs_dir,
            )

    def _process_regular_file_entries(self) -> None:
        _first_prepared_digest: set[bytes] = set()
        try:
            with ThreadPoolExecutor(
                max_workers=self.max_workers, thread_name_prefix="ota_update_slot"
            ) as pool:
                for _entry in self._fst_db_helper.iter_regular_entries():
                    if self._last_exc:
                        break
                    self._se.acquire()

                    _digest = _entry.digest
                    _digest_hex = _digest.hex()

                    _first_to_prepare = False
                    if _digest not in _first_prepared_digest:
                        _first_to_prepare = True
                        _first_prepared_digest.add(_digest)

                    _links_count = _entry.links_count
                    if _links_count is not None and _links_count > 1:
                        pool.submit(
                            self._process_hardlinked_file_at_thread,
                            _digest_hex,
                            _entry,
                            _first_to_prepare,
                        ).add_done_callback(self._task_done_cb)
                    else:
                        pool.submit(
                            self._process_normal_file_at_thread,
                            _digest_hex,
                            _entry,
                            _first_to_prepare,
                        ).add_done_callback(self._task_done_cb)
        except Exception as e:
            if _worker_exc := self._last_exc:
                raise SetupRootfsFailed(
                    f"process regular files failed: dispatch interrupted: {e!r}, "
                    f"last workers error: {_worker_exc}"
                ) from _worker_exc
            raise SetupRootfsFailed(
                f"process regular files failed: dispatch interrupted: {e!r}"
            ) from e

        if _exc := self._last_exc:
            raise SetupRootfsFailed(
                f"process regular files failed: last error: {_exc!r}"
            ) from _exc

    def _process_dir_entries(self) -> None:
        for entry in self._fst_db_helper.iter_dir_entries():
            try:
                prepare_dir(entry, target_mnt=self._rootfs_dir)
            except Exception as e:
                raise SetupRootfsFailed(
                    f"process dir failed: failed {entry=}: {e!r}"
                ) from e

    def _process_non_regular_files(self) -> None:
        for entry in self._fst_db_helper.iter_non_regular_entries():
            try:
                prepare_non_regular(entry, target_mnt=self._rootfs_dir)
            except Exception as e:
                raise SetupRootfsFailed(
                    f"process non-regular files failed: failed {entry=}: {e!r}"
                ) from e

    # API

    def setup_rootfs(self) -> None:
        """Setup the `rootfs_dir` with pre-loaded OTA resources.

        Raises:
            SetupRootfsFailed: if any error occurs during the process.
        """
        self._process_dir_entries()
        self._process_non_regular_files()
        self._process_regular_file_entries()
