"""Verify the OTA image resource dir."""

from __future__ import annotations

import logging
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from hashlib import sha256
from pathlib import Path

import zstandard

from ota_image_libs._resource_filter._filter_config import CompressFilter, SliceFilter
from ota_image_libs.v1.image_index.utils import ImageIndexHelper
from ota_image_libs.v1.resource_table.db import ResourceTableDBHelper
from ota_image_libs.v1.resource_table.schema import ResourceTableManifest

IMAGE_ROOT = "test_image_root/ota_image"
WD = "test_ft"


class ChainedFilesIO:
    def __init__(self, slices: list[Path]) -> None:
        self._slices = slices
        self._opened = False
        self._cur_fd = None

    def __enter__(self):
        self._opened_fd = deque([open(_s, "rb") for _s in self._slices])
        self._opened = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._opened:
            for _fd in self._opened_fd:
                _fd.close()
            self._opened = False
            self._opened_fd.clear()
        return False

    def read(self, size: int) -> bytes:
        if not self._opened:
            raise ValueError

        if self._cur_fd is None:
            self._cur_fd = self._opened_fd.popleft()
        _read = self._cur_fd.read(size)
        if len(_read) > 0:
            return _read

        self._cur_fd.close()
        if not self._opened_fd:
            return b""

        self._cur_fd = self._opened_fd.popleft()
        return self._cur_fd.read(size)


class DHelper:
    def __init__(self, orm, resource_dir: Path) -> None:
        self._orm = orm
        self._resource_dir = resource_dir
        self._thread_local = threading.local()

    @property
    def _dctx(self):
        try:
            return self._thread_local.dctx
        except AttributeError:
            dctx = zstandard.ZstdDecompressor()
            self._thread_local.dctx = dctx
            return dctx

    def _do_decompression_at_thread(self, item: ResourceTableManifest):
        filter_applied = item.filter_applied
        assert isinstance(filter_applied, CompressFilter)

        compressed_entry: ResourceTableManifest = self._orm.orm_select_entry(
            resource_id=filter_applied.resource_id
        )
        _filter_applied = compressed_entry.filter_applied
        if _filter_applied is None:
            try:
                hasher = sha256()
                with open(
                    self._resource_dir / compressed_entry.digest.hex(), "rb"
                ) as src_f:
                    for chunk in self._dctx.read_to_iter(src_f, read_size=8 * 1024**2):
                        hasher.update(chunk)
                cal_digest = hasher.digest()
                if cal_digest != item.digest:
                    print(
                        f"ERR: {item=} found mismatch: decompressed {cal_digest.hex()=}, expected {item.digest.hex()=}"
                    )
            except Exception as e:
                logging.error(f"ERR: {item=} {compressed_entry=}: {e}", exc_info=e)
        elif isinstance(_filter_applied, SliceFilter):  # sliced
            try:
                _slice_files = []
                for _sid in _filter_applied.list_resource_id():
                    _s_entry: ResourceTableManifest = self._orm.orm_select_entry(
                        resource_id=_sid
                    )
                    assert _s_entry.filter_applied is None, "???"
                    _slice_files.append(self._resource_dir / _s_entry.digest.hex())

                hasher = sha256()
                with ChainedFilesIO(_slice_files) as _chain_fio:
                    for chunk in self._dctx.read_to_iter(
                        _chain_fio, read_size=8 * 1024**2
                    ):
                        hasher.update(chunk)
                cal_digest = hasher.digest()
                if cal_digest != item.digest:
                    print(
                        f"(sliced) ERR: {item=} found mismatch: decompressed {cal_digest.hex()=}, expected {item.digest.hex()=}"
                    )
                    print(f"{len(_filter_applied.list_resource_id())=}")
            except Exception as e:
                logging.error(
                    f"(sliced) ERR: {item=} {compressed_entry=}: {e}", exc_info=e
                )


def _cb(se, fut: Future):
    se.release()


def main():
    logging.basicConfig(level=logging.INFO)

    index_helper = ImageIndexHelper(Path(IMAGE_ROOT))
    image_index = index_helper.image_index
    image_resource_dir = index_helper.image_resource_dir

    resource_table_d = image_index.image_resource_table
    assert resource_table_d
    rst_dbf = Path(WD) / "resource_table.sqlite3"
    resource_table_d.export_blob_from_resource_dir(
        resource_dir=image_resource_dir, save_dst=rst_dbf, auto_decompress=True
    )

    _db_helper = ResourceTableDBHelper(rst_dbf)
    rst_orm_pool = _db_helper.get_orm_pool(3)
    _helper = DHelper(
        rst_orm_pool,
        image_resource_dir,
    )

    se = threading.Semaphore(64)
    _pcb = partial(_cb, se)

    with ThreadPoolExecutor(max_workers=6) as pool:
        _count = 0
        for item in _db_helper.iter_all_with_shuffle(batch_size=1024):
            if isinstance(item.filter_applied, CompressFilter):
                _count += 1
                if _count % 10000 == 0:
                    print(f"{_count} compressed files are processed ...")
                se.acquire()
                pool.submit(
                    _helper._do_decompression_at_thread, item
                ).add_done_callback(_pcb)
        print(f"a total {_count} of compressed resources are verified")


if __name__ == "__main__":
    main()
