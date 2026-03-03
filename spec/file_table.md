# File Table

## Media Type

- Uncompressed: `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3`
- Zstd-compressed: `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3+zstd`

The file table is a SQLite3 database (`file_table.sqlite3`) that records all file entries of the original system rootfs image. It consists of five tables that together describe the complete filesystem tree: inodes, regular files, non-regular files, directories, and resource references.

## Database Schema

### Inode Table (`ft_inode`)

Stores inode metadata shared across file entries. Multiple file entries may reference the same inode (hard links).

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `inode_id` | int | PRIMARY KEY | Unique inode identifier |
| `uid` | int | NOT NULL | File owner user ID |
| `gid` | int | NOT NULL | File owner group ID |
| `mode` | int | NOT NULL | File permission and mode bits |
| `links_count` | int | | Hard link count |
| `xattrs` | bytes | | Extended attributes, stored as msgpack-encoded dict |

### Regular Files Table (`ft_regular`)

Stores regular file entries. Each entry references an inode for metadata and a resource for file contents.

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `path` | string | PRIMARY KEY | Absolute file path |
| `inode_id` | int | NOT NULL | References `ft_inode.inode_id` |
| `resource_id` | int | | References `ft_resource.resource_id` |

### Non-Regular Files Table (`ft_non_regular`)

Stores non-regular file entries, including symlinks and character device files.

Character device support is limited to overlayfs whiteout files (device number `0,0`).

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `path` | string | PRIMARY KEY | Absolute file path |
| `inode_id` | int | NOT NULL | References `ft_inode.inode_id` |
| `meta` | bytes | | File contents: symlink target path for symlinks, device info for chardevs |

### Directories Table (`ft_dir`)

Stores directory entries.

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `path` | string | PRIMARY KEY | Absolute directory path |
| `inode_id` | int | NOT NULL | References `ft_inode.inode_id` |

### Resource Table (`ft_resource`)

Stores resource/blob references for regular files within this image payload. Each resource is identified by its SHA256 digest.

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `resource_id` | int | PRIMARY KEY | Unique resource identifier |
| `digest` | bytes | NOT NULL, UNIQUE | SHA256 digest of the resource |
| `size` | int | NOT NULL | Size of the resource in bytes |
| `contents` | bytes | | Inline resource data for small files |

## Relationships

```text
ft_regular.inode_id       → ft_inode.inode_id
ft_regular.resource_id    → ft_resource.resource_id
ft_non_regular.inode_id   → ft_inode.inode_id
ft_dir.inode_id           → ft_inode.inode_id
```
