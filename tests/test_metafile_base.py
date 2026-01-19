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

"""Integration tests for metafile_base module."""

import json

from ota_image_libs.common.metafile_base import MetaFileBase, MetaFileDescriptor
from ota_image_libs.common.model_spec import MediaType, MediaTypeWithAlt

# Create concrete test classes
TEST_METAFILE_MEDIA_TYPE = "application/vnd.test.metafile.v1+json"


class ForTestMetaFile(MetaFileBase):
    """Test MetaFile implementation."""

    MediaType = MediaType[TEST_METAFILE_MEDIA_TYPE]
    test_field: str


INCORRECT_MEDIA_TYPE = "incorrect_media_type"


class ForTestMetaFileWithAltMediaType(MetaFileBase):
    MediaType = MediaTypeWithAlt[TEST_METAFILE_MEDIA_TYPE, INCORRECT_MEDIA_TYPE]
    test_field: str


TEST_MEDIAFILE_DESCRIPTOR_MEDIA_TYPE = "application/vnd.test.metafile.v1+json"


class ForTestMetaFileDescriptor(MetaFileDescriptor[ForTestMetaFile]):
    """Test MetaFileDescriptor implementation."""

    MediaType = MediaType[TEST_MEDIAFILE_DESCRIPTOR_MEDIA_TYPE]


class TestMetaFileDescriptorIntegration:
    def test_export_metafile_to_resource_dir(self, tmp_path):
        """Test exporting metafile to resource directory."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        metafile = ForTestMetaFile(test_field="test_value")

        descriptor = ForTestMetaFileDescriptor.export_metafile_to_resource_dir(
            metafile, resource_dir
        )

        assert descriptor.size > 0
        assert descriptor.digest is not None

        # Verify blob was created
        blob_path = resource_dir / descriptor.digest.digest_hex
        assert blob_path.exists()

        # Verify content
        content = blob_path.read_text()
        parsed = json.loads(content)
        assert parsed["test_field"] == "test_value"

    def test_load_metafile_from_resource_dir(self, tmp_path):
        """Test loading metafile from resource directory."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        metafile = ForTestMetaFile(test_field="test_value")
        descriptor = ForTestMetaFileDescriptor.export_metafile_to_resource_dir(
            metafile, resource_dir
        )

        # Load metafile
        retrieved = descriptor.load_metafile_from_resource_dir(resource_dir)

        assert isinstance(retrieved, ForTestMetaFile)
        assert retrieved.test_field == "test_value"

    def test_metafile_type_resolution(self):
        """Test that metafile_type correctly resolves the type."""
        metafile_type = ForTestMetaFileDescriptor.metafile_type()

        assert metafile_type == ForTestMetaFile

    def test_export_and_retrieve_roundtrip(self, tmp_path):
        """Test full roundtrip of export and retrieve."""
        resource_dir = tmp_path / "resources"
        resource_dir.mkdir()

        original = ForTestMetaFile(test_field="roundtrip_test")

        # Export
        descriptor = ForTestMetaFileDescriptor.export_metafile_to_resource_dir(
            original, resource_dir
        )

        # Load
        retrieved = descriptor.load_metafile_from_resource_dir(resource_dir)

        # Verify data is preserved
        assert retrieved.test_field == original.test_field
        assert retrieved.export_metafile() == original.export_metafile()


class TestMetaFileBase:
    def test_export_metafile_json(self):
        """Test exporting metafile as JSON."""
        metafile = ForTestMetaFile(test_field="json_test")

        exported = metafile.export_metafile()

        assert isinstance(exported, str)
        parsed = json.loads(exported)
        assert parsed["test_field"] == "json_test"
        assert parsed["mediaType"] == "application/vnd.test.metafile.v1+json"

    def test_parse_metafile_json(self):
        """Test parsing metafile from JSON."""
        json_data = json.dumps(
            {
                "mediaType": "application/vnd.test.metafile.v1+json",
                "test_field": "parsed_value",
            }
        )

        metafile = ForTestMetaFile.parse_metafile(json_data)

        assert metafile.test_field == "parsed_value"

    def test_parse_metafile_json_with_media_type_alt(self):
        json_data = json.dumps(
            {
                "mediaType": INCORRECT_MEDIA_TYPE,
                "test_field": "some_value",
            }
        )

        metafile = ForTestMetaFileWithAltMediaType.parse_metafile(json_data)
        assert metafile.test_field == "some_value"

    def test_metafile_has_media_type(self):
        """Test that metafile includes mediaType in export."""
        metafile = ForTestMetaFile(test_field="test")

        exported = metafile.export_metafile()
        parsed = json.loads(exported)

        assert "mediaType" in parsed
        assert parsed["mediaType"] == "application/vnd.test.metafile.v1+json"


# Test YAML support
TEST_YAML_METAFILE_MEDIA_TYPE = "application/vnd.test.metafile.v1+yaml"


class YamlTestMetaFile(MetaFileBase):
    """Test MetaFile with YAML media type."""

    MediaType = MediaType[TEST_YAML_METAFILE_MEDIA_TYPE]

    yaml_field: str
    number_field: int = 42


class TestMetaFileYAMLSupport:
    def test_export_metafile_yaml(self):
        """Test exporting metafile as YAML."""
        metafile = YamlTestMetaFile(yaml_field="yaml_test", number_field=100)

        exported = metafile.export_metafile()

        assert isinstance(exported, str)
        assert "yaml_field: yaml_test" in exported or "yaml_field:" in exported
        assert "mediaType:" in exported

    def test_parse_metafile_yaml(self):
        """Test parsing metafile from YAML."""
        yaml_data = """
mediaType: application/vnd.test.metafile.v1+yaml
yaml_field: parsed_yaml
number_field: 200
"""

        metafile = YamlTestMetaFile.parse_metafile(yaml_data)

        assert metafile.yaml_field == "parsed_yaml"
        assert metafile.number_field == 200

    def test_yaml_roundtrip(self):
        """Test YAML export and parse roundtrip."""
        original = YamlTestMetaFile(yaml_field="roundtrip", number_field=999)

        exported = original.export_metafile()
        parsed = YamlTestMetaFile.parse_metafile(exported)

        assert parsed.yaml_field == original.yaml_field
        assert parsed.number_field == original.number_field


class TestMetaFileExportParseMethods:
    def test_export_metafile_json(self):
        """Test export_metafile method for JSON."""
        metafile = ForTestMetaFile(test_field="export test")

        exported = metafile.export_metafile()

        assert isinstance(exported, str)
        assert "test_field" in exported
        assert "export test" in exported

    def test_parse_metafile_json(self):
        """Test parse_metafile method for JSON."""
        json_data = '{"mediaType": "application/vnd.test.metafile.v1+json", "test_field": "parsed"}'

        metafile = ForTestMetaFile.parse_metafile(json_data)

        assert metafile.test_field == "parsed"
