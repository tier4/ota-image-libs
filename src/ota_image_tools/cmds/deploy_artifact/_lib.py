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

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from queue import Queue

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
from ota_image_tools._utils import exit_with_err_msg

IMAGE_MANIFEST_SAVE_FNAME = "image_manifest.json"
IMAGE_CONFIG_SAVE_FNAME = "image_config.json"
SYS_CONFIG_SAVE_FNAME = "sys_config.json"

REPORT_BATCH = 30_000

logger = logging.getLogger(__name__)


class WorkdirSetup:
    """Prepare the workdir for deploying the OTA image artifact."""

    def __init__(
        self,
        _image_id: ImageIdentifier,
        *,
        artifact: Path,
        workdir: Path,
        rootfsdir: Path,
    ) -> None:
        self._image_id = _image_id
        self.artifact = artifact
        self.workdir = workdir
        self.rootfsdir = rootfsdir

        self._ft_db = workdir / FILE_TABLE_FNAME
        self._rst_db = workdir / RESOURCE_TABLE_FNAME

        # Prepare workdir with all neccessary metadata files extracted from the OTA image artifact
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
            with artifact_reader.open_blob(ft_descriptor.digest.digest_hex) as _blob_fp:
                ft_descriptor.export_blob_from_bytes_stream(
                    _blob_fp, self._ft_db, auto_decompress=True
                )
                self._ft_db_helper = FileTableDBHelper(self._ft_db)


class SetupRootfsFailed(Exception): ...


class SetupRootfs:
    def __init__(
        self,
        *,
        file_table_db_helper: FileTableDBHelper,
        rootfs_dir: str,
        resource_dir: Path,
        max_workers: int = 5,
        concurrent_tasks: int = 1024,
    ) -> None:
        self._fst_db_helper = file_table_db_helper

        # for process_regular workers
        self._internal_que: Queue[int | None] = Queue()

        self._rootfs_dir = Path(rootfs_dir)
        self._resource_dir = Path(resource_dir)

        self.max_workers = max_workers
        self._se = threading.Semaphore(concurrent_tasks)
        self._interrupted = threading.Event()

        self._hardlink_group_lock = threading.Lock()
        self._hardlink_group: dict[int, Path] = {}

    def _report_uploader_thread(self) -> None:
        """Report uploader worker thread entry."""
        count, size = 0, 0
        while (_processed_size := self._internal_que.get()) is not None:
            count += 1
            size += _processed_size
            if count > 0 and count % REPORT_BATCH == 0:
                logger.info(f"{count} files processed ({size} bytes)")

    def _task_done_cb(self, _fut: Future):
        self._se.release()  # release se first
        if _exc := _fut.exception():
            logger.error(f"failure during processing: {_exc}", exc_info=_exc)
            self._internal_que.put_nowait(None)  # signal the status reporter
            self._interrupted.set()

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
                if not first_to_prepare:
                    self._internal_que.put_nowait(_entry_size)
                return

            if _inlined:
                self._hardlink_group[_inode_id] = prepare_regular_inlined(
                    _entry, target_mnt=self._rootfs_dir
                )
                self._internal_que.put_nowait(_entry_size)
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
                self._internal_que.put_nowait(_entry_size)

    def _process_normal_file_at_thread(
        self, _digest_hex: str, _entry: RegularFileRow, first_to_prepare: bool
    ):
        _entry_size = _entry.size
        _inlined = _entry.contents or _entry_size == 0
        if _inlined:
            prepare_regular_inlined(_entry, target_mnt=self._rootfs_dir)
            self._internal_que.put_nowait(_entry_size)
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
            self._internal_que.put_nowait(_entry_size)

    def _process_regular_file_entries(self) -> None:
        logger.info("process regular file entries ...")
        _first_prepared_digest: set[bytes] = set()

        status_reporter_t = threading.Thread(
            target=self._report_uploader_thread,
            name="update_slot_status_reporter",
            daemon=True,
        )
        status_reporter_t.start()
        try:
            with ThreadPoolExecutor(
                max_workers=self.max_workers, thread_name_prefix="ota_update_slot"
            ) as pool:
                for _entry in self._fst_db_helper.iter_regular_entries():
                    if self._interrupted.is_set():
                        logger.error("detect worker failed, abort!")
                        return
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
        finally:
            # finish up the report
            self._internal_que.put_nowait(None)
            status_reporter_t.join()

    def _process_dir_entries(self) -> None:
        logger.info("start to process directory entries ...")
        for entry in self._fst_db_helper.iter_dir_entries():
            try:
                prepare_dir(entry, target_mnt=self._rootfs_dir)
            except Exception as e:
                logger.exception(f"failed to process {dict(entry)=}: {e!r}")
                raise SetupRootfsFailed(f"failed to process {entry=}: {e!r}") from e

    def _process_non_regular_files(self) -> None:
        logger.info("start to process non-regular entries ...")
        for entry in self._fst_db_helper.iter_non_regular_entries():
            try:
                prepare_non_regular(entry, target_mnt=self._rootfs_dir)
            except Exception as e:
                logger.exception(f"failed to process {dict(entry)=}: {e!r}")
                raise SetupRootfsFailed(f"failed to process {entry=}: {e!r}") from e

    # API

    def setup_rootfs(self) -> None:
        """Setup the `rootfs_dir` with pre-loaded OTA resources.

        Raises:
            SetupRootfsFailed: if any error occurs during the process.
        """
        self._process_dir_entries()
        self._process_non_regular_files()
        self._process_regular_file_entries()

        if self._interrupted.is_set():
            raise SetupRootfsFailed("failure during regular files processing!")
