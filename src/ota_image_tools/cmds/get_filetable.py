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
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier, OTAReleaseKey
from ota_image_tools._utils import exit_with_err_msg
from ota_image_tools.libs.common import (
    resolve_image_from_artifact,
    resolve_image_from_folder,
)

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)


def get_filetable_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    get_filetable_arg_parser = sub_arg_parser.add_parser(
        name="get-filetable",
        help=(
            _help_txt
            := "Extract the decompressed file_table SQLite database for a specific image payload."
        ),
        description=_help_txt,
        parents=parent_parser,
    )
    get_filetable_arg_parser.add_argument(
        "--ecu-id",
        help="The target ECU ID to look up.",
        required=True,
    )
    get_filetable_arg_parser.add_argument(
        "--release-key",
        help="The release variant of the image to lookup.",
        type=OTAReleaseKey,
        choices=[OTAReleaseKey.prd.value, OTAReleaseKey.dev.value],
        default=OTAReleaseKey.dev.value,
    )
    get_filetable_arg_parser.add_argument(
        "-o",
        "--output",
        help="The output path to save the decompressed file_table database.",
        required=True,
    )
    get_filetable_arg_parser.add_argument(
        "image_root",
        help="Points to a folder that holds an OTA image, or to an OTA image artifact.",
    )
    get_filetable_arg_parser.set_defaults(handler=get_filetable_cmd)


def _get_filetable_from_folder(
    *, image_root: Path, image_id: ImageIdentifier, output: Path
) -> None:
    _image_manifest_descriptor, _resource_dir = resolve_image_from_folder(
        image_root, image_id
    )

    image_manifest = _image_manifest_descriptor.load_metafile_from_resource_dir(
        _resource_dir
    )
    image_config = image_manifest.config.load_metafile_from_resource_dir(_resource_dir)
    image_config.file_table.export_blob_from_resource_dir(
        _resource_dir, output, auto_decompress=True
    )
    logger.info(f"file_table saved to {output}")


def _get_filetable_from_artifact(
    *, image_root: Path, image_id: ImageIdentifier, output: Path
) -> None:
    with OTAImageArtifactReader(image_root) as artifact_reader:
        image_manifest = resolve_image_from_artifact(artifact_reader, image_id)
        image_config, _ = artifact_reader.get_image_config(image_manifest)
        artifact_reader.get_file_table(image_config, output)
    logger.info(f"file_table saved to {output}")


def get_filetable_cmd(args: Namespace) -> None:
    logger.debug(f"calling {get_filetable_cmd.__name__} with {args}")
    image_identifier = ImageIdentifier(ecu_id=args.ecu_id, release_key=args.release_key)
    logger.info(f"look for {image_identifier} in the OTA image ...")

    image_root = Path(args.image_root)
    output = Path(args.output)

    if image_root.is_dir():
        return _get_filetable_from_folder(
            image_root=image_root,
            image_id=image_identifier,
            output=output,
        )

    if image_root.is_file():
        return _get_filetable_from_artifact(
            image_root=image_root,
            image_id=image_identifier,
            output=output,
        )
    exit_with_err_msg(f"{image_root} is not a folder nor an OTA image artifact!")
