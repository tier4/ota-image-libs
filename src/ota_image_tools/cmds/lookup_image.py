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

from ota_image_libs.v1.consts import RESOURCE_DIR
from ota_image_libs.v1.image_index.utils import ImageIndexHelper
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier, OTAReleaseKey
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)


def lookup_image_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    lookup_image_arg_parser = sub_arg_parser.add_parser(
        name="lookup-image",
        help=(
            _help_txt
            := "Look for image payload within the OTA image and print out the image_manifest/image_config of it."
        ),
        description=_help_txt,
        parents=parent_parser,
    )
    lookup_image_arg_parser.add_argument(
        "--ecu-id",
        help=("The target ECU ID to look up."),
    )
    lookup_image_arg_parser.add_argument(
        "--release-key",
        help="The release variant of the image to lookup, default `dev`",
        type=OTAReleaseKey,
    )
    lookup_image_arg_parser.add_argument(
        "image_root",
        help="Folder that holds the OTA image.",
    )
    lookup_image_arg_parser.set_defaults(handler=lookup_image_cmd)


def lookup_image_cmd(args: Namespace) -> None:
    logger.debug(f"calling {lookup_image_cmd.__name__} with {args}")
    image_root = Path(args.image_root)
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")

    ecu_id = args.ecu_id
    release_key = args.release_key

    image_identifier = ImageIdentifier(ecu_id=ecu_id, release_key=release_key)
    print(f"Look for {image_identifier} in the OTA image ...")

    _index_helper = ImageIndexHelper(image_root)
    image_index = _index_helper.image_index

    _image_manifest_descriptor = image_index.find_image(image_identifier)
    if not _image_manifest_descriptor:
        exit_with_err_msg(f"failed to find image with {image_identifier=}")

    image_manifest_fpath = (
        image_root / RESOURCE_DIR / _image_manifest_descriptor.digest.digest_hex
    )
    print(f"image_manifest for {image_identifier=}: \n")
    print(image_manifest_fpath.read_text())
