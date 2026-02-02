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
"""Libraries for manipulating the OTA image artifact.

Image artifact of OTA Image version 1 is a strict subset of ZIP archive, which has the following constrains:

1. all file entries(blobs) don't have compression via ZIP, stored as plain file(compression is done during OTA image build, not by artifact packing).
2. all file entries have fixed permission bit and datetime set.
3. all file entries have size less than 32MiB (with exceptions when otaclient client update backward compatibility is enabled, but the extra files(otaclient release package) will still be much smaller than 4GiB).
4. the files are arranged in alphabet order.
"""

# some constants that required for making a reproducible artifact build
DEFAULT_TIMESTAMP = (2009, 1, 1, 0, 0, 0)
FILE_PERMISSION = 0o644
DIR_PERMISSION = 0o755
