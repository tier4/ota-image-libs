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
from pathlib import Path
from typing import TYPE_CHECKING

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.consts import RESOURCE_DIR
from ota_image_libs.v1.image_index.utils import ImageIndexHelper
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)


def get_resourcetable_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    get_resourcetable_arg_parser = sub_arg_parser.add_parser(
        name="get-resourcetable",
        help=(
            _help_txt
            := "Extract the decompressed resource_table SQLite database from an OTA image."
        ),
        description=_help_txt,
        parents=parent_parser,
    )
    get_resourcetable_arg_parser.add_argument(
        "-o",
        "--output",
        help="The output path to save the decompressed resource_table database.",
        required=True,
    )
    get_resourcetable_arg_parser.add_argument(
        "image_root",
        help="Points to a folder that holds an OTA image, or to an OTA image artifact.",
    )
    get_resourcetable_arg_parser.set_defaults(handler=get_resourcetable_cmd)


def _get_resourcetable_from_folder(*, image_root: Path, output: Path) -> None:
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")

    _index_helper = ImageIndexHelper(image_root)
    image_index = _index_helper.image_index

    _rt_descriptor = image_index.image_resource_table
    if not _rt_descriptor:
        exit_with_err_msg("resource_table not found in the OTA image.")

    _resource_dir = image_root / RESOURCE_DIR
    _rt_descriptor.export_blob_from_resource_dir(
        _resource_dir, output, auto_decompress=True
    )
    logger.info(f"resource_table saved to {output}")


def _get_resourcetable_from_artifact(*, image_root: Path, output: Path) -> None:
    with OTAImageArtifactReader(image_root) as artifact_reader:
        image_index = artifact_reader.parse_index()
        try:
            artifact_reader.get_resource_table(image_index, output)
        except ValueError as e:
            exit_with_err_msg(f"failed to get the resource_table: {e!r}")
    logger.info(f"resource_table saved to {output}")


def get_resourcetable_cmd(args: Namespace) -> None:
    logger.debug(f"calling {get_resourcetable_cmd.__name__} with {args}")
    image_root = Path(args.image_root)
    output = Path(args.output)

    if image_root.is_dir():
        return _get_resourcetable_from_folder(
            image_root=image_root,
            output=output,
        )

    if image_root.is_file():
        return _get_resourcetable_from_artifact(
            image_root=image_root,
            output=output,
        )
    exit_with_err_msg(f"{image_root} is not a folder nor an OTA image artifact!")
