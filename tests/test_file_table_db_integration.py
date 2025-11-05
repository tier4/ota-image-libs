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

"""Integration tests for file_table database operations."""

from ota_image_libs.v1.file_table.db import (
    FileTableDBHelper,
    FileTableInodeORM,
    FileTableNonRegularORM,
    FileTableRegularORM,
)
from ota_image_libs.v1.file_table.schema import (
    FileTableInode,
    FileTableNonRegularFiles,
    FileTableRegularFiles,
)


class TestFileTableDBHelper:
    def test_bootstrap_db(self, temp_dir):
        """Test bootstrapping the file table database."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        assert db_file.exists()
        assert db_file.stat().st_size > 0

    def test_connect_fstable_db(self, temp_dir):
        """Test connecting to file table database."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_fstable_db()
        assert conn is not None
        conn.close()

    def test_connect_with_wal_mode(self, temp_dir):
        """Test connecting with WAL mode enabled."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_fstable_db(enable_wal=True)
        assert conn is not None
        conn.close()

    def test_connect_with_mmap(self, temp_dir):
        """Test connecting with mmap enabled."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_fstable_db(enable_mmap_size=1024 * 1024)
        assert conn is not None
        conn.close()

    def test_iter_dir_entries_empty(self, temp_dir):
        """Test iterating directory entries on empty database."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        entries = list(helper.iter_dir_entries())
        assert len(entries) == 0

    def test_iter_regular_entries_empty(self, temp_dir):
        """Test iterating regular file entries on empty database."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        entries = list(helper.iter_regular_entries())
        assert len(entries) == 0

    def test_iter_non_regular_entries_empty(self, temp_dir):
        """Test iterating non-regular file entries on empty database."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        entries = list(helper.iter_non_regular_entries())
        assert len(entries) == 0

    def test_select_all_digests_empty(self, temp_dir):
        """Test selecting all digests from empty database."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        digests = list(helper.select_all_digests_with_size())
        assert len(digests) == 0


class TestFileTableIntegration:
    def test_create_and_query_inodes(self, temp_dir):
        """Test creating and querying inode entries."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_fstable_db()
        orm = FileTableInodeORM(conn)

        # Create inode entry
        inode = FileTableInode(
            inode_id=1,
            uid=1000,
            gid=1000,
            mode=0o644,
        )

        orm.orm_insert_entry(inode)
        conn.commit()

        # Query entry
        entries = list(orm.orm_select_entries())
        assert len(entries) == 1
        assert entries[0].inode_id == 1
        assert entries[0].uid == 1000
        assert entries[0].gid == 1000
        assert entries[0].mode == 0o644

        conn.close()

    def test_create_regular_file_entry(self, temp_dir):
        """Test creating regular file entry."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_fstable_db()
        inode_orm = FileTableInodeORM(conn)
        regular_orm = FileTableRegularORM(conn)

        # Create inode first
        inode = FileTableInode(
            inode_id=1,
            uid=1000,
            gid=1000,
            mode=0o644,
        )
        inode_orm.orm_insert_entry(inode)

        # Create regular file entry
        regular_file = FileTableRegularFiles(
            path="/test/file.txt",
            inode_id=1,
            resource_id=100,
        )

        regular_orm.orm_insert_entry(regular_file)
        conn.commit()

        # Query entry
        entries = list(regular_orm.orm_select_entries())
        assert len(entries) == 1
        assert entries[0].path == "/test/file.txt"
        assert entries[0].inode_id == 1
        assert entries[0].resource_id == 100

        conn.close()

    def test_create_non_regular_file_entry(self, temp_dir):
        """Test creating non-regular file entry (symlink)."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_fstable_db()
        inode_orm = FileTableInodeORM(conn)
        non_regular_orm = FileTableNonRegularORM(conn)

        # Create inode first
        inode = FileTableInode(
            inode_id=2,
            uid=1000,
            gid=1000,
            mode=0o777,
        )
        inode_orm.orm_insert_entry(inode)

        # Create non-regular file entry (symlink)
        symlink = FileTableNonRegularFiles(
            path="/test/symlink",
            inode_id=2,
            meta=b"/target/path",
        )

        non_regular_orm.orm_insert_entry(symlink)
        conn.commit()

        # Query entry
        entries = list(non_regular_orm.orm_select_entries())
        assert len(entries) == 1
        assert entries[0].path == "/test/symlink"
        assert entries[0].inode_id == 2
        assert entries[0].meta == b"/target/path"

        conn.close()

    def test_multiple_connections(self, temp_dir):
        """Test multiple connections to the same database."""
        db_file = temp_dir / "file_table.db"

        helper = FileTableDBHelper(db_file)
        helper.bootstrap_db()

        # First connection - insert
        conn1 = helper.connect_fstable_db()
        orm1 = FileTableInodeORM(conn1)

        inode = FileTableInode(
            inode_id=1,
            uid=1000,
            gid=1000,
            mode=0o644,
        )
        orm1.orm_insert_entry(inode)
        conn1.commit()
        conn1.close()

        # Second connection - read
        conn2 = helper.connect_fstable_db()
        orm2 = FileTableInodeORM(conn2)

        entries = list(orm2.orm_select_entries())
        assert len(entries) == 1
        assert entries[0].inode_id == 1

        conn2.close()
