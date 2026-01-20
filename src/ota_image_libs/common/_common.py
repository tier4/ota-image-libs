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

import os
from typing import Any

from pydantic import ValidationInfo

DEFAULT_TMP_FNAME_PREFIX = "tmp"


def tmp_fname(
    hint: str = "",
    prefix: str = DEFAULT_TMP_FNAME_PREFIX,
    suffix: str = "",
    sep: str = "_",
    *,
    random_bytes: int = 4,
) -> str:
    return f"{prefix}{sep}{hint}{sep}{os.urandom(random_bytes).hex()}{suffix}"


def oci_descriptor_before_validator(cls: Any, data: Any, info: ValidationInfo) -> Any:
    """Validate external input, like parsing meta files."""
    assert isinstance(data, dict)
    if info.mode == "json":
        # bypass descriptor protocol
        # NOTE(20260119): we only respect the `SchemaVersion` and `MediaType`
        #   set for the current class, and must not looking throught to parent class.
        if _schema_ver_checker := cls.__dict__.get("SchemaVersion"):
            _schema_ver_checker.validate(data.get("schemaVersion"))
        if _media_type_checker := cls.__dict__.get("MediaType"):
            _media_type_checker.validate(data.get("mediaType"))
    return data


metafile_before_validator = oci_descriptor_before_validator
