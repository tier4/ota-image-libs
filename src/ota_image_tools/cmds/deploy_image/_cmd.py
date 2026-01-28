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
import os
import tempfile
from pathlib import Path
from pprint import pformat
from typing import TYPE_CHECKING

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import ImageIdentifier
from ota_image_tools._utils import exit_with_err_msg, measure_timecost
from ota_image_tools.libs.deploy_image import (
    CONCURRENT_JOBS,
    READ_SIZE,
    WORKERS_NUM,
    OTAImageDeployerSetup,
    ResourcesDeployer,
    RootfsDeployer,
)

if TYPE_CHECKING:
    from argparse import ArgumentParser, Namespace, _SubParsersAction


logger = logging.getLogger(__name__)


def deploy_image_cmd_args(
    sub_arg_parser: _SubParsersAction[ArgumentParser], *parent_parser: ArgumentParser
) -> None:
    deploy_image_arg_parser = sub_arg_parser.add_parser(
        name="deploy-image",
        help=(
            _help_txt
            := "Deploy an system image payload from the input OTA image artifact to a folder."
        ),
        description=_help_txt,
        parents=parent_parser,
    )
    deploy_image_arg_parser.add_argument(
        "--image",
        "-i",
        help="The OTA image artifact to use.",
        required=True,
    )
    deploy_image_arg_parser.add_argument(
        "--ecu-id",
        help="The ECU ID for the system image payload to use.",
        required=True,
    )
    deploy_image_arg_parser.add_argument(
        "--release-key",
        "-k",
        help="The release key for the system image payload to use. "
        "If not specified, default to `dev`.",
        choices=("dev", "prd"),
        default="dev",
    )
    deploy_image_arg_parser.add_argument(
        "--rootfs-dir",
        "-o",
        help="The target folder to deploy the system rootfs image to.",
        required=True,
    )
    deploy_image_arg_parser.add_argument(
        "--tmp-dir",
        "-t",
        help="The temporary directory used for deployment. If not specified, "
        "will create a temporary workdir at the current directory.",
    )
    deploy_image_arg_parser.add_argument(
        "--workers",
        "-w",
        type=int,
        help="The number of workers when deploying the rootfs. "
        "If not specified, will be calculated from `min(8, (os.cpu_count() or 1) + 4)`. "
        f"(current value: {WORKERS_NUM}).",
        default=WORKERS_NUM,
    )
    deploy_image_arg_parser.add_argument(
        "--concurrent",
        type=int,
        help="The maximum allowed concurrent jobs during rootfs deploying.",
        default=CONCURRENT_JOBS,
    )
    deploy_image_arg_parser.add_argument(
        "--read-size",
        type=int,
        help="The maximum read buffer size for every `read` to the image artifact. "
        "Adjust this value when the `deploy-image` cmd uses too much memory.",
        default=READ_SIZE,
    )
    deploy_image_arg_parser.set_defaults(handler=measure_timecost(deploy_image_cmd))


def deploy_image_cmd(args: Namespace) -> None:
    logger.debug(f"calling {deploy_image_cmd.__name__} with {args}")
    image = Path(args.image)
    if not image.is_file():
        exit_with_err_msg(f"input image file {image} not found!")

    rootfs_dir = Path(args.rootfs_dir)
    if rootfs_dir.is_dir():
        exit_with_err_msg(f"{rootfs_dir} already exists!")
    rootfs_dir.mkdir(mode=0o750)
    # NOTE: aligns with otaclient's convention
    resource_dir = rootfs_dir / ".ota-resources"
    resource_dir.mkdir(mode=0o700)

    with OTAImageArtifactReader(image) as _zipr:
        if not _zipr.is_valid_image():
            exit_with_err_msg("not a valid OTA image artifact!")

    if args.tmp_dir:
        tmp_dir_base = Path(args.tmp_dir)
        logger.info(
            f"will create tmp workdir under user specified tmp dir base: {tmp_dir_base}"
        )
    else:
        tmp_dir_base = os.getcwd()
        logger.info(f"will create tmp workdir under current workdir: {tmp_dir_base}")

    with tempfile.TemporaryDirectory(
        prefix=".ota_image_deployer",
        suffix=f"-{os.urandom(4).hex()}",
        dir=tmp_dir_base,
    ) as tmpdir:
        logger.debug(f"use {tmpdir=}")
        tmpdir = Path(tmpdir)

        logger.info("setup workdir for the deployment ...")
        workdir = tmpdir / "workdir"
        workdir.mkdir()

        image_id = ImageIdentifier(ecu_id=args.ecu_id, release_key=args.release_key)
        logger.info(f"will use system image payload with {image_id=}.")
        workdir_setup = OTAImageDeployerSetup(image_id, artifact=image, workdir=workdir)

        logger.info(
            "OTA image index labels: \n"
            f"{pformat(workdir_setup.image_index.annotations.model_dump(exclude_none=True))}"
        )

        assert workdir_setup.image_manifest
        logger.info(
            f"OTA image manifest annotations for {image_id=}: \n"
            f"{pformat(workdir_setup.image_manifest.annotations.model_dump(exclude_none=True))}"
        )

        image_config = workdir_setup.image_config
        logger.info(
            "system image statistics: \n"
            f"{pformat(image_config.labels.model_dump(exclude_none=True))}"
        )

        logger.info("deploy resources for later setting rootfs ...")
        resource_deploy_tmp_dir = tmpdir / "resource_deploy_tmpdir"
        resource_deploy_tmp_dir.mkdir()
        resource_deployer = ResourcesDeployer(
            workdir_setup=workdir_setup,
            resource_dir=resource_dir,
            tmp_dir=resource_deploy_tmp_dir,
            workers_num=args.workers,
            concurrent_jobs=args.concurrent,
            read_size=args.read_size,
        )
        resource_deployer.deploy_resources()

        logger.info(f"setup rootfs at {rootfs_dir} ...")
        rootfs_deployer = RootfsDeployer(
            file_table_db_helper=workdir_setup._ft_db_helper,
            rootfs_dir=rootfs_dir,
            resource_dir=resource_dir,
            max_workers=args.workers,
            concurrent_tasks=args.concurrent,
        )
        rootfs_deployer.setup_rootfs()

        logger.info(f"finish deploying system image with {image_id=} to {rootfs_dir=}!")
