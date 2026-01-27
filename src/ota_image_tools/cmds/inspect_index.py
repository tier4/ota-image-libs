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

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.consts import IMAGE_INDEX_FNAME
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)


def inspect_index_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    inspect_index_arg_parser = sub_arg_parser.add_parser(
        name="inspect-index",
        help=(_help_txt := "Print out the index.json of the OTA image"),
        description=_help_txt,
        parents=parent_parser,
    )
    inspect_index_arg_parser.add_argument(
        "image_root",
        help="Points to a folder holds OTA image, or to an OTA image artifact.",
    )
    inspect_index_arg_parser.set_defaults(handler=inspect_index_cmd)


def inspect_index_cmd(args: Namespace) -> None:
    logger.debug(f"calling {inspect_index_cmd.__name__} with {args}")
    image_root = Path(args.image_root)

    if image_root.is_dir():
        if not check_if_valid_ota_image(image_root):
            exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")

        _index_f = image_root / IMAGE_INDEX_FNAME
        _formatted_json = json.dumps(json.loads(_index_f.read_text()), indent=2)
        return print(_formatted_json)

    if image_root.is_file():
        with OTAImageArtifactReader(image_root) as artifact_reader:
            return print(
                artifact_reader.parse_index().model_dump_json(
                    indent=2, exclude_none=True
                )
            )

    exit_with_err_msg(f"{image_root} is not a folder nor an OTA image artifact!")
