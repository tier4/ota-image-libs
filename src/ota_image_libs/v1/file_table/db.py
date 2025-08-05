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

import contextlib
import sqlite3
import typing
from contextlib import closing
from pathlib import Path
from typing import Callable, Generator, Optional, TypedDict, cast

from simple_sqlite3_orm import (
    AsyncORMBase,
    CreateIndexParams,
    CreateTableParams,
    ORMBase,
    ORMThreadPoolBase,
    gen_sql_stmt,
)
from simple_sqlite3_orm.utils import (
    check_db_integrity,
    enable_mmap,
    enable_wal_mode,
    lookup_table,
    wrap_value,
)

from ota_image_libs.common.model_spec import MsgPackedDict, StrOrPath
from ota_image_libs.v1.media_types import OTA_IMAGE_FILETABLE

from . import (
    FILE_TABLE_FNAME,
    FT_DIR_TABLE_NAME,
    FT_INODE_TABLE_NAME,
    FT_NON_REGULAR_TABLE_NAME,
    FT_REGULAR_TABLE_NAME,
    FT_RESOURCE_TABLE_NAME,
    MEDIA_TYPE_FNAME,
)
from .schema import (
    FileTableDirectories,
    FileTableInode,
    FileTableNonRegularFiles,
    FileTableRegularFiles,
    FileTableResource,
)

#
# ------ Table ORM definitions ------ #
#

# ------ inode table ------ #


class _FileTableInodeTableConfig:
    orm_bootstrap_table_name = FT_INODE_TABLE_NAME
    orm_bootstrap_create_table_params = CreateTableParams(without_rowid=False)


class FileTableInodeORM(ORMBase[FileTableInode], _FileTableInodeTableConfig):
    orm_bootstrap_table_name = FT_INODE_TABLE_NAME


class FileTableInodeORMPool(
    ORMThreadPoolBase[FileTableInode], _FileTableInodeTableConfig
):
    orm_bootstrap_table_name = FT_INODE_TABLE_NAME


class AsyncFileTableInodeORMPool(
    AsyncORMBase[FileTableInode], _FileTableInodeTableConfig
):
    orm_bootstrap_table_name = FT_INODE_TABLE_NAME


# ------ regular file table ------ #


class _FileTableRegularTableConfig:
    orm_bootstrap_table_name = FT_REGULAR_TABLE_NAME
    orm_bootstrap_create_table_params = CreateTableParams(without_rowid=True)
    orm_bootstrap_indexes_params = [
        CreateIndexParams(
            index_name="fr_resource_id_index", index_cols=("resource_id",)
        ),
        CreateIndexParams(index_name="fr_inode_id_index", index_cols=("inode_id",)),
    ]


class FileTableRegularORM(ORMBase[FileTableRegularFiles], _FileTableRegularTableConfig):
    orm_bootstrap_table_name = FT_REGULAR_TABLE_NAME


class FileTableRegularORMPool(
    ORMThreadPoolBase[FileTableRegularFiles], _FileTableRegularTableConfig
):
    orm_bootstrap_table_name = FT_REGULAR_TABLE_NAME


class AsyncFileTableRegularORMPool(
    AsyncORMBase[FileTableRegularFiles], _FileTableRegularTableConfig
):
    orm_bootstrap_table_name = FT_REGULAR_TABLE_NAME


# ------ non-regular file table ------ #


class _FileTableNonRegularTableConfig:
    orm_bootstrap_table_name = FT_NON_REGULAR_TABLE_NAME
    orm_bootstrap_create_table_params = CreateTableParams(without_rowid=True)
    orm_bootstrap_indexes_params = [
        CreateIndexParams(index_name="fnr_inode_id_index", index_cols=("inode_id",)),
    ]


class FileTableNonRegularORM(
    ORMBase[FileTableNonRegularFiles], _FileTableNonRegularTableConfig
):
    orm_bootstrap_table_name = FT_NON_REGULAR_TABLE_NAME


class FileTableNonRegularORMPool(
    ORMThreadPoolBase[FileTableNonRegularFiles], _FileTableNonRegularTableConfig
):
    orm_bootstrap_table_name = FT_NON_REGULAR_TABLE_NAME


class AsyncFileTableNonRegularORMPool(
    AsyncORMBase[FileTableNonRegularFiles], _FileTableNonRegularTableConfig
):
    orm_bootstrap_table_name = FT_NON_REGULAR_TABLE_NAME


# ------ directory table ------ #


class _FileTableDirTableConfig:
    orm_bootstrap_table_name = FT_DIR_TABLE_NAME
    orm_bootstrap_create_table_params = CreateTableParams(without_rowid=True)
    orm_bootstrap_indexes_params = [
        CreateIndexParams(index_name="fd_inode_id_index", index_cols=("inode_id",)),
    ]


class FileTableDirORM(ORMBase[FileTableDirectories], _FileTableDirTableConfig):
    orm_bootstrap_table_name = FT_DIR_TABLE_NAME


class FileTableDirORMPool(
    ORMThreadPoolBase[FileTableDirectories], _FileTableDirTableConfig
):
    orm_bootstrap_table_name = FT_DIR_TABLE_NAME


class AsyncFileTableDirORMPool(
    AsyncORMBase[FileTableDirectories], _FileTableDirTableConfig
):
    orm_bootstrap_table_name = FT_DIR_TABLE_NAME


# ------ resource table ------ #


class _FileTableResourceTableConfig:
    orm_bootstrap_table_name = FT_RESOURCE_TABLE_NAME
    orm_bootstrap_create_table_params = CreateTableParams(without_rowid=False)


class FileTableResourceORM(ORMBase[FileTableResource], _FileTableResourceTableConfig):
    orm_bootstrap_table_name = FT_RESOURCE_TABLE_NAME


class FileTableResourceORMPool(
    ORMThreadPoolBase[FileTableResource], _FileTableResourceTableConfig
):
    orm_bootstrap_table_name = FT_RESOURCE_TABLE_NAME


class AsyncFileTableResourceORMPool(
    AsyncORMBase[FileTableResource], _FileTableResourceTableConfig
):
    orm_bootstrap_table_name = FT_RESOURCE_TABLE_NAME


#
# ------ Helper for operating the file_table DB ------ #
#


class _FileTableEntryTypedDict(TypedDict):
    """The result of joining ft_inode and ft_* table."""

    path: str
    uid: int
    gid: int
    mode: int
    links_count: Optional[int]
    xattrs: Optional[MsgPackedDict]


class RegularFileTypedDict(_FileTableEntryTypedDict):
    digest: bytes
    size: int
    inode_id: int
    contents: Optional[bytes]


class NonRegularFileTypedDict(_FileTableEntryTypedDict):
    meta: Optional[bytes]


class DirTypedDict(TypedDict):
    path: str
    uid: int
    gid: int
    mode: int
    xattrs: Optional[MsgPackedDict]


DB_TIMEOUT = 16  # seconds
MAX_ENTRIES_PER_DIGEST = 16
EMPTY_FILE_SHA256 = r"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
EMPTY_FILE_SHA256_BYTE = bytes.fromhex(EMPTY_FILE_SHA256)


class FileTableDBHelper:
    # NOTE(20250604): filter out the empty file.
    # NOTE(20250724): if the entry is inlined, we don't need to select them.
    ITER_COMMON_DIGEST = gen_sql_stmt(
        f"SELECT base.{FT_REGULAR_TABLE_NAME}.path, base.{FT_RESOURCE_TABLE_NAME}.digest",
        f"FROM base.{FT_REGULAR_TABLE_NAME}",
        f"JOIN base.{FT_RESOURCE_TABLE_NAME} USING(resource_id)",
        f"JOIN {FT_RESOURCE_TABLE_NAME} AS target_rs ON base.{FT_RESOURCE_TABLE_NAME}.digest = target_rs.digest",
        f"WHERE base.{FT_RESOURCE_TABLE_NAME}.digest != {wrap_value(EMPTY_FILE_SHA256_BYTE)} AND target_rs.contents IS NULL"
        f"ORDER BY base.{FT_RESOURCE_TABLE_NAME}.digest",
    )

    def __init__(self, db_f: str | Path) -> None:
        self.db_f = db_f

    def connect_fstable_db(
        self, *, enable_wal: bool = False, enable_mmap_size: int | None = None
    ) -> sqlite3.Connection:
        _conn = sqlite3.connect(self.db_f, check_same_thread=False, timeout=DB_TIMEOUT)
        if enable_wal:
            enable_wal_mode(_conn)
        if enable_mmap_size and enable_mmap_size > 0:
            enable_mmap(_conn, enable_mmap_size)
        return _conn

    def bootstrap_db(self) -> None:
        with closing(self.connect_fstable_db()) as fst_conn:
            ft_regular_orm = FileTableRegularORM(fst_conn)
            ft_regular_orm.orm_bootstrap_db()
            ft_dir_orm = FileTableDirORM(fst_conn)
            ft_dir_orm.orm_bootstrap_db()
            ft_non_regular_orm = FileTableNonRegularORM(fst_conn)
            ft_non_regular_orm.orm_bootstrap_db()
            ft_resource_orm = FileTableResourceORM(fst_conn)
            ft_resource_orm.orm_bootstrap_db()
            ft_inode_orm = FileTableInodeORM(fst_conn)
            ft_inode_orm.orm_bootstrap_db()

    def iter_dir_entries(self) -> Generator[DirTypedDict]:
        with FileTableDirORM(self.connect_fstable_db()) as orm:
            _row_factory = typing.cast(Callable[..., DirTypedDict], sqlite3.Row)

            # fmt: off
            yield from orm.orm_select_entries(
                _row_factory=_row_factory,
                _stmt = gen_sql_stmt(
                    "SELECT", "path,uid,gid,mode,xattrs",
                    "FROM", FT_DIR_TABLE_NAME,
                    "JOIN", FT_INODE_TABLE_NAME, "USING", "(inode_id)",
                )
            )
            # fmt: on

    def iter_regular_entries(self) -> Generator[RegularFileTypedDict]:
        with FileTableRegularORM(self.connect_fstable_db()) as orm:
            # fmt: off
            _stmt = gen_sql_stmt(
                "SELECT", "path,uid,gid,mode,links_count,xattrs,digest,size,contents,inode_id",
                "FROM", FT_REGULAR_TABLE_NAME,
                "JOIN", FT_INODE_TABLE_NAME, "USING(inode_id)",
                "JOIN", FT_RESOURCE_TABLE_NAME, "USING(resource_id)",
                "ORDER BY", "digest"
            )
            # fmt: on
            yield from orm.orm_select_entries(
                _stmt=_stmt,
                _row_factory=cast("Callable[..., RegularFileTypedDict]", sqlite3.Row),
            )

    def iter_non_regular_entries(self) -> Generator[NonRegularFileTypedDict]:
        with FileTableNonRegularORM(self.connect_fstable_db()) as orm:
            # fmt: off
            yield from orm.orm_select_entries(
                _row_factory=typing.cast(
                    Callable[..., NonRegularFileTypedDict], sqlite3.Row
                ),
                _stmt=gen_sql_stmt(
                    "SELECT", "path,uid,gid,mode,xattrs,meta",
                    "FROM", FT_NON_REGULAR_TABLE_NAME,
                    "JOIN", FT_INODE_TABLE_NAME, "USING", "(inode_id)",
                )
            )
            # fmt: on

    def iter_common_regular_entries_by_digest(
        self,
        base_file_table: str,
        *,
        max_num_of_entries_per_digest: int = MAX_ENTRIES_PER_DIGEST,
    ) -> Generator[tuple[bytes, list[Path]]]:
        _hash = b""
        _cur: list[Path] = []

        with FileTableRegularORM(self.connect_fstable_db()) as orm:
            orm.orm_con.execute(f"ATTACH DATABASE '{base_file_table}' AS base;")
            for entry in orm.orm_select_entries(
                _stmt=self.ITER_COMMON_DIGEST,
                _row_factory=sqlite3.Row,
            ):
                _this_digest: bytes = entry["digest"]
                _this_path: Path = Path(entry["path"])

                if _this_digest == _hash:
                    # When there are too many entries for this digest, just pick the first
                    #   <max_num_of_entries_per_digest> of them.
                    if len(_cur) <= max_num_of_entries_per_digest:
                        _cur.append(_this_path)
                else:
                    if _cur:
                        yield _hash, _cur
                    _hash, _cur = _this_digest, [_this_path]

            if _cur:
                yield _hash, _cur

    def get_dir_orm_pool(self, db_conn_num: int) -> FileTableDirORMPool:
        return FileTableDirORMPool(
            con_factory=self.connect_fstable_db,
            number_of_cons=db_conn_num,
        )

    def get_dir_orm(self, conn: sqlite3.Connection | None = None) -> FileTableDirORM:
        if conn is not None:
            return FileTableDirORM(conn)
        return FileTableDirORM(self.connect_fstable_db())

    def get_regular_file_orm_pool(self, db_conn_num: int) -> FileTableDirORMPool:
        return FileTableDirORMPool(
            con_factory=self.connect_fstable_db, number_of_cons=db_conn_num
        )

    def get_regular_file_orm(
        self, conn: sqlite3.Connection | None = None
    ) -> FileTableRegularORM:
        if conn is not None:
            return FileTableRegularORM(conn)
        return FileTableRegularORM(self.connect_fstable_db())

    def get_non_regular_file_orm_pool(
        self, db_conn_num: int
    ) -> FileTableRegularORMPool:
        return FileTableRegularORMPool(
            con_factory=self.connect_fstable_db, number_of_cons=db_conn_num
        )

    def get_non_regular_file_orm(
        self, conn: sqlite3.Connection | None = None
    ) -> FileTableNonRegularORM:
        if conn is not None:
            return FileTableNonRegularORM(conn)
        return FileTableNonRegularORM(self.connect_fstable_db())

    def get_inode_orm(
        self, conn: sqlite3.Connection | None = None
    ) -> FileTableInodeORM:
        if conn is not None:
            return FileTableInodeORM(conn)
        return FileTableInodeORM(self.connect_fstable_db())

    def get_resource_orm(
        self, conn: sqlite3.Connection | None = None
    ) -> FileTableResourceORM:
        if conn is not None:
            return FileTableResourceORM(conn)
        return FileTableResourceORM(self.connect_fstable_db())

    # APIs for saving and loading file_table to/from OTA image metadata directory.
    #
    # ------ OTA image file_table storage protocol ------ #
    #
    # The file_table is saved to the target directory as follow:
    #   <dst>/
    #       ├── file_table.sqlite3
    #       └── mediaType
    #

    @staticmethod
    def _check_base_filetable(db_f: StrOrPath) -> StrOrPath:
        with contextlib.closing(
            sqlite3.connect(f"file:{db_f}?mode=ro&immutable=1", uri=True)
        ) as con:
            try:
                if not check_db_integrity(con):
                    raise ValueError(f"{db_f} fails integrity check")

                if not (
                    lookup_table(con, FT_REGULAR_TABLE_NAME)
                    and lookup_table(con, FT_RESOURCE_TABLE_NAME)
                ):
                    raise ValueError(
                        f"{db_f} presented, but either ft_regular or ft_resource tables missing"
                    )
            except sqlite3.Error as e:
                raise ValueError(f"{db_f} might be broken: {e}") from e

        try:
            with contextlib.closing(sqlite3.connect(":memory:")) as con:
                con.execute(f"ATTACH '{db_f}' AS attach_test;")
                return db_f
        except Exception as e:
            raise ValueError(
                f"{db_f} is valid, but cannot be attached: {e!r}, skip"
            ) from e

    def save_fstable(
        self,
        dst_dir: StrOrPath,
        *,
        saved_name=FILE_TABLE_FNAME,
        media_type=OTA_IMAGE_FILETABLE,
        media_type_fname=MEDIA_TYPE_FNAME,
    ) -> None:
        """Save the <db_f> to <dst>, with image-meta save layout."""

        dst_dir = Path(dst_dir)
        dst_dir.mkdir(exist_ok=True, parents=True)

        with contextlib.closing(
            self.connect_fstable_db()
        ) as _fs_conn, contextlib.closing(
            sqlite3.connect(dst_dir / saved_name)
        ) as _dst_conn:
            with _dst_conn as conn:
                _fs_conn.backup(conn)

        media_type_f = dst_dir / media_type_fname
        media_type_f.write_text(media_type)

    @classmethod
    def find_saved_fstable(cls, image_meta_dir: StrOrPath) -> Path:
        """Find and validate saved file_table in <image_meta_dir>.

        Raises:
            ValueError if the the target directory is not a image_meta dir.
            FileNotFoundError if the file_table is not found.

        Returns:
            Return the file_table database fpath if it is a valid file_table.
        """
        image_meta_dir = Path(image_meta_dir)
        media_type_f = image_meta_dir / MEDIA_TYPE_FNAME

        if not (
            media_type_f.is_file() and media_type_f.read_text() == OTA_IMAGE_FILETABLE
        ):
            raise ValueError(
                f"{MEDIA_TYPE_FNAME} not found under {image_meta_dir=}, "
                f"or mediaType is unsupported (supported type: {OTA_IMAGE_FILETABLE=})"
            )

        db_f = image_meta_dir / FILE_TABLE_FNAME
        if not db_f.is_file():
            raise FileNotFoundError(f"{db_f} not found under {image_meta_dir=}")

        cls._check_base_filetable(db_f)
        return db_f
