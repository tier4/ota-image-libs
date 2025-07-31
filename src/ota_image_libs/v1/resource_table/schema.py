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

from typing import Optional, TypedDict

from pydantic import SkipValidation
from simple_sqlite3_orm import (
    ConstrainRepr,
    TableSpec,
    TypeAffinityRepr,
)
from typing_extensions import Annotated

from ota_image_libs._resource_filter import FilterConfig
from ota_image_libs.common.model_spec import MediaType
from ota_image_libs.common.oci_spec import OCIDescriptor
from ota_image_libs.v1.media_types import (
    OTA_IMAGE_RESOURCETABLE,
    OTA_IMAGE_RESOURCETABLE_ZSTD,
)


class ResourceTableDescriptor(OCIDescriptor):
    MediaType = MediaType[OTA_IMAGE_RESOURCETABLE]


class ZstdCompressedResourceTableDescriptor(OCIDescriptor):
    MediaType = MediaType[OTA_IMAGE_RESOURCETABLE_ZSTD]


class ResourceTableManifest(TableSpec):
    resource_id: Annotated[int, ConstrainRepr("PRIMARY KEY"), SkipValidation]
    digest: Annotated[bytes, ConstrainRepr("NOT NULL"), SkipValidation]
    size: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]

    filter_applied: Annotated[Optional[FilterConfig], TypeAffinityRepr(bytes)] = None
    meta: Optional[bytes] = None


class ResourceTableManifestTypedDict(TypedDict, total=False):
    resource_id: int
    digest: bytes
    size: int

    filter_applied: FilterConfig | None
    meta: bytes | None
