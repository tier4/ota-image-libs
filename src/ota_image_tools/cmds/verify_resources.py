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
"""Verify the blobs in the OTA image blob storage are valid."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

from ota_image_libs.v1.consts import RESOURCE_DIR
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 8 * 1024**2  # 8 MiB
SHA256_DIGEST_HEX_SIZE = 64  # SHA256 hex digest size
REPORT_BATCH = 10_000


class FileDigestHelper:
    def __init__(
        self,
        resource_dir: Path,
        *,
        worker_threads: int,
        max_concurrent: int | None = None,
        read_size: int = READ_CHUNK_SIZE,
    ) -> None:
        self._resource_dir = resource_dir
        self._worker_threads = worker_threads
        self._se = threading.Semaphore(
            max_concurrent
            if max_concurrent and max_concurrent > 0
            else worker_threads * 6
        )
        self._read_chunk_size = read_size
        self._should_exit = threading.Event()
        self._last_failed_digest = None

        self._thread_local = threading.local()

    def _thread_worker_initializer(self) -> None:
        self._thread_local.buffer = buffer = bytearray(self._read_chunk_size)
        self._thread_local.view = memoryview(buffer)

    def _file_digest_at_thread(self, fpath: Path, expected_digest: str):
        """Copied from Python 3.13 stdlib hashlib.file_digest.

        Simplified as we know the `fileobj` represents an actual file.
        """
        try:
            buf = self._thread_local.buffer
            view = self._thread_local.view

            digestobj = sha256()
            with open(fpath, "rb") as fileobj:
                while (size := fileobj.readinto(buf)) > 0:
                    if self._should_exit.is_set():
                        return None
                    digestobj.update(view[:size])
            if digestobj.hexdigest() != expected_digest:
                self._last_failed_digest = expected_digest
                print(f"Find broken blob {fpath}: calculated: {digestobj.hexdigest()}")
        except Exception as e:
            self._should_exit.set()
            self._last_failed_digest = expected_digest
            print(f"Error during processing {fpath}: {e}")
        finally:
            self._se.release()

    def digest_files(self, digests_to_check: Iterator[str] | None = None):
        if digests_to_check:
            _blobs_gen = (self._resource_dir / digest for digest in digests_to_check)
        else:
            _blobs_gen = self._resource_dir.iterdir()

        with ThreadPoolExecutor(
            max_workers=self._worker_threads,
            thread_name_prefix="ota_image_sysimg_processer",
            # initialize buffer at thread worker starts up
            initializer=self._thread_worker_initializer,
        ) as worker_pool:
            _count = 0
            for _count, blob_fpath in enumerate(_blobs_gen, start=1):
                if _count % REPORT_BATCH == 0:
                    print(f"{_count} blobs are processed ...")
                if self._should_exit.is_set():
                    exit_with_err_msg(f"Find broken blob: {self._last_failed_digest}!")

                if len(blob_fpath.name) != SHA256_DIGEST_HEX_SIZE:
                    print(
                        f"WARNING: find not-a-blob file in resource_dir: {blob_fpath.name}"
                    )
                    continue

                # NOTE: in blob storage, the file name is its' own sha256 digest.
                self._se.acquire()
                worker_pool.submit(
                    self._file_digest_at_thread, blob_fpath, blob_fpath.name
                )
        print(f"Total {_count} blobs are verified.")


def verify_resources_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    verify_resources_arg_parser = sub_arg_parser.add_parser(
        name="verify-resources",
        help=(_help_txt := "Verify the resources in the OTA image"),
        description=_help_txt,
        parents=parent_parser,
    )
    verify_resources_arg_parser.add_argument(
        "--blob-checksum",
        action="append",
        help="If specified, instead of verifying the whole storage, "
        "only check the blob of this SHA256 checksum. "
        "Can be specified multiple times.",
    )
    verify_resources_arg_parser.add_argument(
        "--worker-threads",
        type=int,
        default=6,
        help="Number of worker threads to use for verifying the resources.",
    )
    verify_resources_arg_parser.add_argument(
        "image_root",
        help="Folder that holds the OTA image.",
    )
    verify_resources_arg_parser.set_defaults(handler=verify_resources_cmd)


def verify_resources_cmd(args: Namespace) -> None:
    logger.debug(f"calling {verify_resources_cmd.__name__} with {args}")
    image_root = Path(args.image_root)
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image!")

    resource_dir = image_root / RESOURCE_DIR
    blobs_to_check = None
    if args.blob_checksum:
        print(f"Verifying specified blobs in OTA image at {image_root} ...")
        blobs_to_check = (
            _checksum.split(":", maxsplit=1)[-1] for _checksum in args.blob_checksum
        )
    else:
        print(
            f"Verifying all blobs in the resource directory in OTA image at {image_root} ..."
        )
    FileDigestHelper(resource_dir, worker_threads=args.worker_threads).digest_files(
        blobs_to_check
    )
