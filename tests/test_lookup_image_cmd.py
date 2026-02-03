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
"""Tests for lookup_image command module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from ota_image_libs.v1.artifact.reader import OTAImageArtifactReader
from ota_image_libs.v1.image_manifest.schema import (
    ImageIdentifier,
    ImageManifest,
    OTAReleaseKey,
)
from ota_image_tools.cmds.lookup_image import (
    _lookup_image_from_artifact,
    _lookup_image_from_folder,
    lookup_image_cmd,
    lookup_image_cmd_args,
)
from tests.conftest import TEST_OTA_IMAGE


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


class TestLookupImageCmdArgs:
    """Tests for argument parser configuration."""

    def test_args_registration(self):
        """Test that lookup-image command arguments are registered correctly."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        lookup_image_cmd_args(sub_parser)

        args = arg_parser.parse_args(
            ["lookup-image", "--ecu-id", "test_ecu", "some_path"]
        )
        assert args.ecu_id == "test_ecu"
        assert args.image_root == "some_path"
        assert hasattr(args, "handler")

    def test_args_ecu_id_required(self):
        """Test that ecu-id argument is required."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        lookup_image_cmd_args(sub_parser)

        with pytest.raises(SystemExit):
            arg_parser.parse_args(["lookup-image", "some_path"])

    def test_args_release_key_default(self):
        """Test that release-key defaults to 'dev'."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        lookup_image_cmd_args(sub_parser)

        args = arg_parser.parse_args(
            ["lookup-image", "--ecu-id", "test_ecu", "some_path"]
        )
        assert args.release_key == OTAReleaseKey.dev.value

    def test_args_release_key_prd(self):
        """Test that release-key can be set to 'prd'."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        lookup_image_cmd_args(sub_parser)

        args = arg_parser.parse_args(
            [
                "lookup-image",
                "--ecu-id",
                "test_ecu",
                "--release-key",
                "prd",
                "some_path",
            ]
        )
        assert args.release_key == OTAReleaseKey.prd.value

    def test_args_image_config_flag(self):
        """Test that image-config flag is parsed correctly."""
        arg_parser = argparse.ArgumentParser()
        sub_parser = arg_parser.add_subparsers()

        lookup_image_cmd_args(sub_parser)

        args = arg_parser.parse_args(
            ["lookup-image", "--ecu-id", "test_ecu", "--image-config", "some_path"]
        )
        assert args.image_config is True


class TestLookupImageFromArtifact:
    """Tests for looking up images from OTA image artifact."""

    def test_lookup_image_manifest(
        self,
        test_artifact: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test looking up image manifest from artifact."""
        image_id = ImageIdentifier(ecu_id=valid_ecu_id, release_key=valid_release_key)

        _lookup_image_from_artifact(
            image_root=test_artifact,
            image_id=image_id,
            show_image_config=False,
        )

        captured = capsys.readouterr()
        # Verify the output is valid JSON
        parsed = json.loads(captured.out)
        assert "config" in parsed
        assert "layers" in parsed

    def test_lookup_image_config(
        self,
        test_artifact: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test looking up image config from artifact."""
        image_id = ImageIdentifier(ecu_id=valid_ecu_id, release_key=valid_release_key)

        _lookup_image_from_artifact(
            image_root=test_artifact,
            image_id=image_id,
            show_image_config=True,
        )

        captured = capsys.readouterr()
        # Output should contain image config info
        assert len(captured.out) > 0

    def test_lookup_image_not_found(self, test_artifact: Path):
        """Test error when image is not found in artifact."""
        image_id = ImageIdentifier(
            ecu_id="nonexistent_ecu", release_key=OTAReleaseKey.dev
        )

        with pytest.raises(AssertionError):
            _lookup_image_from_artifact(
                image_root=test_artifact,
                image_id=image_id,
                show_image_config=False,
            )


class TestLookupImageFromFolder:
    """Tests for looking up images from extracted OTA image folder."""

    @pytest.fixture
    def extracted_ota_image(self, tmp_path: Path) -> Path:
        """Extract the test OTA image to a temporary folder."""
        extract_dir = tmp_path / "ota_image"
        with ZipFile(TEST_OTA_IMAGE, "r") as zf:
            zf.extractall(extract_dir)
        return extract_dir

    def test_lookup_image_manifest(
        self,
        extracted_ota_image: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test looking up image manifest from folder."""
        image_id = ImageIdentifier(ecu_id=valid_ecu_id, release_key=valid_release_key)

        _lookup_image_from_folder(
            image_root=extracted_ota_image,
            image_id=image_id,
            show_image_config=False,
        )

        captured = capsys.readouterr()
        # Verify the output is valid JSON
        parsed = json.loads(captured.out)
        assert "config" in parsed
        assert "layers" in parsed

    def test_lookup_image_config(
        self,
        extracted_ota_image: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test looking up image config from folder."""
        image_id = ImageIdentifier(ecu_id=valid_ecu_id, release_key=valid_release_key)

        _lookup_image_from_folder(
            image_root=extracted_ota_image,
            image_id=image_id,
            show_image_config=True,
        )

        captured = capsys.readouterr()
        # Output should contain image config info
        assert len(captured.out) > 0

    def test_lookup_image_not_found(self, extracted_ota_image: Path):
        """Test error when image is not found in folder."""
        image_id = ImageIdentifier(
            ecu_id="nonexistent_ecu", release_key=OTAReleaseKey.dev
        )

        with pytest.raises(SystemExit):
            _lookup_image_from_folder(
                image_root=extracted_ota_image,
                image_id=image_id,
                show_image_config=False,
            )

    def test_lookup_image_invalid_folder(self, tmp_path: Path):
        """Test error with invalid OTA image folder."""
        invalid_folder = tmp_path / "invalid"
        invalid_folder.mkdir()

        image_id = ImageIdentifier(ecu_id="test_ecu", release_key=OTAReleaseKey.dev)

        with pytest.raises(SystemExit):
            _lookup_image_from_folder(
                image_root=invalid_folder,
                image_id=image_id,
                show_image_config=False,
            )


class TestLookupImageCmd:
    """Tests for the main lookup_image_cmd handler."""

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
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test command handler with OTA image artifact."""
        args = argparse.Namespace(
            ecu_id=valid_ecu_id,
            release_key=valid_release_key,
            image_root=str(test_artifact),
            image_config=False,
        )

        lookup_image_cmd(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "config" in parsed

    def test_cmd_with_folder(
        self,
        extracted_ota_image: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test command handler with extracted OTA image folder."""
        args = argparse.Namespace(
            ecu_id=valid_ecu_id,
            release_key=valid_release_key,
            image_root=str(extracted_ota_image),
            image_config=False,
        )

        lookup_image_cmd(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "config" in parsed

    def test_cmd_invalid_path(self, tmp_path: Path):
        """Test command handler with non-existent path."""
        args = argparse.Namespace(
            ecu_id="test_ecu",
            release_key=OTAReleaseKey.dev,
            image_root=str(tmp_path / "nonexistent"),
            image_config=False,
        )

        with pytest.raises(SystemExit):
            lookup_image_cmd(args)


class TestLookupImageIntegration:
    """Integration tests for lookup_image command."""

    def test_manifest_contains_required_fields(
        self,
        test_artifact: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test that the returned manifest contains required fields."""
        args = argparse.Namespace(
            ecu_id=valid_ecu_id,
            release_key=valid_release_key,
            image_root=str(test_artifact),
            image_config=False,
        )

        lookup_image_cmd(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        # Required OCI image manifest fields
        assert "schemaVersion" in parsed
        assert "mediaType" in parsed
        assert "config" in parsed
        assert "layers" in parsed
        assert "annotations" in parsed

    def test_config_has_digest_info(
        self,
        test_artifact: Path,
        valid_ecu_id: str,
        valid_release_key: OTAReleaseKey,
        capsys,
    ):
        """Test that config section has digest information."""
        args = argparse.Namespace(
            ecu_id=valid_ecu_id,
            release_key=valid_release_key,
            image_root=str(test_artifact),
            image_config=False,
        )

        lookup_image_cmd(args)

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)

        assert "digest" in parsed["config"]
        assert "size" in parsed["config"]
        assert "mediaType" in parsed["config"]
