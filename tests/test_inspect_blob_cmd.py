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
"""Tests for inspect_blob command module."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_tools.cmds.inspect_blob import (
    _inspect_blob_from_folder,
    _inspect_blob_from_image_artifact,
    inspect_blob_cmd,
    inspect_blob_cmd_args,
)
from tests.conftest import TEST_OTA_IMAGE


@pytest.fixture
def valid_blob_digest(test_artifact: Path) -> str:
    """Get a valid blob digest from the test OTA image."""
    with OTAImageArtifactReader(test_artifact) as reader:
        index = reader.parse_index()
        manifest_descriptor = index.manifests[0]
        return manifest_descriptor.digest.digest_hex


class TestInspectBlobCmdArgs:
    """Tests for argument parser configuration."""

    def test_args_registration(self):
        """Test that inspect-blob command arguments are registered correctly."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        inspect_blob_cmd_args(sub_parser)

        # Parse with required arguments
        args = arg_parser.parse_args(
            ["inspect-blob", "--checksum", "a" * 64, "some_path"]
        )
        assert args.checksum == "a" * 64
        assert args.image_root == "some_path"
        assert hasattr(args, "handler")

    def test_args_with_output_option(self):
        """Test that output option is parsed correctly."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        inspect_blob_cmd_args(sub_parser)

        args = arg_parser.parse_args(
            [
                "inspect-blob",
                "--checksum",
                "a" * 64,
                "--output",
                "/tmp/output.bin",
                "some_path",
            ]
        )
        assert args.output == "/tmp/output.bin"

    def test_args_with_bytes_option(self):
        """Test that bytes option is parsed correctly."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        inspect_blob_cmd_args(sub_parser)

        args = arg_parser.parse_args(
            ["inspect-blob", "--checksum", "a" * 64, "--bytes", "some_path"]
        )
        assert args.bytes is True

    def test_args_checksum_required(self):
        """Test that checksum argument is required."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        inspect_blob_cmd_args(sub_parser)

        with pytest.raises(SystemExit):
            arg_parser.parse_args(["inspect-blob", "some_path"])


class TestInspectBlobFromArtifact:
    """Tests for inspecting blobs from OTA image artifact."""

    def test_inspect_blob_save_to_file(
        self,
        test_artifact: Path,
        valid_blob_digest: str,
        tmp_path: Path,
    ):
        """Test saving blob to a file from artifact."""
        save_dst = tmp_path / "blob_output.bin"

        _inspect_blob_from_image_artifact(
            sha256_digest=valid_blob_digest,
            image_root=test_artifact,
            save_dst=str(save_dst),
            to_bytes=False,
        )

        assert save_dst.exists()
        assert save_dst.stat().st_size > 0

    def test_inspect_blob_as_bytes(self, test_artifact: Path, valid_blob_digest: str):
        """Test printing blob as bytes to stdout."""
        with patch("sys.stdout") as mock_stdout:
            mock_stdout.buffer = mock_stdout
            _inspect_blob_from_image_artifact(
                sha256_digest=valid_blob_digest,
                image_root=test_artifact,
                save_dst=None,
                to_bytes=True,
            )

    def test_inspect_blob_as_text(self, test_artifact: Path, valid_blob_digest: str):
        """Test printing blob as text to stdout."""
        with patch("sys.stdout"):
            _inspect_blob_from_image_artifact(
                sha256_digest=valid_blob_digest,
                image_root=test_artifact,
                save_dst=None,
                to_bytes=False,
            )

    def test_inspect_blob_not_found(self, test_artifact: Path):
        """Test error when blob is not found in artifact."""
        fake_digest = "0" * 64
        with pytest.raises(FileNotFoundError):
            _inspect_blob_from_image_artifact(
                sha256_digest=fake_digest,
                image_root=test_artifact,
                save_dst=None,
                to_bytes=False,
            )


class TestInspectBlobFromFolder:
    """Tests for inspecting blobs from extracted OTA image folder."""

    @pytest.fixture
    def extracted_ota_image(self, tmp_path: Path) -> Path:
        """Extract the test OTA image to a temporary folder."""
        extract_dir = tmp_path / "ota_image"
        with ZipFile(TEST_OTA_IMAGE, "r") as zf:
            zf.extractall(extract_dir)
        return extract_dir

    def test_inspect_blob_save_to_file(
        self, extracted_ota_image: Path, valid_blob_digest: str, tmp_path: Path
    ):
        """Test saving blob to file from folder."""
        save_dst = tmp_path / "blob_output.bin"

        _inspect_blob_from_folder(
            sha256_digest=valid_blob_digest,
            image_root=extracted_ota_image,
            save_dst=str(save_dst),
            to_bytes=False,
        )

        assert save_dst.exists()
        assert save_dst.stat().st_size > 0

    def test_inspect_blob_as_text(
        self, extracted_ota_image: Path, valid_blob_digest: str, capsys
    ):
        """Test printing blob as text from folder."""
        _inspect_blob_from_folder(
            sha256_digest=valid_blob_digest,
            image_root=extracted_ota_image,
            save_dst=None,
            to_bytes=False,
        )

        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_inspect_blob_not_found(self, extracted_ota_image: Path):
        """Test error when blob is not found in folder."""
        fake_digest = "0" * 64

        with pytest.raises(SystemExit):
            _inspect_blob_from_folder(
                sha256_digest=fake_digest,
                image_root=extracted_ota_image,
                save_dst=None,
                to_bytes=False,
            )

    def test_inspect_blob_invalid_folder(self, tmp_path: Path):
        """Test error with invalid OTA image folder."""
        invalid_folder = tmp_path / "invalid"
        invalid_folder.mkdir()

        with pytest.raises(SystemExit):
            _inspect_blob_from_folder(
                sha256_digest="a" * 64,
                image_root=invalid_folder,
                save_dst=None,
                to_bytes=False,
            )


class TestInspectBlobCmd:
    """Tests for the main inspect_blob_cmd handler."""

    @pytest.fixture
    def extracted_ota_image(self, tmp_path: Path) -> Path:
        """Extract the test OTA image to a temporary folder."""
        extract_dir = tmp_path / "ota_image"
        with ZipFile(TEST_OTA_IMAGE, "r") as zf:
            zf.extractall(extract_dir)
        return extract_dir

    def test_cmd_with_artifact(
        self,
        test_artifact: Path,
        valid_blob_digest: str,
        tmp_path: Path,
    ):
        """Test command handler with OTA image artifact."""
        save_dst = tmp_path / "output.bin"
        args = argparse.Namespace(
            checksum=f"sha256:{valid_blob_digest}",
            image_root=str(test_artifact),
            output=str(save_dst),
            bytes=False,
        )

        inspect_blob_cmd(args)

        assert save_dst.exists()

    def test_cmd_with_folder(
        self, extracted_ota_image: Path, valid_blob_digest: str, tmp_path: Path
    ):
        """Test command handler with extracted OTA image folder."""
        save_dst = tmp_path / "output.bin"
        args = argparse.Namespace(
            checksum=f"sha256:{valid_blob_digest}",
            image_root=str(extracted_ota_image),
            output=str(save_dst),
            bytes=False,
        )

        inspect_blob_cmd(args)

        assert save_dst.exists()

    def test_cmd_invalid_checksum(self, test_artifact: Path):
        """Test command handler with invalid checksum format."""
        args = argparse.Namespace(
            checksum="invalid_checksum",
            image_root=str(test_artifact),
            output=None,
            bytes=False,
        )

        with pytest.raises(SystemExit):
            inspect_blob_cmd(args)

    def test_cmd_invalid_path(self, tmp_path: Path):
        """Test command handler with non-existent path."""
        args = argparse.Namespace(
            checksum="sha256:" + "a" * 64,
            image_root=str(tmp_path / "nonexistent"),
            output=None,
            bytes=False,
        )

        with pytest.raises(SystemExit):
            inspect_blob_cmd(args)
