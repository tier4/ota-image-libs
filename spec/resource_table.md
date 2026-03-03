# Resource Table

## Media Type

- Uncompressed: `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3`
- Zstd-compressed: `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3+zstd`

The resource table is a SQLite3 database (`resource_table.sqlite3`) that serves as the manifest of the OTA image blob storage. It records every unique resource (blob) in the OTA image, including the digest, size, and optional storage optimization filter.

The resource table is referenced from the [image index](image_index.md) as a top-level manifest entry.

## Database Schema

### Resource Manifest Table (`rs_manifest`)

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `resource_id` | int | PRIMARY KEY | Unique resource identifier |
| `digest` | bytes | NOT NULL, UNIQUE | SHA256 digest of the original resource |
| `size` | int | NOT NULL | Size of the original resource in bytes |
| `filter_applied` | bytes | | Storage optimization filter, serialized as `<filter_code>:<msgpack_options>` |
| `meta` | bytes | | Additional metadata |

## Storage Optimization Filters

When an OTA image is finalized (optimized), the blob storage may apply filters to reduce storage size or improve transfer efficiency. The `filter_applied` column records which filter was applied to a given resource.

The raw format is `<filter_type>:<msgpack_encoded_options>`, where `filter_type` is a single-byte code.

### BundleFilter (`b`)

Small resources are bundled together into a larger blob to reduce the number of files in the blob storage.

Options (msgpack-encoded list):

- **`bundle_resource_id`** *int* — The resource ID of the bundle blob that contains this resource.
- **`offset`** *int* — Byte offset within the bundle blob where this resource starts.
- **`len`** *int* — Length in bytes of this resource within the bundle blob.

### CompressFilter (`c`)

Resources are stored in compressed form using a specified compression algorithm.

Options (msgpack-encoded list):

- **`resource_id`** *int* — The resource ID of the compressed blob in the blob storage.
- **`compression_alg`** *string* — The compression algorithm used (e.g., `zstd`).

### SliceFilter (`s`)

Large resources are sliced into smaller sub-resources. The original resource is reconstructed by concatenating the sub-resources in order.

Options (msgpack-encoded list):

- **`slices`** *array of int* — Ordered list of resource IDs that, when concatenated, reconstruct the original resource.
