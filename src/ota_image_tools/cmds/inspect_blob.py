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
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ota_image_libs.common.oci_spec import Sha256Digest
from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.consts import RESOURCE_DIR
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction

READ_SIZE = 1024**2  # 1MiB

logger = logging.getLogger(__name__)


def inspect_blob_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    inspect_blob_arg_parser = sub_arg_parser.add_parser(
        name="inspect-blob",
        help=(_help_txt := "Print out the content or save a blob from the OTA image"),
        description=_help_txt,
        parents=parent_parser,
    )
    inspect_blob_arg_parser.add_argument(
        "--output",
        "-o",
        help="If specified, save the blob to a file.",
    )
    inspect_blob_arg_parser.add_argument(
        "--checksum",
        help="The sha256 checksum of the blob.",
        required=True,
    )
    inspect_blob_arg_parser.add_argument(
        "--bytes",
        action="store_true",
        help="Print out the blob as binary blob, only respected when `-o` is not specified.",
    )
    inspect_blob_arg_parser.add_argument(
        "image_root",
        help="Points to a folder that holds an OTA image, or to an OTA image artifact.",
    )
    inspect_blob_arg_parser.set_defaults(handler=inspect_blob_cmd)


def _inspect_blob_from_folder(
    *, sha256_digest: str, image_root: Path, save_dst: str | None, to_bytes: bool
):
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")

    _resource_folder = image_root / RESOURCE_DIR
    _resource = _resource_folder / sha256_digest

    if not _resource.is_file():
        exit_with_err_msg(f"{_resource} not found in blob storage!")

    if save_dst:
        print(f"Save blob to {save_dst} ...")
        shutil.copy(_resource, save_dst)
        return

    with open(_resource, "rb" if to_bytes else "r") as f:
        while data := f.read(READ_SIZE):
            print(data, end=None)


def _inspect_blob_from_image_artifact(
    *,
    sha256_digest: str,
    image_root: Path,
    save_dst: str | None,
    to_bytes: bool,
    encoding: str = "utf-8",
):
    with OTAImageArtifactReader(
        image_root
    ) as artifact_reader, artifact_reader.open_blob(sha256_digest) as _blob:
        if save_dst:
            with open(save_dst, "wb") as _dst:
                return shutil.copyfileobj(_blob, _dst)
        if to_bytes:
            return shutil.copyfileobj(_blob, sys.stdout.buffer)

        # manually read from blob stream and doing the decode
        while chunk := _blob.read(READ_SIZE):
            sys.stdout.write(chunk.decode(encoding))


def inspect_blob_cmd(args: Namespace) -> None:
    logger.debug(f"calling {inspect_blob_cmd.__name__} with {args}")
    try:
        checksum = Sha256Digest._from_str_validator(args.checksum).digest_hex
    except Exception as e:
        exit_with_err_msg(
            f"Not a valid checksum, only sha256 checksum is supported: {e}"
        )

    image_root = Path(args.image_root)
    if image_root.is_dir():
        return _inspect_blob_from_folder(
            sha256_digest=checksum,
            image_root=image_root,
            save_dst=args.output,
            to_bytes=args.bytes,
        )
    if image_root.is_file():
        return _inspect_blob_from_image_artifact(
            sha256_digest=checksum,
            image_root=image_root,
            save_dst=args.output,
            to_bytes=args.bytes,
        )

    exit_with_err_msg(f"{image_root} is not a folder nor an OTA image artifact!")
