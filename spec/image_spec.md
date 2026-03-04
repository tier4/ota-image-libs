# OTA image specification, version 1

## Overview

An OTA image of specification version 1 is a unique representation of an input system rootfs image.
It is designed for file-based OTA updates, where each file in the rootfs is individually tracked and deduplicated.

An OTA image consists of the following components:

- **[Image Index](image_index.md)** (`index.json`) — The top-level manifest that lists all artifacts in the OTA image, including image payloads, OTAClient release packages, and the resource table.
  The image index follows the OCI image index specification.

- **[Image Manifest](image_manifest.md)** — Per-image payload manifest that references the image config and file table.
  Each image manifest represents a single ECU's OTA payload and follows the OCI image manifest specification.
  An image manifest is uniquely identified by its `ecu_id` and `ota_release_key`.

- **[Image Config](image_config.md)** — Configuration metadata for an image payload, including architecture, OS information, system config reference, and statistics about the original rootfs.

- **[Sys Config](sys_config.md)** — System-level configuration for the target device, including hostname, mount points, swap, sysctl settings, and OTAClient configuration.

- **[File Table](file_table.md)** — A per-payload SQLite3 database that records all file entries of the original system rootfs image, including regular files, non-regular files (symlinks, chardevs), directories, inode metadata, and resource references.

- **[Resource Table](resource_table.md)** — A SQLite3 database that serves as the manifest of the blob storage, recording the digest, size, and optional storage optimization filter for every unique resource in the OTA image.

- **[Index JWT](index_jwt.md)** (`index.jwt`) — A signed JWT that authenticates the image index.
  Uses ES256 algorithm with X.509 certificate chain.

- **[OTAClient Package](otaclient_package.md)** — An optional OTAClient release package bundled into the OTA image, allowing OTAClient to self-update before performing the OTA.

## Annotations

Pre-defined annotation keys used across OTA image metadata are documented in [annotations](annotations.md).

## Blob Storage

The blob storage is a flat directory of all unique resources in the OTA image, distinguished by SHA256 digest.
Each resource is stored as a file named by its SHA256 hex digest under the `data/` directory.

When the OTA image is finalized (optimized), resources in the blob storage may be transformed using storage filters:

- **BundleFilter** (`b`) — Small resources are bundled into a larger blob.
  The filter records `bundle_resource_id`, `offset`, and `len` to locate the original resource within the bundle.
- **CompressFilter** (`c`) — Resources are stored compressed.
  The filter records the `resource_id` of the compressed blob and the `compression_alg` (e.g., `zstd`).
- **SliceFilter** (`s`) — Resources are reconstructed from an ordered list of sub-resource IDs.

## OTA Image Artifact

An OTA image artifact is packaged as a ZIP file (strict subset).
The artifact follows these rules:

1. All entries are stored without ZIP-level compression (compression is done during image build at the resource level).
2. Fixed permission bits (`0644` for files, `0755` for directories) and timestamps for reproducible builds.
3. Individual files are limited to less than 32 MiB, except OTAClient packages which may be up to 4 GiB.
4. Entries are ordered alphabetically.

## Media Types

See [media_types.md](media_types.md) for the complete list of media types used in the OTA image specification.
