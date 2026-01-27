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

# freeze_support MUST be called before as early as possible
if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()


def main():
    import argparse
    import functools
    import logging
    from collections.abc import Callable
    from typing import TYPE_CHECKING

    from ota_image_libs import version
    from ota_image_tools._utils import configure_logging
    from ota_image_tools.cmds.lookup_image import lookup_image_cmd_args

    from .cmds import (
        inspect_blob_cmd_args,
        inspect_index_cmd_args,
        verify_resources_cmd_args,
        verify_sign_cmd_args,
    )

    if TYPE_CHECKING:
        from argparse import ArgumentParser, _SubParsersAction

    logger = logging.getLogger(__name__)

    arg_parser = argparse.ArgumentParser(
        description="OTA Image Tools for OTA Image version 1",
    )

    def missing_subcmd(_):
        print("Please specify subcommand.")
        print(arg_parser.format_help())

    arg_parser.set_defaults(handler=missing_subcmd)

    # ------ top-level parser ------ #
    arg_parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="Enable debug logging for this script",
    )

    sub_arg_parser: _SubParsersAction[ArgumentParser] = arg_parser.add_subparsers(
        title="available sub-commands",
        parser_class=functools.partial(
            argparse.ArgumentParser,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        ),  # type: ignore
    )

    # ------ sub commands registering ------ #

    version_cmd = sub_arg_parser.add_parser(
        name="version",
        help="Print the ota-image-libs version.",
    )
    version_cmd.set_defaults(
        handler=lambda _: print(f"Build with ota-image-libs v{version}.")
    )

    inspect_blob_cmd_args(sub_arg_parser)
    inspect_index_cmd_args(sub_arg_parser)
    lookup_image_cmd_args(sub_arg_parser)
    verify_sign_cmd_args(sub_arg_parser)
    verify_resources_cmd_args(sub_arg_parser)

    # ------ top-level args parsing ----- #
    args = arg_parser.parse_args()
    if args.debug:
        configure_logging(logging.DEBUG)
        logger.debug("Set to debug logging.")
    else:
        configure_logging(logging.INFO)

    # ------ execute command ------ #
    handler: Callable = args.handler
    handler(args)


if __name__ == "__main__":
    main()
