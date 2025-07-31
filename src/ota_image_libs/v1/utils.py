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

from __future__ import annotations

import json
import logging
from pathlib import Path

from ota_image_libs.v1.consts import (
    IMAGE_INDEX_FNAME,
    OCI_LAYOUT_CONTENT,
    OCI_LAYOUT_FNAME,
    RESOURCE_DIR,
)

logger = logging.getLogger(__name__)


def check_if_valid_ota_image(image_root: Path) -> bool:
    """Check if the given path holds a valid OTA image.

    Args:
        image_root (Path): The path to the OTA image directory.

    Returns:
        bool: True if valid, False otherwise.
    """
    oci_layout_f = image_root / OCI_LAYOUT_FNAME
    if not oci_layout_f.is_file():
        logger.error(f"OCI layout file not found: {oci_layout_f}")
        return False

    oci_layout_f_content = json.loads(oci_layout_f.read_text())
    if oci_layout_f_content != OCI_LAYOUT_CONTENT:
        logger.error(f"Invalid OCI layout content: {oci_layout_f_content}")
        return False

    index_f = image_root / IMAGE_INDEX_FNAME
    if not index_f.is_file():
        logger.error(f"Image index file not found: {index_f}")
        return False
    # NOTE: let image_index related functions to check if the index file is valid

    resource_dir = image_root / RESOURCE_DIR
    if not resource_dir.is_dir():
        logger.error(f"Resource directory not found: {resource_dir}")
        return False
    return True
