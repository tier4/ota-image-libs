# Resource Table

The resource table is a SQLite3 database (`resource_table.sqlite3`) that serves as the manifest of the OTA image blob storage.
It records every unique resource (blob) in the OTA image, including the digest, size, and optional storage optimization filter.

The resource table is referenced from the [image index](image_index.md) as a top-level manifest entry.

`resource_table` applies to the whole OTA image, not a specific OTA image payload.

## Media Type

- Uncompressed: `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3`
- Zstd-compressed: `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3+zstd`

## Database Schema

Database as Code: [`resource_table/schema.py`](../src/ota_image_libs/v1/resource_table/schema.py)

### Resource Manifest Table (`rs_manifest`)

| Column | Type | Constraint | Description |
| --- | --- | --- | --- |
| `resource_id` | int | PRIMARY KEY | Unique resource identifier |
| `digest` | bytes | NOT NULL, UNIQUE | SHA256 digest of the original resource |
| `size` | int | NOT NULL | Size of the original resource in bytes |
| `filter_applied` | bytes | | Storage optimization filter, serialized as `<filter_code>:<msgpack_options>` |
| `meta` | bytes | | Additional metadata |

## Storage Optimization Filters

When an OTA image is finalized, the blob storage may apply filters to optimize the blob storage and improve transfer efficiency.
The `filter_applied` column records which filter was applied to a given resource.

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

## Retrieve an original resource blob from the optimized Blob Storage

Because the blob storage may apply filters to optimize storage, recovering the original resource requires resolving the `filter_applied` chain.
The resolution is recursive — a filtered resource may reference other resources that themselves have filters applied.

Given a file entry from the [file table](file_table.md), to retrieve the resource blob for that regular file entry, the lookup process will be:

1. **Look up the resource by digest.** Use the `digest` from `file_table.ft_resource` in the file table to find the corresponding entry in `resource_table.rs_manifest`.
Note that `resource_id` in the file table and `resource_id` in the resource table are independent — the digest is the join key.

2. **Check `filter_applied`.** If the entry has no filter (`filter_applied` is NULL), the resource is stored as-is in the blob storage. Fetch the blob identified by its digest directly.

3. **Resolve the filter.** Recursively recover the original resource according to the filter type:

   - **No filter** — The resource is a leaf. Fetch the blob by its digest directly from the blob storage.

   - **BundleFilter (`b`)** — Look up the bundle resource by `bundle_resource_id`, recursively resolve the bundle resource itself, then extract the target bytes at `offset` with length `len` from the resolved bundle blob.

   - **CompressFilter (`c`)** — Look up the compressed resource by `resource_id`, recursively resolve it (it may itself be sliced), then decompress with the specified `compression_alg` to obtain the original resource.

   - **SliceFilter (`s`)** — Look up each sub-resource in `slices` by their resource IDs, resolve each one (slices themselves MUST be leaf resources with no filter applied), then concatenate them in order to reconstruct the original resource.

The following diagram illustrates the possible filter resolution trees:

```text
Original Resource (compressed + sliced)
  └── CompressFilter
        └── Compressed Blob (sliced)
              └── SliceFilter
                    ├── Slice 0 (leaf, no filter)
                    ├── Slice 1 (leaf, no filter)
                    └── Slice 2 (leaf, no filter)

Original Resource (bundled)
  └── BundleFilter
        └── Bundle Blob (may itself need resolution)
              extract bytes at [offset, offset+len)

Original Resource (no filter)
  └── (leaf, fetch directly from blob storage)
```
