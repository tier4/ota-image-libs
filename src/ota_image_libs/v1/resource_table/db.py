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

import logging
import random
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Generator

import zstandard
from simple_sqlite3_orm import (
    CreateIndexParams,
    ORMBase,
    ORMThreadPoolBase,
)
from simple_sqlite3_orm.utils import enable_mmap, enable_wal_mode

from ota_image_libs._resource_filter import (
    BundleFilter,
    CompressFilter,
    SliceFilter,
)
from ota_image_libs.common import tmp_fname

from . import RST_MANIFEST_TABLE_NAME
from .schema import ResourceTableManifest
from .utils import (
    recreate_bundled_resource,
    recreate_sliced_resource,
    recreate_zstd_compressed_resource,
)

logger = logging.getLogger(__name__)

DB_TIMEOUT = 16  # seconds


class _ResourceTableConfig:
    orm_bootstrap_table_name = RST_MANIFEST_TABLE_NAME
    orm_bootstrap_indexes_params = [
        CreateIndexParams(index_name="rst_digest_idx", index_cols=("digest",))
    ]


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


class PrepareResourceHelper:
    """Helper for processing resouces.

    This class is for multi-threads use.
    """

    def __init__(
        self,
        orm_pool: ResourceTableORMPool,
        *,
        resource_dir: Path,
        download_tmp_dir: Path,
    ):
        self._orm_pool = orm_pool
        self._resource_dir = resource_dir
        self._tmp_dir = download_tmp_dir

        # for bundled entries, only allow one task to actually rebuild the bundle,
        self._bundle_process_lock = threading.Lock()
        self._bundle: dict[int, Path] = {}

        self._thread_local = threading.local()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._orm_pool.orm_pool_shutdown()
        return False

    @property
    def _thread_local_dctx(self) -> zstandard.ZstdDecompressor:
        # NOTE: should access the thread_local directly by self._thread_local
        try:
            return self._thread_local.dctx
        except AttributeError:
            dctx = zstandard.ZstdDecompressor()
            self._thread_local.dctx = dctx
            return dctx

    def _prepare_bundled_resource(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[tuple[str, Path]]:
        assert isinstance(entry.filter_applied, BundleFilter)
        # NOTE: prevent the same bundle being prepared again and again
        with self._bundle_process_lock:
            bundle_rsid = entry.filter_applied.list_resource_id()
            if bundle_rsid not in self._bundle:
                bundle_entry = self._orm_pool.orm_select_entry(resource_id=bundle_rsid)
                logger.debug(f"Requesting bundle({bundle_rsid=}): {bundle_entry}")
                bundle_save_dst = self._tmp_dir / tmp_fname(str(bundle_rsid))
                yield from self._prepare_resource(bundle_entry, bundle_save_dst)
                self._bundle[bundle_rsid] = bundle_save_dst

        # NOTE: keep the bundle for later use
        recreate_bundled_resource(entry, self._bundle[bundle_rsid], save_dst)

    def _prepare_compressed_resources(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[tuple[str, Path]]:
        assert isinstance(entry.filter_applied, CompressFilter)
        compressed_rsid = entry.filter_applied.list_resource_id()
        compressed_entry = self._orm_pool.orm_select_entry(resource_id=compressed_rsid)
        compressed_save_dst = self._tmp_dir / tmp_fname(str(compressed_rsid))
        yield from self._prepare_resource(compressed_entry, compressed_save_dst)
        try:
            recreate_zstd_compressed_resource(
                entry, compressed_save_dst, save_dst, dctx=self._thread_local_dctx
            )
        except Exception as e:
            logger.error(f"Failure during decompressing: {entry}: {e}", exc_info=e)
            raise

        compressed_save_dst.unlink(missing_ok=True)

    def _prepare_slided_resources(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[tuple[str, Path]]:
        assert isinstance(entry.filter_applied, SliceFilter)
        slices_rsid = entry.filter_applied.list_resource_id()
        _slices_fpath: list[Path] = []
        for _rsid in slices_rsid:
            _slice_entry: ResourceTableManifest = self._orm_pool.orm_select_entry(
                resource_id=_rsid
            )
            _slice_save_dst = self._tmp_dir / tmp_fname(str(_rsid))
            _slices_fpath.append(_slice_save_dst)
            # NOTE: slice SHOULD NOT be filtered again, it MUST be the leaves in the resource
            #       filter applying tree.
            assert _slice_entry.filter_applied is None
            yield (_slice_entry.digest.hex(), _slice_save_dst)
        recreate_sliced_resource(entry, _slices_fpath, save_dst)

        # after recovering the target resource, cleanup the slices
        for _slice in _slices_fpath:
            _slice.unlink(missing_ok=True)

    def _prepare_resource(
        self, entry: ResourceTableManifest, save_dst: Path
    ) -> Generator[tuple[str, Path]]:
        filter_applied = entry.filter_applied
        if filter_applied is None:  # reaching the leaf
            yield (entry.digest.hex(), save_dst)
        elif isinstance(filter_applied, BundleFilter):
            yield from self._prepare_bundled_resource(entry, save_dst)
        elif isinstance(filter_applied, CompressFilter):
            yield from self._prepare_compressed_resources(entry, save_dst)
        elif isinstance(filter_applied, SliceFilter):
            yield from self._prepare_slided_resources(entry, save_dst)
        else:
            raise NotImplementedError

    def prepare_resource_at_thread(
        self, digest: bytes
    ) -> tuple[ResourceTableManifest, Generator[tuple[str, Path]]]:
        """Prepare resource for the given digest.

        NOTE that the `resource_id` in the resource_table is NOT the same as
            `resource_id` in the file_table!

        This method guides the caller to download all the needed resources to get the
        resource with the given digest. For example, if the resource is a
        compressed archive, it may require the caller to download the archive.

        Raises:
            Raises ValueError when the requested digest is not found in the db.
        """
        target_entry = self._orm_pool.orm_select_entry(digest=digest)
        if target_entry is None:
            raise ValueError(
                f"resource with {digest.hex()} is not found in the rs_table!"
            )

        def _gen():
            yield from self._prepare_resource(
                target_entry, self._resource_dir / digest.hex()
            )

        return target_entry, _gen()
