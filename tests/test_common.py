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

from ota_image_libs.common._common import tmp_fname


class TestTmpFname:
    def test_tmp_fname_all_parameters(self):
        """Test tmp_fname with all parameters."""
        result = tmp_fname(
            hint="test", prefix="pre", suffix=".log", sep="-", random_bytes=6
        )

        assert result.startswith("pre-")
        assert "test" in result
        assert result.endswith(".log")
        # 6 bytes = 12 hex characters
        parts = result.replace(".log", "").split("-")
        assert len(parts[-1]) == 12
