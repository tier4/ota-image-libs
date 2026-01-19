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

import pytest
from pydantic import BaseModel

from ota_image_libs.common import MsgPackedDict
from ota_image_libs.common.msgpack_utils import pack_obj


class TestMsgPackedDict:
    def test_msgpacked_dict_basic(self):
        """Test basic MsgPackedDict creation and serialization."""
        test_dict = {"key1": b"value1", "key2": b"value2"}
        packed_dict = MsgPackedDict(test_dict)

        assert packed_dict["key1"] == b"value1"
        assert packed_dict["key2"] == b"value2"

    def test_msgpacked_dict_bytes_schema_validator(self):
        """Test MsgPackedDict.bytes_schema_validator."""
        test_dict = {"key1": b"value1", "key2": b"value2"}
        packed_bytes = pack_obj(test_dict)

        result = MsgPackedDict.bytes_schema_validator(packed_bytes)

        assert isinstance(result, MsgPackedDict)
        assert result["key1"] == b"value1"
        assert result["key2"] == b"value2"

    def test_msgpacked_dict_bytes_schema_serializer(self):
        """Test MsgPackedDict.bytes_schema_serializer."""
        test_dict = {"key1": b"value1", "key2": b"value2"}
        packed_dict = MsgPackedDict(test_dict)

        result = packed_dict.bytes_schema_serializer()

        assert isinstance(result, bytes)
        # Verify it can be unpacked back
        repacked = MsgPackedDict.bytes_schema_validator(result)
        assert repacked == packed_dict

    def test_msgpacked_dict_invalid_bytes(self):
        """Test MsgPackedDict with invalid bytes."""
        invalid_bytes = b"not valid msgpack"

        with pytest.raises(ValueError):
            MsgPackedDict.bytes_schema_validator(invalid_bytes)

    def test_msgpacked_dict_non_bytes_values(self):
        """Test MsgPackedDict with non-bytes values."""
        test_dict = {"key1": "string_value"}
        packed_bytes = pack_obj(test_dict)

        with pytest.raises(ValueError):
            MsgPackedDict.bytes_schema_validator(packed_bytes)


class TestPydanticIntegration:
    def test_msgpacked_dict_in_pydantic_model(self):
        """Test using MsgPackedDict in a Pydantic model."""

        class TestModel(BaseModel):
            data: MsgPackedDict

        test_dict = {"key1": b"value1", "key2": b"value2"}
        packed_bytes = pack_obj(test_dict)

        # Test from bytes
        model = TestModel.model_validate({"data": packed_bytes})
        assert isinstance(model.data, MsgPackedDict)
        assert model.data["key1"] == b"value1"

        # Test serialization
        serialized = model.model_dump()
        assert "data" in serialized
