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

"""Tests for file_table utils module."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ota_image_libs.common import MsgPackedDict
from ota_image_libs.v1.file_table.db import DirRow, NonRegularFileRow, RegularFileRow
from ota_image_libs.v1.file_table.utils import (
    PrepareEntryFailed,
    _set_xattr,
    prepare_dir,
    prepare_non_regular,
    prepare_regular_copy,
    prepare_regular_hardlink,
    prepare_regular_inlined,
)


class TestSetXattr:
    """Tests for _set_xattr function."""

    def test_set_xattr_basic(self, tmp_path):
        """Test setting extended attributes."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        xattrs = MsgPackedDict(
            {
                "user.test_attr": b"test_value",
                "user.another": b"another_value",
            }
        )

        _set_xattr(test_file, xattrs)

        # Verify attributes were set
        for key, value in xattrs.items():
            actual = os.getxattr(test_file, key, follow_symlinks=False)
            assert actual == value

    @pytest.mark.skip(
        "Setting xattr on symlinks may not be supported on all filesystems"
    )
    def test_set_xattr_on_symlink(self, tmp_path):
        """Test setting extended attributes on a symlink."""
        target = tmp_path / "target.txt"
        target.touch()
        link = tmp_path / "link"
        link.symlink_to(target)

        xattrs = MsgPackedDict({"user.link_attr": b"link_value"})

        _set_xattr(link, xattrs)

        # Verify attribute was set on the link itself, not the target
        actual = os.getxattr(link, "user.link_attr", follow_symlinks=False)
        assert actual == b"link_value"


class TestPrepareDir:
    """Tests for prepare_dir function."""

    def test_prepare_dir_basic(self, tmp_path):
        """Test creating a basic directory."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()

        entry = DirRow(
            path="/test/dir",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o755,
        )

        prepare_dir(entry, target_mnt=target_mnt)

        created_dir = target_mnt / "test" / "dir"
        assert created_dir.exists()
        assert created_dir.is_dir()
        assert stat.S_IMODE(created_dir.stat().st_mode) == 0o755

    def test_prepare_dir_with_parents(self, tmp_path):
        """Test creating directory with parent directories."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()

        entry = DirRow(
            path="/a/b/c/d",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o750,
        )

        prepare_dir(entry, target_mnt=target_mnt)

        created_dir = target_mnt / "a" / "b" / "c" / "d"
        assert created_dir.exists()
        assert created_dir.is_dir()

    def test_prepare_dir_with_xattrs(self, tmp_path):
        """Test creating directory with extended attributes."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()

        xattrs = MsgPackedDict({"user.test": b"value"})
        entry = DirRow(
            path="/test/dir",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o755,
            xattrs=xattrs,
        )

        prepare_dir(entry, target_mnt=target_mnt)

        created_dir = target_mnt / "test" / "dir"
        actual = os.getxattr(created_dir, "user.test")
        assert actual == b"value"

    def test_prepare_dir_exists_ok(self, tmp_path):
        """Test that preparing an existing directory doesn't fail."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        existing_dir = target_mnt / "test"
        existing_dir.mkdir()

        entry = DirRow(
            path="/test",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o755,
        )

        # Should not raise
        prepare_dir(entry, target_mnt=target_mnt)
        assert existing_dir.exists()

    def test_prepare_dir_failure_raises_exception(self, tmp_path):
        """Test that failures raise PrepareEntryFailed."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        # Create a file where the directory should be
        blocking_file = target_mnt / "test"
        blocking_file.touch()

        entry = DirRow(
            path="/test/dir",  # This will fail because /test is a file
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o755,
        )

        with pytest.raises(PrepareEntryFailed) as exc_info:
            prepare_dir(entry, target_mnt=target_mnt)

        assert exc_info.value.entry == entry


class TestPrepareNonRegular:
    """Tests for prepare_non_regular function."""

    def test_prepare_symlink(self, tmp_path):
        """Test creating a symlink."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        symlink_target = "/target/file.txt"
        entry = NonRegularFileRow(
            path="/test/link",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=stat.S_IFLNK | 0o777,
            meta=symlink_target.encode(),
        )

        prepare_non_regular(entry, target_mnt=target_mnt)

        created_link = target_mnt / "test" / "link"
        assert created_link.is_symlink()
        assert os.readlink(created_link) == symlink_target

    @pytest.mark.skip("symlink with xattr might not be supported in all filesystems")
    def test_prepare_symlink_with_xattrs(self, tmp_path):
        """Test creating symlink with extended attributes."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        xattrs = MsgPackedDict({"user.link_attr": b"link_value"})
        entry = NonRegularFileRow(
            path="/test/link",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=stat.S_IFLNK | 0o777,
            meta=b"/target",
            xattrs=xattrs,
        )
        prepare_non_regular(entry, target_mnt=target_mnt)

        created_link = target_mnt / "test" / "link"
        actual = os.getxattr(created_link, "user.link_attr", follow_symlinks=False)
        assert actual == b"link_value"

    def test_prepare_non_regular_symlink_no_target_fails(self, tmp_path):
        """Test that symlink without target fails."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()

        entry = NonRegularFileRow(
            path="/test/bad_link",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=stat.S_IFLNK | 0o777,
            meta=None,  # No target
        )

        with pytest.raises(PrepareEntryFailed):
            prepare_non_regular(entry, target_mnt=target_mnt)

    def test_prepare_non_regular_unknown_type_ignored(self, tmp_path):
        """Test that unknown file types are silently ignored."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()

        # FIFO type as an example of unsupported type
        entry = NonRegularFileRow(
            path="/test/fifo",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=stat.S_IFIFO | 0o644,
        )

        # Should not raise, just silently ignore
        prepare_non_regular(entry, target_mnt=target_mnt)


class TestPrepareRegularCopy:
    """Tests for prepare_regular_copy function."""

    def test_prepare_regular_copy_basic(self, tmp_path):
        """Test copying a regular file."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        content = b"test content"
        source_file.write_bytes(content)

        entry = RegularFileRow(
            path="/test/file.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"somedigest",
            size=len(content),
            inode_id=1,
        )

        result = prepare_regular_copy(entry, source_file, target_mnt=target_mnt)

        assert result.exists()
        assert result.read_bytes() == content
        assert stat.S_IMODE(result.stat().st_mode) == 0o644

    def test_prepare_regular_copy_with_permissions(self, tmp_path):
        """Test copying file with specific permissions."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        source_file.write_bytes(b"content")

        entry = RegularFileRow(
            path="/test/file.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o755,
            digest=b"digest",
            size=7,
            inode_id=1,
        )

        result = prepare_regular_copy(entry, source_file, target_mnt=target_mnt)

        assert stat.S_IMODE(result.stat().st_mode) == 0o755

    def test_prepare_regular_copy_with_xattrs(self, tmp_path):
        """Test copying file with extended attributes."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        source_file.write_bytes(b"content")

        xattrs = MsgPackedDict({"user.custom": b"value"})
        entry = RegularFileRow(
            path="/test/file.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=7,
            inode_id=1,
            xattrs=xattrs,
        )

        result = prepare_regular_copy(entry, source_file, target_mnt=target_mnt)

        actual = os.getxattr(result, "user.custom")
        assert actual == b"value"

    def test_prepare_regular_copy_custom_copyfile(self, tmp_path):
        """Test using custom copyfile utility."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        source_file.write_bytes(b"original")

        # Custom copyfile that writes different content
        def custom_copy(src: Path, dst: Path):
            dst.write_bytes(b"custom")

        entry = RegularFileRow(
            path="/test/file.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=7,
            inode_id=1,
        )

        result = prepare_regular_copy(
            entry, source_file, target_mnt=target_mnt, copyfile_util=custom_copy
        )

        assert result.read_bytes() == b"custom"

    def test_prepare_regular_copy_failure_cleanup(self, tmp_path):
        """Test that failed copy cleans up target file."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()

        source_file = tmp_path / "nonexistent.txt"  # Doesn't exist

        entry = RegularFileRow(
            path="/test/file.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=0,
            inode_id=1,
        )

        target_file = target_mnt / "test" / "file.txt"

        with pytest.raises(PrepareEntryFailed):
            prepare_regular_copy(entry, source_file, target_mnt=target_mnt)

        # File should not exist after failed copy
        assert not target_file.exists()


class TestPrepareRegularInlined:
    """Tests for prepare_regular_inlined function."""

    def test_prepare_regular_inlined_with_content(self, tmp_path):
        """Test creating file with inlined content."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        content = b"inlined content"
        entry = RegularFileRow(
            path="/test/file.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=len(content),
            inode_id=1,
            contents=content,
        )

        result = prepare_regular_inlined(entry, target_mnt=target_mnt)

        assert result.exists()
        assert result.read_bytes() == content
        assert stat.S_IMODE(result.stat().st_mode) == 0o644

    def test_prepare_regular_inlined_empty_file(self, tmp_path):
        """Test creating empty file."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        entry = RegularFileRow(
            path="/test/empty.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=0,
            inode_id=1,
            contents=None,
        )

        result = prepare_regular_inlined(entry, target_mnt=target_mnt)

        assert result.exists()
        assert result.read_bytes() == b""
        assert stat.S_IMODE(result.stat().st_mode) == 0o644

    def test_prepare_regular_inlined_with_xattrs(self, tmp_path):
        """Test creating inlined file with extended attributes."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        xattrs = MsgPackedDict({"user.inline": b"attr_value"})
        entry = RegularFileRow(
            path="/test/file.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=4,
            inode_id=1,
            contents=b"data",
            xattrs=xattrs,
        )

        result = prepare_regular_inlined(entry, target_mnt=target_mnt)

        actual = os.getxattr(result, "user.inline")
        assert actual == b"attr_value"


class TestPrepareRegularHardlink:
    """Tests for prepare_regular_hardlink function."""

    def test_prepare_regular_hardlink_basic(self, tmp_path):
        """Test creating a hardlink."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        content = b"hardlink content"
        source_file.write_bytes(content)

        entry = RegularFileRow(
            path="/test/hardlink.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=len(content),
            inode_id=1,
        )

        result = prepare_regular_hardlink(entry, source_file, target_mnt=target_mnt)

        assert result.exists()
        assert result.read_bytes() == content
        # Verify it's a hardlink (same inode)
        assert result.stat().st_ino == source_file.stat().st_ino
        assert result.stat().st_nlink == 2

    def test_prepare_regular_hardlink_with_permissions(self, tmp_path):
        """Test creating hardlink with permission application."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        source_file.write_bytes(b"content")

        entry = RegularFileRow(
            path="/test/hardlink.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o755,
            digest=b"digest",
            size=7,
            inode_id=1,
        )

        result = prepare_regular_hardlink(
            entry,
            source_file,
            target_mnt=target_mnt,
            hardlink_skip_apply_permission=False,
        )

        assert stat.S_IMODE(result.stat().st_mode) == 0o755

    def test_prepare_regular_hardlink_skip_permissions(self, tmp_path):
        """Test creating hardlink without applying permissions."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        source_file.write_bytes(b"content")
        # Set specific mode on source
        os.chmod(source_file, 0o600)

        entry = RegularFileRow(
            path="/test/hardlink.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o755,  # Different mode
            digest=b"digest",
            size=7,
            inode_id=1,
        )

        result = prepare_regular_hardlink(
            entry,
            source_file,
            target_mnt=target_mnt,
            hardlink_skip_apply_permission=True,
        )

        # Should keep source file's permissions
        assert stat.S_IMODE(result.stat().st_mode) == 0o600

    def test_prepare_regular_hardlink_with_xattrs(self, tmp_path):
        """Test creating hardlink with extended attributes."""
        target_mnt = tmp_path / "mnt"
        target_mnt.mkdir()
        (target_mnt / "test").mkdir()  # Create parent directory

        source_file = tmp_path / "source.txt"
        source_file.write_bytes(b"content")

        xattrs = MsgPackedDict({"user.hardlink": b"attr"})
        entry = RegularFileRow(
            path="/test/hardlink.txt",
            uid=os.getuid(),
            gid=os.getgid(),
            mode=0o644,
            digest=b"digest",
            size=7,
            inode_id=1,
            xattrs=xattrs,
        )

        result = prepare_regular_hardlink(entry, source_file, target_mnt=target_mnt)

        actual = os.getxattr(result, "user.hardlink")
        assert actual == b"attr"
