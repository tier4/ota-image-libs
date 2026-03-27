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
"""Tests for get_filetable command module."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import (
    ImageIdentifier,
    ImageManifest,
    OTAReleaseKey,
)
from ota_image_tools.cmds.get_filetable import (
    _get_filetable_from_artifact,
    _get_filetable_from_folder,
    get_filetable_cmd,
)


@pytest.fixture
def valid_ecu_id(test_artifact: Path) -> str:
    """Get a valid ECU ID from the test OTA image."""
    with OTAImageArtifactReader(test_artifact) as reader:
        index = reader.parse_index()
        manifest_descriptor = index.manifests[0]
        manifest = ImageManifest.parse_metafile(
            reader.read_blob_as_text(manifest_descriptor.digest.digest_hex)
        )
        return manifest.ecu_id


@pytest.fixture
def valid_release_key(test_artifact: Path) -> OTAReleaseKey:
    """Get a valid release key from the test OTA image."""
    with OTAImageArtifactReader(test_artifact) as reader:
        index = reader.parse_index()
        manifest_descriptor = index.manifests[0]
        manifest = ImageManifest.parse_metafile(
            reader.read_blob_as_text(manifest_descriptor.digest.digest_hex)
        )
        return manifest.ota_release_key


class TestGetFiletableFromArtifact:
    """Tests for extracting file_table from OTA image artifact."""

    def test_get_filetable(
        self,
        test_artifact: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        tmp_path: Path,
    ):
        """Test extracting file_table from artifact produces a valid SQLite database."""
        output = tmp_path / "file_table.db"
        image_id = ImageIdentifier(ecu_id=valid_ecu_id, release_key=valid_release_key)

        _get_filetable_from_artifact(
            image_root=test_artifact,
            image_id=image_id,
            output=output,
        )

        assert output.exists()
        assert output.stat().st_size > 0
        # Verify it is a valid SQLite database
        conn = sqlite3.connect(output)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert len(tables) > 0


class TestGetFiletableFromFolder:
    """Tests for extracting file_table from extracted OTA image folder."""

    def test_get_filetable(
        self,
        extracted_ota_image: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        tmp_path: Path,
    ):
        """Test extracting file_table from folder produces a valid SQLite database."""
        output = tmp_path / "file_table.db"
        image_id = ImageIdentifier(ecu_id=valid_ecu_id, release_key=valid_release_key)

        _get_filetable_from_folder(
            image_root=extracted_ota_image,
            image_id=image_id,
            output=output,
        )

        assert output.exists()
        assert output.stat().st_size > 0
        conn = sqlite3.connect(output)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert len(tables) > 0

    def test_get_filetable_not_found(self, extracted_ota_image: Path, tmp_path: Path):
        """Test error when image is not found in folder."""
        output = tmp_path / "file_table.db"
        image_id = ImageIdentifier(
            ecu_id="nonexistent_ecu", release_key=OTAReleaseKey.dev
        )

        with pytest.raises(SystemExit):
            _get_filetable_from_folder(
                image_root=extracted_ota_image,
                image_id=image_id,
                output=output,
            )

    def test_get_filetable_invalid_folder(self, tmp_path: Path):
        """Test error with invalid OTA image folder."""
        invalid_folder = tmp_path / "invalid"
        invalid_folder.mkdir()
        output = tmp_path / "file_table.db"

        image_id = ImageIdentifier(ecu_id="test_ecu", release_key=OTAReleaseKey.dev)

        with pytest.raises(FileNotFoundError):
            _get_filetable_from_folder(
                image_root=invalid_folder,
                image_id=image_id,
                output=output,
            )


class TestGetFiletableCmd:
    """Tests for the main get_filetable_cmd handler."""

    def test_cmd_with_artifact(
        self,
        test_artifact: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        tmp_path: Path,
    ):
        """Test command handler with OTA image artifact."""
        output = tmp_path / "file_table.db"
        args = argparse.Namespace(
            ecu_id=valid_ecu_id,
            release_key=valid_release_key,
            image_root=str(test_artifact),
            output=str(output),
        )

        get_filetable_cmd(args)

        assert output.exists()

    def test_cmd_with_folder(
        self,
        extracted_ota_image: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        tmp_path: Path,
    ):
        """Test command handler with extracted OTA image folder."""
        output = tmp_path / "file_table.db"
        args = argparse.Namespace(
            ecu_id=valid_ecu_id,
            release_key=valid_release_key,
            image_root=str(extracted_ota_image),
            output=str(output),
        )

        get_filetable_cmd(args)

        assert output.exists()

    def test_cmd_invalid_path(self, tmp_path: Path):
        """Test command handler with non-existent path."""
        args = argparse.Namespace(
            ecu_id="test_ecu",
            release_key=OTAReleaseKey.dev,
            image_root=str(tmp_path / "nonexistent"),
            output=str(tmp_path / "file_table.db"),
        )

        with pytest.raises(SystemExit):
            get_filetable_cmd(args)
