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
            := "Look for image payload within the OTA image and print out the image_manifest of it."
        ),
        description=_help_txt,
        parents=parent_parser,
    )
    lookup_image_arg_parser.add_argument(
        "--ecu-id",
        help="The target ECU ID to look up.",
        required=True,
    )
    lookup_image_arg_parser.add_argument(
        "--image-config",
        help="Print the image config instead of image manifest.",
        action="store_true",
        default=False,
    )
    lookup_image_arg_parser.add_argument(
        "--release-key",
        help="The release variant of the image to lookup.",
        type=OTAReleaseKey,
        choices=[OTAReleaseKey.prd.value, OTAReleaseKey.dev.value],
        default=OTAReleaseKey.dev.value,
    )
    lookup_image_arg_parser.add_argument(
        "image_root",
        help="Points to a folder holds OTA image, or to an OTA image artifact.",
    )
    lookup_image_arg_parser.set_defaults(handler=lookup_image_cmd)


def _lookup_image_from_folder(
    *, image_root: Path, image_id: ImageIdentifier, show_image_config: bool
):
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")

    _index_helper = ImageIndexHelper(image_root)
    image_index = _index_helper.image_index

    _image_manifest_descriptor = image_index.find_image(image_id)
    if not _image_manifest_descriptor:
        exit_with_err_msg(f"failed to find image with {image_id=}")

    _resource_dir = image_root / RESOURCE_DIR
    image_manifest_fpath = _resource_dir / _image_manifest_descriptor.digest.digest_hex
    if show_image_config:
        image_manifest = _image_manifest_descriptor.load_metafile_from_resource_dir(
            _resource_dir
        )
        image_config_fpath = _resource_dir / image_manifest.config.digest.digest_hex
        logger.info("image_config: ")
        return print(image_config_fpath.read_text())

    logger.info("image_manifest: ")
    print(image_manifest_fpath.read_text())


def _lookup_image_from_artifact(
    *, image_root: Path, image_id: ImageIdentifier, show_image_config: bool
):
    with OTAImageArtifactReader(image_root) as artifact_reader:
        image_index = artifact_reader.parse_index()
        image_manifest = artifact_reader.select_image_payload(image_id, image_index)
        assert image_manifest

        if show_image_config:
            image_config, _ = artifact_reader.get_image_config(image_manifest)
            logger.info("image_config: ")
            print(f"{image_config.model_dump_json(indent=2, exclude_none=True)}")

        logger.info("image_manifest: ")
        print(f"{image_manifest.model_dump_json(indent=2, exclude_none=True)}")


def lookup_image_cmd(args: Namespace) -> None:
    logger.debug(f"calling {lookup_image_cmd.__name__} with {args}")
    image_identifier = ImageIdentifier(ecu_id=args.ecu_id, release_key=args.release_key)
    logger.info(f"look for {image_identifier} in the OTA image ...")

    image_root = Path(args.image_root)
    if image_root.is_dir():
        return _lookup_image_from_folder(
            image_root=image_root,
            image_id=image_identifier,
            show_image_config=args.image_config,
        )

    if image_root.is_file():
        return _lookup_image_from_artifact(
            image_root=image_root,
            image_id=image_identifier,
            show_image_config=args.image_config,
        )

    exit_with_err_msg(f"{image_root} is not a folder nor an OTA image artifact!")
