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
"""Tests for get_resourcetable command module."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pytest

from ota_image_tools.cmds.get_resourcetable import (
    _get_resourcetable_from_artifact,
    _get_resourcetable_from_folder,
    get_resourcetable_cmd,
)


class TestGetResourcetableFromArtifact:
    """Tests for extracting resource_table from OTA image artifact."""

    def test_get_resourcetable(self, test_artifact: Path, tmp_path: Path):
        """Test extracting resource_table from artifact produces a valid SQLite database."""
        output = tmp_path / "resource_table.db"

        _get_resourcetable_from_artifact(
            image_root=test_artifact,
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


class TestGetResourcetableFromFolder:
    """Tests for extracting resource_table from extracted OTA image folder."""

    def test_get_resourcetable(self, extracted_ota_image: Path, tmp_path: Path):
        """Test extracting resource_table from folder produces a valid SQLite database."""
        output = tmp_path / "resource_table.db"

        _get_resourcetable_from_folder(
            image_root=extracted_ota_image,
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

    def test_get_resourcetable_invalid_folder(self, tmp_path: Path):
        """Test error with invalid OTA image folder."""
        invalid_folder = tmp_path / "invalid"
        invalid_folder.mkdir()
        output = tmp_path / "resource_table.db"

        with pytest.raises(FileNotFoundError):
            _get_resourcetable_from_folder(
                image_root=invalid_folder,
                output=output,
            )


class TestGetResourcetableCmd:
    """Tests for the main get_resourcetable_cmd handler."""

    def test_cmd_with_artifact(self, test_artifact: Path, tmp_path: Path):
        """Test command handler with OTA image artifact."""
        output = tmp_path / "resource_table.db"
        args = argparse.Namespace(
            image_root=str(test_artifact),
            output=str(output),
        )

        get_resourcetable_cmd(args)

        assert output.exists()

    def test_cmd_with_folder(self, extracted_ota_image: Path, tmp_path: Path):
        """Test command handler with extracted OTA image folder."""
        output = tmp_path / "resource_table.db"
        args = argparse.Namespace(
            image_root=str(extracted_ota_image),
            output=str(output),
        )

        get_resourcetable_cmd(args)

        assert output.exists()

    def test_cmd_invalid_path(self, tmp_path: Path):
        """Test command handler with non-existent path."""
        args = argparse.Namespace(
            image_root=str(tmp_path / "nonexistent"),
            output=str(tmp_path / "resource_table.db"),
        )

        with pytest.raises(SystemExit):
            get_resourcetable_cmd(args)
