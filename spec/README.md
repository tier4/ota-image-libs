# OTA Image Specification v1

This directory contains the authoritative specification for OTA image version 1.

## Overview

[image_spec.md](image_spec.md) — Overall OTA image specification overview, including components, blob storage, and artifact format

## Artifact Types for OTA Image

Following the OCI specification, OTA-specific artifacts and manifests have their own [media types](media_types.md).

## OTA Metadata Specifications

| Document | Description |
| --- | --- |
| [image_index.md](image_index.md) | Top-level OCI image index (`index.json`) |
| [image_manifest.md](image_manifest.md) | Per-image payload manifest (OCI image manifest) |
| [image_config.md](image_config.md) | Image configuration and rootfs statistics |
| [sys_config.md](sys_config.md) | System-level configuration (hostname, mounts, swap, etc.) |
| [file_table.md](file_table.md) | SQLite3 database schema for filesystem metadata |
| [resource_table.md](resource_table.md) | SQLite3 database schema for blob storage manifest |
| [otaclient_package.md](otaclient_package.md) | OTAClient release package format |

## OTA Image Signing and Verification

The OTA image's entry point (`index.json`) is signed by [Index JWT](index_jwt.md) following the JWT/JWS specification.

## Annotation Keys

Following the OCI specification, OTA image spec v1 pre-defines a list of [annotation keys](annotations.md) for annotating and labelling the OTA image.
