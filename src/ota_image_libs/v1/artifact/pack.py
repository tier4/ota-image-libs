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
"""Helper functions for packing OTA image artifact.

NOTE that only for this module, python 3.11 and newer is required.
This is not a problem, as the expected user of this lib, the ota-image-builder,
    is pinned to python 3.13.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from ota_image_libs.v1.artifact import (
    DEFAULT_TIMESTAMP,
    DIR_PERMISSION,
    FILE_PERMISSION,
)
from ota_image_libs.v1.consts import IMAGE_INDEX_FNAME, INDEX_JWT_FNAME

if sys.version_info >= (3, 11):

    def add_dir(zipf: ZipFile, filename: Path, arcname: Path | str) -> None:
        """
        Add a directory to the OTA image zipfile. The src must be a directory.
        """
        _zipinfo = ZipInfo.from_file(
            filename=f"{str(filename).rstrip('/')}/",
            arcname=f"{str(arcname).rstrip('/')}/",
        )
        _zipinfo.CRC = 0
        _zipinfo.date_time = DEFAULT_TIMESTAMP
        zipf.mkdir(_zipinfo, mode=DIR_PERMISSION)

    def add_file(
        zipf: ZipFile, filename: Path, arcname: Path | str, *, rw_chunk_size: int
    ) -> None:
        """
        Add a regular file to the OTA image zipfile. The src must be a regular file.

        Basically a copy of the ZipFile.writestr method.
        """
        _zipinfo = ZipInfo.from_file(filename=filename, arcname=str(arcname))
        _zipinfo.date_time = DEFAULT_TIMESTAMP
        _zipinfo.compress_type = zipf.compression
        _zipinfo.compress_level = zipf.compresslevel
        _zipinfo.external_attr |= FILE_PERMISSION << 16  # rw_r_r_

        with open(filename, "rb") as src, zipf.open(_zipinfo, "w") as dst:
            shutil.copyfileobj(src, dst, rw_chunk_size)

    def pack_artifact(_image_root: Path, _output: Path, *, rw_chunk_size: int) -> int:
        """Pack OTA image artifact from OTA image located at `_image_root` to `_output`.

        The output artifact will be a ZIP archive with specific constrains as follow:
        1. all file entries(blobs) don't have compression via ZIP, stored as plain file.
        2. all file entries have fixed permission bit and datetime set.
        3. all file entries have size less than ota-image-builder configured `CHUNK_SIZE`.
        4. the files are arranged in alphabet order.

        The OTA image artifact build is reproducible, the same artifact will always be
            generated from the same input OTA image.
        """
        _file_count, _top_level = 0, True
        with ZipFile(_output, mode="w", compression=ZIP_STORED) as output_f:
            for curdir, _, files in os.walk(_image_root):
                curdir = Path(curdir)
                relative_curdir = curdir.relative_to(_image_root)

                if _top_level:
                    _top_level = False

                    # add the index.json file as the first file entry in zipfile,
                    #   effectively defining the manifest for this image.
                    # see https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT chapter 4.1.11
                    #   for more details about ZIP manifest.
                    add_file(
                        zipf=output_f,
                        filename=curdir / IMAGE_INDEX_FNAME,
                        arcname=IMAGE_INDEX_FNAME,
                        rw_chunk_size=rw_chunk_size,
                    )
                    _file_count += 1

                    # following the index.json, add the index.jwt file as the second file entry
                    add_file(
                        zipf=output_f,
                        filename=curdir / INDEX_JWT_FNAME,
                        arcname=INDEX_JWT_FNAME,
                        rw_chunk_size=rw_chunk_size,
                    )
                    _file_count += 1

                    for _fname in sorted(files):
                        if _fname in (IMAGE_INDEX_FNAME, INDEX_JWT_FNAME):
                            continue
                        add_file(
                            zipf=output_f,
                            filename=curdir / _fname,
                            arcname=_fname,
                            rw_chunk_size=rw_chunk_size,
                        )
                        _file_count += 1

                else:
                    add_dir(zipf=output_f, filename=curdir, arcname=relative_curdir)
                    for _file in sorted(files):
                        _src = curdir / _file
                        _relative_src = relative_curdir / _file
                        add_file(
                            zipf=output_f,
                            filename=_src,
                            arcname=_relative_src,
                            rw_chunk_size=rw_chunk_size,
                        )
                        _file_count += 1
        return _file_count
