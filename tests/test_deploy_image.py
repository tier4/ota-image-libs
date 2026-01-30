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
"""Tests for the deploy_image module."""

from __future__ import annotations

import os
from concurrent.futures import Future
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import (
    ImageIdentifier,
    ImageManifest,
    OTAReleaseKey,
)
from ota_image_tools.libs.deploy_image import (
    READ_SIZE,
    OTAImageDeployerSetup,
    ResourcesDeployer,
    RootfsDeployer,
    SetupWorkDirFailed,
)

LIBS_DEPLOY_IMAGE = "ota_image_tools.libs.deploy_image"


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    """Create a temporary working directory."""
    wd = tmp_path / "workdir"
    wd.mkdir(parents=True, exist_ok=True)
    return wd


@pytest.fixture
def resource_dir(tmp_path: Path) -> Path:
    """Create a temporary resource directory."""
    rd = tmp_path / "resources"
    rd.mkdir(parents=True, exist_ok=True)
    return rd


@pytest.fixture
def rootfs_dir(tmp_path: Path) -> Path:
    """Create a temporary rootfs directory."""
    rfd = tmp_path / "rootfs"
    rfd.mkdir(parents=True, exist_ok=True)
    return rfd


@pytest.fixture
def tmp_download_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for downloads."""
    td = tmp_path / "tmp"
    td.mkdir(parents=True, exist_ok=True)
    return td


@pytest.fixture
def one_image_id(test_artifact) -> ImageIdentifier:
    """Get a valid ImageIdentifier from the test artifact.

    This reads the test OTA image to find the first valid image manifest.
    """
    with OTAImageArtifactReader(test_artifact) as reader:
        image_index = reader.parse_index()
        for entry in image_index.manifests:
            if isinstance(entry, ImageManifest.Descriptor):
                manifest = ImageManifest.parse_metafile(
                    reader.read_blob_as_text(entry.digest.digest_hex)
                )
                return manifest.image_identifier
    raise ValueError("invalid test data!")


class TestOTAImageDeployerSetup:
    """Tests for OTAImageDeployerSetup class."""

    def test_setup_with_invalid_image_id(self, test_artifact: Path, workdir: Path):
        """Test setup with an invalid image ID raises SetupWorkDirFailed or exits."""
        invalid_image_id = ImageIdentifier(
            ecu_id="nonexistent_ecu", release_key=OTAReleaseKey.dev
        )
        with pytest.raises((SetupWorkDirFailed, SystemExit)):
            OTAImageDeployerSetup(
                invalid_image_id, artifact=test_artifact, workdir=workdir
            )

    def test_setup_with_invalid_artifact(self, tmp_path: Path, workdir: Path):
        """Test setup with an invalid artifact raises SetupWorkDirFailed."""
        invalid_artifact = tmp_path / "invalid.zip"
        invalid_artifact.write_bytes(b"not a valid zip")

        image_id = ImageIdentifier(ecu_id="main_ecu", release_key=OTAReleaseKey.dev)
        with pytest.raises(SetupWorkDirFailed):
            OTAImageDeployerSetup(image_id, artifact=invalid_artifact, workdir=workdir)

    def test_setup_with_nonexistent_artifact(self, workdir: Path):
        """Test setup with non-existent artifact raises SetupWorkDirFailed."""
        nonexistent = Path("/nonexistent/path/artifact.zip")
        image_id = ImageIdentifier(ecu_id="main_ecu", release_key=OTAReleaseKey.dev)
        with pytest.raises(SetupWorkDirFailed):
            OTAImageDeployerSetup(image_id, artifact=nonexistent, workdir=workdir)


def test_worker_cb_sets_failed_flag_on_exception(
    mocker: MockerFixture, resource_dir, tmp_download_dir
):
    """Test that _worker_cb sets failed flag on exception."""
    workdir_setup = mocker.MagicMock(spec=OTAImageDeployerSetup)
    workdir_setup._rst_db_helper = mocker.MagicMock()
    workdir_setup._rst_db_helper.get_orm_pool = mocker.MagicMock()

    deployer = ResourcesDeployer(
        workdir_setup=workdir_setup,
        resource_dir=resource_dir,
        tmp_dir=tmp_download_dir,
        workers_num=2,
        concurrent_jobs=10,
        read_size=READ_SIZE,
    )

    fut = mocker.MagicMock(spec=Future)
    exc = ValueError("injected test failure")
    fut.exception.return_value = exc

    deployer._concurrent_se.acquire()
    deployer._worker_cb(fut)
    assert deployer._last_exc is exc


def test_deploy_image_e2e(
    mocker: MockerFixture,
    test_artifact: Path,
    one_image_id,
    workdir,
    resource_dir,
    tmp_download_dir,
    rootfs_dir,
):
    """Test the deployment workflow up to resource deployment.

    Note: Full rootfs deployment requires root permissions for chown/chmod.
    This test verifies setup and resource deployment work correctly.
    """
    if os.geteuid() != 0:  # patch privileged operations for non-root tests
        mocker.patch(f"{LIBS_DEPLOY_IMAGE}.prepare_dir")
        mocker.patch(f"{LIBS_DEPLOY_IMAGE}.prepare_non_regular")
        mocker.patch(f"{LIBS_DEPLOY_IMAGE}.prepare_regular_inlined")
        mocker.patch(f"{LIBS_DEPLOY_IMAGE}.prepare_regular_hardlink")
        mocker.patch(f"{LIBS_DEPLOY_IMAGE}.prepare_regular_copy")

    setup = OTAImageDeployerSetup(one_image_id, artifact=test_artifact, workdir=workdir)

    resources_deployer = ResourcesDeployer(
        workdir_setup=setup,
        resource_dir=resource_dir,
        tmp_dir=tmp_download_dir,
        workers_num=2,
        concurrent_jobs=10,
        read_size=READ_SIZE,
        rst_db_conn=2,
    )
    resources_deployer.deploy_resources()

    rootfs_deployer = RootfsDeployer(
        file_table_db_helper=setup._ft_db_helper,
        rootfs_dir=rootfs_dir,
        resource_dir=resource_dir,
        max_workers=2,
        concurrent_tasks=10,
    )
    rootfs_deployer.setup_rootfs()
