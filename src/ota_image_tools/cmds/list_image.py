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
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_index.utils import ImageIndexHelper
from ota_image_libs.v1.image_manifest.schema import ImageManifest
from ota_image_libs.v1.utils import check_if_valid_ota_image
from ota_image_tools._utils import exit_with_err_msg

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)


def list_image_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    list_image_arg_parser = sub_arg_parser.add_parser(
        name="list-image",
        help=(_help_txt := "List all OTA image payloads within this OTA image."),
        description=_help_txt,
        parents=parent_parser,
    )
    list_image_arg_parser.add_argument(
        "image",
        help="Points to an OTA image folder, or an OTA image artifact ZIP file.",
    )
    list_image_arg_parser.set_defaults(handler=list_image_cmd)


def _list_image_from_folder(image_root: Path) -> list[ImageManifest.Descriptor]:
    if not check_if_valid_ota_image(image_root):
        exit_with_err_msg(f"{image_root} doesn't hold a valid OTA image.")
    _index_helper = ImageIndexHelper(image_root)

    return [
        _d
        for _d in _index_helper.image_index.manifests
        if isinstance(_d, ImageManifest.Descriptor)
    ]


def _list_image_from_artifact(image_artifact: Path) -> list[ImageManifest.Descriptor]:
    with OTAImageArtifactReader(image_artifact) as artifact_reader:
        if not artifact_reader.is_valid_image():
            exit_with_err_msg(f"{image_artifact} is not a valid OTA image artifact!")

        return [
            _d
            for _d in artifact_reader.parse_index().manifests
            if isinstance(_d, ImageManifest.Descriptor)
        ]


_DIV = "-" * 18


def _render_output(_in: list[ImageManifest.Descriptor]) -> str:
    _buffer = StringIO()

    _title = f"{_DIV} OTA image payloads {_DIV}\n"
    _buffer.write(_title)
    for idx, _entry in enumerate(_in):
        if (_annon := _entry.annotations) is None:
            _buffer.write(f"{idx=} (no annotations available)\n")
            continue

        ecu_id, ota_release_key = (
            _annon.pilot_auto_platform_ecu,
            _annon.ota_release_key.value,
        )
        _buffer.write(f"{idx=}\t{ecu_id=}\t{ota_release_key=}\n")
    _buffer.write("-" * len(_title))
    return _buffer.getvalue()


def list_image_cmd(args: Namespace) -> None:
    logger.debug(f"calling {list_image_cmd.__name__} with {args}")
    image = Path(args.image)

    if image.is_dir():
        print(f"OTA image folder: {image}")
        res = _list_image_from_folder(image)
    else:
        print(f"OTA image artifact: {image}")
        res = _list_image_from_artifact(image)
    print(_render_output(res))
