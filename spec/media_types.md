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

## OTAClient Package Media Types

These media types are specific to the [OTAClient release package](otaclient_package.md).

| Media Type | Usage |
| --- | --- |
| `application/vnd.tier4.otaclient.release-package.v1` | OTAClient release package artifact |
| `application/vnd.tier4.otaclient.release-package.manifest.v1+json` | OTAClient release package manifest |
| `application/vnd.tier4.otaclient.release-package.v1.squashfs` | OTAClient application image (SquashFS) |
