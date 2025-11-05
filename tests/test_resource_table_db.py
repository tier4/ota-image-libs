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

"""Integration tests for resource_table database operations."""

from ota_image_libs.v1.resource_table.db import ResourceTableDBHelper
from ota_image_libs.v1.resource_table.schema import ResourceTableManifest


class TestResourceTableDBHelper:
    def test_bootstrap_db(self, temp_dir):
        """Test bootstrapping the resource table database."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        assert db_file.exists()
        assert db_file.stat().st_size > 0

    def test_connect_rstable_db(self, temp_dir):
        """Test connecting to resource table database."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_rstable_db()
        assert conn is not None
        conn.close()

    def test_connect_with_wal_mode(self, temp_dir):
        """Test connecting with WAL mode enabled."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_rstable_db(enable_wal=True)
        assert conn is not None
        conn.close()

    def test_connect_with_mmap(self, temp_dir):
        """Test connecting with mmap enabled."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_rstable_db(enable_mmap_size=1024 * 1024)
        assert conn is not None
        conn.close()

    def test_get_orm(self, temp_dir):
        """Test getting ORM instance."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        orm = helper.get_orm()
        assert orm is not None

    def test_get_orm_with_connection(self, temp_dir):
        """Test getting ORM instance with existing connection."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_rstable_db()
        orm = helper.get_orm(conn)
        assert orm is not None
        conn.close()

    def test_get_orm_pool(self, temp_dir):
        """Test getting ORM pool."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        orm_pool = helper.get_orm_pool(db_conn_num=2)
        assert orm_pool is not None

    def test_iter_all_with_shuffle_empty(self, temp_dir):
        """Test iterating all entries with shuffle on empty database."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        entries = list(helper.iter_all_with_shuffle(batch_size=10))
        assert len(entries) == 0

    def test_iter_all_with_shuffle_with_data(self, temp_dir):
        """Test iterating all entries with shuffle with some data."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        # Add some test entries
        conn = helper.connect_rstable_db()
        orm = helper.get_orm(conn)

        # Create test entries
        for i in range(5):
            entry = ResourceTableManifest(
                resource_id=i,
                digest=f"sha256:{'0' * 60}{i:04d}".encode(),
                size=1000 + i,
            )
            orm.orm_insert_entry(entry)

        conn.commit()
        conn.close()

        # Iterate with shuffle
        entries = list(helper.iter_all_with_shuffle(batch_size=3))
        assert len(entries) == 5

        # Verify all resource_ids are present
        resource_ids = {e.resource_id for e in entries}
        expected_ids = {i for i in range(5)}
        assert resource_ids == expected_ids


class TestResourceTableIntegration:
    def test_create_and_query_entries(self, temp_dir):
        """Test creating and querying resource table entries."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        conn = helper.connect_rstable_db()
        orm = helper.get_orm(conn)

        # Create entry
        entry = ResourceTableManifest(
            resource_id=1,
            digest=("sha256:" + "0" * 64).encode(),
            size=12345,
        )

        orm.orm_insert_entry(entry)
        conn.commit()

        # Query entry
        entries = list(orm.orm_select_entries())
        assert len(entries) == 1
        assert entries[0].resource_id == 1
        assert entries[0].size == 12345

        conn.close()

    def test_multiple_connections(self, temp_dir):
        """Test multiple connections to the same database."""
        db_file = temp_dir / "resource_table.db"

        helper = ResourceTableDBHelper(db_file)
        helper.bootstrap_db()

        # First connection - insert
        conn1 = helper.connect_rstable_db()
        orm1 = helper.get_orm(conn1)

        entry = ResourceTableManifest(
            resource_id=1,
            digest=("sha256:" + "1" * 64).encode(),
            size=100,
        )
        orm1.orm_insert_entry(entry)
        conn1.commit()
        conn1.close()

        # Second connection - read
        conn2 = helper.connect_rstable_db()
        orm2 = helper.get_orm(conn2)

        entries = list(orm2.orm_select_entries())
        assert len(entries) == 1
        assert entries[0].resource_id == 1

        conn2.close()
