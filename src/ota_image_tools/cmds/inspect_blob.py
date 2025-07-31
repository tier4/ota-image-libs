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
from pathlib import Path
from typing import TYPE_CHECKING

from ota_image_libs.common.oci_spec import Sha256Digest
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
        help="Print out the blob as binary blob.",
    )
    inspect_blob_arg_parser.add_argument(
        "image_root",
        help="Folder that holds the OTA image.",
    )
    inspect_blob_arg_parser.set_defaults(handler=inspect_blob_cmd)


def inspect_blob_cmd(args: Namespace) -> None:
    logger.debug(f"calling {inspect_blob_cmd.__name__} with {args}")
    image_root = Path(args.image_root)
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")

    try:
        _checksum = Sha256Digest._from_str_validator(args.checksum)
    except Exception as e:
        exit_with_err_msg(
            f"Not a valid checksum, only sha256 checksum is supported: {e}"
        )

    _resource_folder = image_root / RESOURCE_DIR
    _resource = _resource_folder / _checksum.digest_hex

    if not _resource.is_file():
        exit_with_err_msg(f"{_resource} not found in blob storage!")

    if _save_dst := args.output:
        print(f"Save blob to {_save_dst} ...")
        shutil.copy(_resource, _save_dst)
        return

    with open(_resource, "rb" if args.bytes else "r") as f:
        while data := f.read(READ_SIZE):
            print(data, end=None)
