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
"""Consts related to OTA image."""

import json

IMAGE_INDEX_FNAME = "index.json"
INDEX_JWT_FNAME = "index.jwt"
RESOURCE_DIR = "blobs/sha256"
OCI_LAYOUT_FNAME = "oci-layout"
OCI_LAYOUT_CONTENT = {"imageLayoutVersion": "1.0.0"}
OCI_LAYOUT_F_CONTENT = json.dumps(OCI_LAYOUT_CONTENT)

ALLOWED_JWT_ALG = "ES256"
SUPPORTED_HASH_ALG = "sha256"

SUPPORTED_COMPRESSION_ALG = ZSTD_COMPRESSION_ALG = "zstd"
