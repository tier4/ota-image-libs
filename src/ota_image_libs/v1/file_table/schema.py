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

from typing import Annotated, Optional, TypedDict

from pydantic import SkipValidation
from simple_sqlite3_orm import (
    ConstrainRepr,
    TableSpec,
    TypeAffinityRepr,
)

from ota_image_libs.common.model_spec import MediaType, MsgPackedDict
from ota_image_libs.common.oci_spec import OCIDescriptor
from ota_image_libs.v1.media_types import OTA_IMAGE_FILETABLE, OTA_IMAGE_FILETABLE_ZSTD


class FileTableDescriptor(OCIDescriptor):
    MediaType = MediaType[OTA_IMAGE_FILETABLE]


class ZstdCompressedFileTableDescriptor(OCIDescriptor):
    MediaType = MediaType[OTA_IMAGE_FILETABLE_ZSTD]


#
# ------ Table definitions for file_table database ------ #
#

# ------ inode table ------ #


class FileTableInode(TableSpec):
    inode_id: Annotated[int, ConstrainRepr("PRIMARY KEY"), SkipValidation]
    uid: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]
    gid: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]
    mode: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]
    links_count: Annotated[Optional[int], SkipValidation] = None
    xattrs: Annotated[Optional[MsgPackedDict], TypeAffinityRepr(bytes)] = None


class FiletableInodeTypedDict(TypedDict, total=False):
    inode_id: int
    uid: int
    gid: int
    mode: int
    links_count: Optional[int]
    xattrs: Optional[MsgPackedDict]


# ------ regular file table ------ #


class FileTableRegularFiles(TableSpec):
    """DB table for regular file entries."""

    path: Annotated[str, ConstrainRepr("PRIMARY KEY"), SkipValidation]
    inode_id: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]
    resource_id: Annotated[int, SkipValidation]


class FileTableRegularTypedDict(TypedDict, total=False):
    path: str
    inode_id: int
    resource_id: int


# ------ non-regular file table ------ #


class FileTableNonRegularFiles(TableSpec):
    """DB table for non-regular file entries.

    This includes:
    1. symlink.
    2. chardev file.

    NOTE that support for chardev file is only for overlayfs' whiteout file,
        so only device num as 0,0 will be allowed.
    NOTE: chardev is not supported by legacy OTA image, so just ignore it.
    """

    path: Annotated[str, ConstrainRepr("PRIMARY KEY"), SkipValidation]
    inode_id: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]
    meta: Annotated[Optional[bytes], SkipValidation] = None
    """The contents of the file. Currently only used by symlink."""


class FileTableNonRegularTypedDict(TypedDict, total=False):
    path: str
    inode_id: int
    meta: Optional[bytes]


# ------ directory table ------ #


class FileTableDirectories(TableSpec):
    path: Annotated[str, ConstrainRepr("PRIMARY KEY"), SkipValidation]
    inode_id: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]


class FileTableDirectoryTypedDict(TypedDict, total=False):
    path: str
    inode_id: int


# ------ resource table ------ #


class FileTableResource(TableSpec):
    resource_id: Annotated[int, ConstrainRepr("PRIMARY KEY"), SkipValidation]
    digest: Annotated[bytes, ConstrainRepr("NOT NULL", "UNIQUE"), SkipValidation]
    size: Annotated[int, ConstrainRepr("NOT NULL"), SkipValidation]
    contents: Annotated[Optional[bytes], SkipValidation] = None


class FileTableResourceTypedDict(TypedDict, total=False):
    resource_id: int
    digest: bytes
    size: int
    contents: Optional[bytes]
