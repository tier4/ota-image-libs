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
"""Common shared utils and libs for parsing and generating OTA images metadata."""

from ._common import tmp_fname
from .metafile_base import MetaFileBase, MetaFileDescriptor
from .model_fields import ConstFieldMeta
from .model_spec import (
    AliasEnabledModel,
    MediaType,
    MsgPackedDict,
    SchemaVersion,
)
from .oci_spec import OCIDescriptor, Sha256Digest

__all__ = [
    "AliasEnabledModel",
    "MetaFileBase",
    "SchemaVersion",
    "MediaType",
    "MsgPackedDict",
    "OCIDescriptor",
    "MetaFileDescriptor",
    "Sha256Digest",
    "ConstFieldMeta",
    "tmp_fname",
]
