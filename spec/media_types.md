# Media Types

Source code: [`media_types.py`](../src/ota_image_libs/v1/media_types.py)

This document lists all media types used in the OTA image v1 specification.

## OCI Standard Media Types

These media types are defined by the [OCI Image Spec](https://github.com/opencontainers/image-spec/blob/main/media-types.md).

| Media Type | Usage |
| --- | --- |
| `application/vnd.oci.image.index.v1+json` | [Image Index](image_index.md) |
| `application/vnd.oci.image.manifest.v1+json` | [Image Manifest](image_manifest.md) |

## OTA Image Media Types

These media types are specific to the OTA image v1 specification.

| Media Type | Usage |
| --- | --- |
| `application/vnd.tier4.ota.file-based-ota-image.v1` | OTA image artifact |
| `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3` | [File Table](file_table.md) (uncompressed) |
| `application/vnd.tier4.ota.file-based-ota-image.file_table.v1.sqlite3+zstd` | [File Table](file_table.md) (zstd-compressed) |
| `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3` | [Resource Table](resource_table.md) (uncompressed) |
| `application/vnd.tier4.ota.file-based-ota-image.resource_table.v1.sqlite3+zstd` | [Resource Table](resource_table.md) (zstd-compressed) |
| `application/vnd.tier4.ota.file-based-ota-image.config.v1+json` | [Image Config](image_config.md) |
| `application/vnd.tier4.ota.sys-config.v1+yaml` | [System Config](sys_config.md) |

## Partition-based OTA Image Media Types

These media types are specific to the [partition-based payload](partition_image.md).

| Media Type | Usage |
| --- | --- |
| `application/vnd.tier4.ota.partition-based-ota-image.v1` | `artifactType` of a partition-based payload's image manifest |
| `application/vnd.tier4.ota.partition-based-ota-image.config.v1+json` | [Partition Image Config](partition_image.md#partition-image-config) |
| `application/vnd.tier4.ota.partition-based-ota-image.partition.v1` | a raw partition image blob |
| `application/vnd.tier4.ota.partition-based-ota-image.partition.v1+zstd` | the same, stored zstd-compressed (see [Compressed Blobs](partition_image.md#compressed-blobs)) |
| `application/vnd.tier4.ota.partition-based-ota-image.boot-files.v1.tar` | the boot files of a slot, as a tar |
| `application/vnd.tier4.ota.partition-based-ota-image.partition-delta.v1.tar` | a [block diff](partition_image.md#partition-delta) that reconstructs a partition image from an earlier one |
| `application/vnd.tier4.ota.partition-based-ota-image.vendor-package.v1` | an opaque package applied by the platform's own updater |
| `application/vnd.tier4.ota.partition-based-ota-image.vendor-package.v1+zstd` | the same, stored zstd-compressed |
| `application/vnd.tier4.ota.partition-based-ota-image.data-image.v1` | a [data image](partition_image.md#data-image-entry): a read-only filesystem image kept as a file outside the slots and mounted at a path |
| `application/vnd.tier4.ota.partition-based-ota-image.data-image.v1+zstd` | the same, stored zstd-compressed |
| `application/vnd.tier4.ota.partition-based-ota-image.firmware-package.v1` | a [firmware package](partition_image.md#firmware-entry) the platform's own firmware updater applies |
| `application/vnd.tier4.ota.partition-based-ota-image.firmware-package.v1+zstd` | the same, stored zstd-compressed |

## OTAClient Package Media Types

These media types are specific to the [OTAClient release package](otaclient_package.md).

| Media Type | Usage |
| --- | --- |
| `application/vnd.tier4.otaclient.release-package.v1` | OTAClient release package artifact |
| `application/vnd.tier4.otaclient.release-package.manifest.v1+json` | OTAClient release package manifest |
| `application/vnd.tier4.otaclient.release-package.v1.squashfs` | OTAClient application image (SquashFS) |

## Update Agent Release Package

The agent that applies an OTA image, shipped in it; see [`update_agent_package/schema.py`](../src/ota_image_libs/v1/update_agent_package/schema.py).

| Media Type | Usage |
| --- | --- |
| `application/vnd.tier4.ota.update-agent.release-package.v1` | `artifactType` of the entry's manifest |
| `application/vnd.tier4.ota.update-agent.release-package.manifest.v1+json` | its manifest, whose `layers` are the bundles |
| `application/vnd.tier4.ota.update-agent.bundle.v1` | one bundle; annotations `vnd.tier4.ota.update-agent.type`, `.version` and optionally `.architecture` say what it is and what it runs on |
