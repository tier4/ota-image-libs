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
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from ota_image_libs.common import tmp_fname
from ota_image_libs.v1.file_table.db import FileTableDBHelper, RegularFileTypedDict
from ota_image_libs.v1.file_table.utils import (
    fpath_on_target,
    prepare_dir,
    prepare_non_regular,
    prepare_regular_copy,
    prepare_regular_hardlink,
)
from ota_image_libs.v1.image_index.utils import ImageIndexHelper
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier, OTAReleaseKey
from ota_image_libs.v1.resource_table.db import (
    PrepareResourceHelper,
    ResourceTableDBHelper,
)
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg, func_call_with_se

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction

READ_SIZE = 1024**2  # 1MiB
RST_DB_THREADS = 3
TMP_RESOURCE_DIR = ".rs_dir"
"""Temporary resource dir on target folder."""

logger = logging.getLogger(__name__)


def _rebuild_directories(ft_dbhelper: FileTableDBHelper, target_dir: Path):
    for _dir in ft_dbhelper.iter_dir_entries():
        prepare_dir(_dir, target_mnt=target_dir)


def _rebuild_non_regular_files(ft_dbhelper: FileTableDBHelper, target_dir: Path):
    for _entry in ft_dbhelper.iter_non_regular_entries():
        prepare_non_regular(_entry, target_mnt=target_dir)


def _prepare_resource_at_thread(
    digest: bytes,
    *,
    rst_rshelper: PrepareResourceHelper,
    resource_dir: Path,
    tmp_resource_dir: Path,
) -> Path:
    save_dst = tmp_resource_dir / digest.hex()
    _, _gen = rst_rshelper.prepare_resource_at_thread(digest, save_dst)

    for _requested_blob, _tmp_save_dst in _gen:
        # copy the blobs that `prepare_resource` method requires
        shutil.copyfile(resource_dir / _requested_blob, _tmp_save_dst)
    # after all the blobs are prepare, the `prepare_resource` method will
    #   rebuild the requested origin blob
    return save_dst


class RebuildRegularFilesHelper:
    def __init__(
        self,
        *,
        ft_dbf: Path,
        rst_dbf: Path,
        target_dir: Path,
        resource_dir: Path,
        tmp_resource_dir: Path,
        worker_threads: int,
        max_concurrent: int,
    ) -> None:
        self._ft_dbf = ft_dbf
        self._rst_dbf = rst_dbf
        self.target_dir = target_dir
        self.resource_dir = resource_dir
        self.tmp_resource_dir = tmp_resource_dir
        self.worker_threads = worker_threads
        self._se = threading.Semaphore(max_concurrent)

        self._rst_rshelper = PrepareResourceHelper(
            ResourceTableDBHelper(self._rst_dbf).get_orm_pool(RST_DB_THREADS),
            self.tmp_resource_dir,
        )

    def _rebuild_single_file_at_thread(self, _entry: RegularFileTypedDict):
        _target_on_mnt = fpath_on_target(_entry["path"], target_mnt=self.target_dir)
        if (_contents := _entry["contents"]) is None:
            _first_resource = _prepare_resource_at_thread(
                _entry["digest"],
                rst_rshelper=self._rst_rshelper,
                resource_dir=self.resource_dir,
                tmp_resource_dir=self.tmp_resource_dir,
            )
            shutil.move(_first_resource, _target_on_mnt)
        else:
            _target_on_mnt.write_bytes(_contents)

    def _rebuild_digest_files_group_at_thread(
        self, digest: bytes, entries: list[RegularFileTypedDict]
    ) -> None:
        _first_resource = None
        _hardlink_dict: dict[int, Path] = {}  # inode_id, Path

        for _entry in entries:
            _this_links_count = _entry["links_count"]
            _inode_id = _entry["inode_id"]

            if _first_resource is None:
                _contents = _entry["contents"]
                if _contents is None:
                    _first_resource = _prepare_resource_at_thread(
                        digest,
                        rst_rshelper=self._rst_rshelper,
                        resource_dir=self.resource_dir,
                        tmp_resource_dir=self.tmp_resource_dir,
                    )
                else:
                    _first_resource = self.tmp_resource_dir / digest.hex()
                    _first_resource.write_bytes(_contents)

                _fpath_on_target = prepare_regular_hardlink(
                    _entry, _first_resource, target_mnt=self.target_dir
                )
                if _this_links_count is not None and _this_links_count > 1:
                    _hardlink_dict[_inode_id] = Path(_fpath_on_target)
                continue

            assert _first_resource is not None
            if _this_links_count is None or _this_links_count <= 1:
                # No hardlink, just copy the file
                prepare_regular_copy(
                    _entry, _first_resource, target_mnt=self.target_dir
                )
                continue

            # hardlinked file
            if _inode_id in _hardlink_dict:
                prepare_regular_hardlink(
                    _entry,
                    _hardlink_dict[_inode_id],
                    target_mnt=self.target_dir,
                    hardlink_skip_apply_permission=True,
                )
            else:  # first hardlink item
                _fpath_on_target = prepare_regular_copy(
                    _entry,
                    _first_resource,
                    target_mnt=self.target_dir,
                )
                _hardlink_dict[_inode_id] = Path(_fpath_on_target)

    def _task_done_cb(self, _fut: Future) -> None:
        self._se.release()
        if _exc := _fut.exception():
            logger.warning(f"failed during processing: {_exc}", exc_info=_exc)

    def process(self):
        _cur_digest, _cur_batch = b"", []
        ft_dbhelper = FileTableDBHelper(self._ft_dbf)
        with ThreadPoolExecutor(max_workers=self.worker_threads) as pool:
            submit_with_se = func_call_with_se(pool.submit, self._se)
            for _entry in ft_dbhelper.iter_regular_entries():
                _this_digest = _entry["digest"]

                if _this_digest != _cur_digest:
                    if len(_cur_batch) == 1:
                        submit_with_se(
                            self._rebuild_single_file_at_thread, _cur_batch[0]
                        ).add_done_callback(self._task_done_cb)
                    elif len(_cur_batch) > 1:
                        submit_with_se(
                            self._rebuild_digest_files_group_at_thread,
                            _cur_digest,
                            _cur_batch,
                        ).add_done_callback(self._task_done_cb)

                    _cur_digest = _this_digest
                    # do not clear as we pass this list to the worker previously
                    _cur_batch = []
                _cur_batch.append(_entry)

            # don't forget the last batch
            submit_with_se(
                self._rebuild_digest_files_group_at_thread,
                _cur_digest,
                _cur_batch,
            ).add_done_callback(self._task_done_cb)


def rebuild_rootfs_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    rebuild_rootfs_arg_parser = sub_arg_parser.add_parser(
        name="rebuild-rootfs",
        help="Rebuild the rootfs from the OTA image.",
        description="Rebuild the rootfs from the OTA image.",
        parents=parent_parser,
    )
    rebuild_rootfs_arg_parser.add_argument(
        "--tmp-dir",
        help="Temporary working directory during rootfs rebuild. "
        "If not set, ota-image-tools will use the system default temp directory(typically, /tmp) "
        "to set up the working directory.",
    )
    rebuild_rootfs_arg_parser.add_argument(
        "--image-root",
        type=Path,
        required=True,
        help="Path to the OTA image root directory.",
    )
    rebuild_rootfs_arg_parser.add_argument(
        "--image-id",
        required=True,
        help="Unique identifier for the image payload to use. "
        "Schema: `<ecu_id>[:<ota_release_key>]`. "
        "If <ota_release_key> is not specified, `dev` variant is assumed.",
    )
    rebuild_rootfs_arg_parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="The path to the folder holding the rebuilt rootfs.",
    )
    rebuild_rootfs_arg_parser.add_argument(
        "--worker-threads",
        type=int,
        default=6,
        help="How many worker threads to use when rebuild the rootfs.",
    )
    rebuild_rootfs_arg_parser.add_argument(
        "--max-concurrent",
        type=int,
        default=12,
        help="How many pending tasks in the thread pool wait list.",
    )
    rebuild_rootfs_arg_parser.set_defaults(handler=rebuild_rootfs_cmd)


def rebuild_rootfs_cmd(args: Namespace) -> None:
    logger.debug(f"calling {rebuild_rootfs_cmd.__name__} with {args}")
    image_root: Path = args.image_root
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")

    target: Path = args.target
    target.mkdir(parents=True, exist_ok=True)

    index_helper = ImageIndexHelper(image_root)
    image_index = index_helper.image_index
    image_resource_dir = index_helper.image_resource_dir
    print(f"Rebuilding rootfs from OTA image at {image_root} to {target} ...")

    image_id: str = args.image_id
    ecu_id, ota_release_key, *_ = *image_id.rsplit(":", maxsplit=1), "dev"
    print(f"Will use image payload: {ecu_id=}, {ota_release_key=}")

    with TemporaryDirectory(dir=args.tmp_dir) as tmp_workding_dir, TemporaryDirectory(
        dir=target, prefix=TMP_RESOURCE_DIR
    ) as tmp_resource_dir:
        logger.debug(f"Setup tmp resource dir at {tmp_resource_dir}")
        logger.debug(f"Setup tmp working dir at {tmp_workding_dir}")
        tmp_resource_dir = Path(tmp_resource_dir)
        tmp_workding_dir = Path(tmp_workding_dir)

        image_manifest_d = image_index.find_image(
            ImageIdentifier(ecu_id, OTAReleaseKey(ota_release_key))
        )
        if image_manifest_d is None:
            exit_with_err_msg(
                f"Image with {ecu_id=},{ota_release_key=} not found in the OTA image."
            )
        image_manifest = image_manifest_d.load_metafile_from_resource_dir(
            resource_dir=image_resource_dir
        )
        ft_dbf = tmp_workding_dir / tmp_fname("file_table.sqlite3")
        image_manifest.image_file_table.export_blob_from_resource_dir(
            resource_dir=image_resource_dir, save_dst=ft_dbf, auto_decompress=True
        )

        resource_table_d = image_index.image_resource_table
        if resource_table_d is None:
            exit_with_err_msg(
                "The OTA image does not contain a resource table. "
                "Please ensure at least one image payload is added to the OTA image."
            )

        rst_dbf = tmp_workding_dir / tmp_fname("resource_table.sqlite3")
        resource_table_d.export_blob_from_resource_dir(
            resource_dir=image_resource_dir, save_dst=rst_dbf, auto_decompress=True
        )

        ft_dbhelper = FileTableDBHelper(ft_dbf)

        _start_time = time.time()
        print("Rebuild directories ...")
        try:
            _rebuild_directories(ft_dbhelper, target)
        except Exception as e:
            logger.error(f"Rebuild directories failed: {e}", exc_info=e)
            exit_with_err_msg(
                f"Failed to rebuild directories in {target}: {e}",
            )

        print("Rebuild non-regular files ...")
        try:
            _rebuild_non_regular_files(ft_dbhelper, target)
        except Exception as e:
            logger.error(f"Rebuild non-regular files failed: {e}", exc_info=e)
            exit_with_err_msg(
                f"Failed to rebuild non-regular files in {target}: {e}",
            )

        print("Rebuild regular files ...")
        try:
            _regular_files_helper = RebuildRegularFilesHelper(
                ft_dbf=ft_dbf,
                rst_dbf=rst_dbf,
                target_dir=target,
                resource_dir=image_resource_dir,
                tmp_resource_dir=tmp_resource_dir,
                worker_threads=args.worker_threads,
                max_concurrent=args.max_concurrent,
            )
            _regular_files_helper.process()
        except Exception as e:
            logger.error(f"Rebuild regular files failed: {e}", exc_info=e)
            exit_with_err_msg(
                f"Failed to rebuild regular files in {target}: {e}",
            )

        print(
            f"Rebuilding rootfs completed, total time cost: {time.time() - _start_time}s"
        )
