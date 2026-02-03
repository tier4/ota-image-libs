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
"""Tests for inspect_index command module."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from ota_image_tools.cmds.inspect_index import (
    inspect_index_cmd,
    inspect_index_cmd_args,
)
from tests.conftest import TEST_OTA_IMAGE


class TestInspectIndexCmdArgs:
    """Tests for argument parser configuration."""

    def test_args_registration(self):
        """Test that inspect-index command arguments are registered correctly."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        inspect_index_cmd_args(sub_parser)

        args = arg_parser.parse_args(["inspect-index", "some_path"])
        assert args.image_root == "some_path"
        assert hasattr(args, "handler")

    def test_args_image_root_required(self):
        """Test that image_root positional argument is required."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        inspect_index_cmd_args(sub_parser)

        with pytest.raises(SystemExit):
            arg_parser.parse_args(["inspect-index"])


class TestInspectIndexCmdWithArtifact:
    """Tests for inspect_index_cmd with OTA image artifact."""

    def test_inspect_index_from_artifact(self, test_artifact: Path, capsys):
        """Test inspecting index.json from OTA image artifact."""
        args = argparse.Namespace(image_root=str(test_artifact))

        inspect_index_cmd(args)

        captured = capsys.readouterr()
        # Verify the output is valid JSON
        parsed = json.loads(captured.out)
        assert "schemaVersion" in parsed
        assert "manifests" in parsed


class TestInspectIndexCmdWithFolder:
    """Tests for inspect_index_cmd with extracted OTA image folder."""

    @pytest.fixture
    def extracted_ota_image(self, tmp_path: Path) -> Path:
        """Extract the test OTA image to a temporary folder."""
        extract_dir = tmp_path / "ota_image"
        with ZipFile(TEST_OTA_IMAGE, "r") as zf:
            zf.extractall(extract_dir)
        return extract_dir

    def test_inspect_index_from_folder(self, extracted_ota_image: Path, capsys):
        """Test inspecting index.json from extracted OTA image folder."""
        args = argparse.Namespace(image_root=str(extracted_ota_image))

        inspect_index_cmd(args)

        captured = capsys.readouterr()
        # Verify the output is valid JSON
        parsed = json.loads(captured.out)
        assert "schemaVersion" in parsed
        assert "manifests" in parsed

    def test_inspect_index_invalid_folder(self, tmp_path: Path):
        """Test error with invalid OTA image folder (no index.json)."""
        invalid_folder = tmp_path / "invalid"
        invalid_folder.mkdir()

        args = argparse.Namespace(image_root=str(invalid_folder))

        with pytest.raises(SystemExit):
            inspect_index_cmd(args)

    def test_inspect_index_folder_content_matches_artifact(
        self, extracted_ota_image: Path, test_artifact: Path
    ):
        """Test that folder and artifact outputs contain same data."""
        # Get output from artifact
        args_artifact = argparse.Namespace(image_root=str(test_artifact))

        # Capture artifact output
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        inspect_index_cmd(args_artifact)
        artifact_output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        # Get output from folder
        sys.stdout = io.StringIO()
        args_folder = argparse.Namespace(image_root=str(extracted_ota_image))
        inspect_index_cmd(args_folder)
        folder_output = sys.stdout.getvalue()
        sys.stdout = old_stdout

        # Parse both outputs
        artifact_data = json.loads(artifact_output)
        folder_data = json.loads(folder_output)

        # Compare key fields
        assert artifact_data["schemaVersion"] == folder_data["schemaVersion"]
        assert len(artifact_data["manifests"]) == len(folder_data["manifests"])


class TestInspectIndexCmdErrors:
    """Tests for error handling in inspect_index_cmd."""

    def test_invalid_path(self, tmp_path: Path):
        """Test error when path does not exist."""
        args = argparse.Namespace(image_root=str(tmp_path / "nonexistent"))

        with pytest.raises(SystemExit):
            inspect_index_cmd(args)

    def test_invalid_file(self, tmp_path: Path):
        """Test error when file is not a valid OTA image."""
        invalid_file = tmp_path / "invalid.zip"
        with ZipFile(invalid_file, mode="w") as zf:
            zf.writestr("dummy.txt", "not an OTA image")

        args = argparse.Namespace(image_root=str(invalid_file))

        with pytest.raises(KeyError):
            # This should raise KeyError since index.json doesn't exist in archive
            inspect_index_cmd(args)


class TestInspectIndexIntegration:
    """Integration tests for inspect_index command."""

    def test_index_contains_required_fields(self, test_artifact: Path, capsys):
        """Test that the index.json contains all required OCI fields."""
        args = argparse.Namespace(image_root=str(test_artifact))

        inspect_index_cmd(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        # Required OCI image index fields
        assert "schemaVersion" in parsed
        assert parsed["schemaVersion"] == 2
        assert "manifests" in parsed
        assert isinstance(parsed["manifests"], list)

    def test_index_manifests_have_required_fields(self, test_artifact: Path, capsys):
        """Test that manifests in index have required fields."""
        args = argparse.Namespace(image_root=str(test_artifact))

        inspect_index_cmd(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        for manifest in parsed["manifests"]:
            assert "digest" in manifest
            assert "size" in manifest
            assert "mediaType" in manifest
