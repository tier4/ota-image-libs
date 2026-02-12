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

import random
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Generator

from simple_sqlite3_orm import (
    ORMBase,
    ORMThreadPoolBase,
)
from simple_sqlite3_orm.utils import enable_mmap, enable_wal_mode

from . import RST_MANIFEST_TABLE_NAME
from .schema import ResourceTableManifest

DB_TIMEOUT = 16  # seconds


class _ResourceTableConfig:
    orm_bootstrap_table_name = RST_MANIFEST_TABLE_NAME


class ResourceTableORM(ORMBase[ResourceTableManifest], _ResourceTableConfig):
    orm_bootstrap_table_name = RST_MANIFEST_TABLE_NAME


class ResourceTableORMPool(
    ORMThreadPoolBase[ResourceTableManifest], _ResourceTableConfig
):
    orm_bootstrap_table_name = RST_MANIFEST_TABLE_NAME


class ResourceTableDBHelper:
    def __init__(self, db_f: str | Path) -> None:
        self.db_f = db_f

    def bootstrap_db(self) -> None:
        with closing(self.connect_rstable_db()) as rst_conn:
            orm = ResourceTableORM(rst_conn)
            orm.orm_bootstrap_db()

    def connect_rstable_db(
        self, *, enable_wal: bool = False, enable_mmap_size: int | None = None
    ) -> sqlite3.Connection:
        _conn = sqlite3.connect(self.db_f, check_same_thread=False, timeout=DB_TIMEOUT)
        if enable_wal:
            enable_wal_mode(_conn)
        if enable_mmap_size and enable_mmap_size > 0:
            enable_mmap(_conn, enable_mmap_size)
        return _conn

    def iter_all_with_shuffle(
        self, *, batch_size: int
    ) -> Generator[ResourceTableManifest]:
        """Iter all entries with seek method by rowid, shuffle each batch before yield.

        NOTE: the target table must has rowid defined!
        """
        with closing(self.connect_rstable_db()) as rst_conn:
            orm = ResourceTableORM(rst_conn)
            _this_batch = []
            for _entry in orm.orm_select_entries():
                _this_batch.append(_entry)
                if len(_this_batch) >= batch_size:
                    random.shuffle(_this_batch)
                    yield from _this_batch
                    _this_batch = []
            random.shuffle(_this_batch)
            yield from _this_batch

    def get_orm(self, conn: sqlite3.Connection | None = None) -> ResourceTableORM:
        """Get ORM instance for the resource table."""
        if conn is not None:
            return ResourceTableORM(conn)
        return ResourceTableORM(self.connect_rstable_db())

    def get_orm_pool(self, db_conn_num: int) -> ResourceTableORMPool:
        """Get ORM instance pool for the resource table."""
        return ResourceTableORMPool(
            con_factory=self.connect_rstable_db, number_of_cons=db_conn_num
        )
