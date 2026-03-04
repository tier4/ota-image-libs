# OTAClient Package Artifact

The [OTAClient](https://github.com/tier4/ota-client) package artifact is an optional component within the OTA image that carries [OTAClient](https://github.com/tier4/ota-client) release package.
[OTAClient](https://github.com/tier4/ota-client) can use this to update itself before performing the actual OTA update on the target ECU.

The artifact type for the OTAClient release package artifact is:
`application/vnd.tier4.otaclient.release-package.v1`.

Schema as code: [`otaclient_package/schema.py`](../src/ota_image_libs/v1/otaclient_package/schema.py)


## OTAClient Package Manifest Schema

- **`schemaVersion`** *int*

    This REQUIRED field specifies the manifest's schema version.
    The value MUST be `2`.

- **`mediaType`** *string*

    This REQUIRED field specifies the media type of the manifest.
    The value MUST be `application/vnd.oci.image.manifest.v1+json`.

- **`artifactType`** *string*

    This REQUIRED field specifies the artifact type of the OTAClient package manifest.
    The value MUST be `application/vnd.tier4.otaclient.release-package.v1`.

- **`config`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    This REQUIRED field specifies an OCI descriptor that points to the [original OTAClient release package manifest](https://github.com/tier4/ota-client/blob/main/src/otaclient_manifest/schema.py).
    The mediaType MUST be `application/vnd.tier4.otaclient.release-package.manifest.v1+json`.

- **`layers`** *array of [OCI descriptors](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    This REQUIRED field specifies a list of descriptors, each pointing to an OTAClient application image artifact.
    The mediaType of each descriptor MUST be `application/vnd.tier4.otaclient.release-package.v1.squashfs`.
    Typically, there will be at least two entries for `x86_64` and `arm64` architectures.

    Each layer descriptor MAY have `annotations` with the following fields:

    - **`version`** *string* — The version of the OTAClient application image.
    - **`type`** *string* — The type of the artifact (e.g., `squashfs`).
    - **`architecture`** *string* — The target architecture. MUST be either `arm64` or `x86_64`.
    - **`size`** *int* — The size of the artifact in bytes.
    - **`checksum`** *string* — The SHA256 digest of the artifact (e.g., `sha256:<hex>`).

- **`annotations`** *string-string map*

    This REQUIRED field specifies the annotations for this OTAClient package manifest.

    - **`date`** *string* — The date and time when this OTAClient release package was created, in ISO8601 format.

## Example OTAClient Package Artifact Manifest

```json
{
  "config": {
    "size": 734,
    "digest": "sha256:ae1cb935a136d480e2f4413da0bbf599cbde7d4e36dd84b06df7c98fd9be753c",
    "mediaType": "application/vnd.tier4.otaclient.release-package.manifest.v1+json"
  },
  "layers": [
    {
      "size": 55123968,
      "digest": "sha256:a6ca43b751e9eb9d9f50461e76d957cf8be873e779f9415b55532b8f7072a2e5",
      "annotations": {
        "version": "3.9.1.squashfs",
        "type": "squashfs",
        "architecture": "arm64",
        "size": 55123968,
        "checksum": "sha256:a6ca43b751e9eb9d9f50461e76d957cf8be873e779f9415b55532b8f7072a2e5"
      },
      "mediaType": "application/vnd.tier4.otaclient.release-package.v1.squashfs"
    },
    {
      "size": 57634816,
      "digest": "sha256:3be096c4952122f168748a6db9d11fde8570afce01b837f2f61d43c7a8ce3fa3",
      "annotations": {
        "version": "3.9.1.squashfs",
        "type": "squashfs",
        "architecture": "x86_64",
        "size": 57634816,
        "checksum": "sha256:3be096c4952122f168748a6db9d11fde8570afce01b837f2f61d43c7a8ce3fa3"
      },
      "mediaType": "application/vnd.tier4.otaclient.release-package.v1.squashfs"
    }
  ],
  "annotations": {
    "date": "2025-07-03T08:38:38.782711Z"
  },
  "schemaVersion": 2,
  "mediaType": "application/vnd.oci.image.manifest.v1+json"
}
```
