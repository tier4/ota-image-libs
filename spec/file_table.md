# File Table

The file table is a SQLite3 database (`file_table.sqlite3`) that describes the original input system rootfs image of one OTA image payload, recording metadata of all the entries in that filesystem.

It consists of five tables that together describe the complete filesystem tree: inodes, regular files, non-regular files, directories, and resource references.

Each OTA image payload has its own file_table. In a multi-payload OTA image, there is one file_table per payload.

## Media Type

- Uncompressed: `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3`
- Zstd-compressed: `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3+zstd`

## Database Schema

Database as Code: [`file_table/schema.py`](../src/ota_image_libs/v1/file_table/schema.py)

### Inode Table (`ft_inode`)

Stores inode metadata shared across file entries. Multiple file entries may reference the same inode (hard links).

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `inode_id` | int | PRIMARY KEY | Unique inode identifier |
| `uid` | int | NOT NULL | File owner user ID |
| `gid` | int | NOT NULL | File owner group ID |
| `mode` | int | NOT NULL | File permission and mode bits |
| `links_count` | int | | Hard link count |
| `xattrs` | bytes | | Extended attributes, stored as msgpacked dict |

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
| `contents` | bytes | | (For file with size less than 64 bytes) Inline resource data for the file |

## Relationships

```text
+----------------+       +----------------+       +-----------------+
|  ft_regular    |       |   ft_inode     |       | ft_non_regular  |
|----------------|       |----------------|       |-----------------|
| path       PK  |       | inode_id   PK  |       | path        PK  |
| inode_id   FK  |------*| uid            |*------| inode_id    FK  |
| resource_id FK |--+    | gid            |       | meta            |
+----------------+  |    | mode           |       +-----------------+
                    |    | links_count    |
+----------------+  |    | xattrs         |
|    ft_dir      |  |    +----------------+
|----------------|  |           *
| path       PK  |  |           |
| inode_id   FK  |--+-----------+
+----------------+  |
                    |    +----------------+
                    |    | ft_resource    |
                    |    |----------------|
                    +---*| resource_id PK |
                         | digest         |
                         | size           |
                         | contents       |
                         +----------------+

PK = Primary Key, FK = Foreign Key
*  = referenced side (one), no mark = referencing side (many)
```
