# OTAClient package artifact

## OTAClient package manifest schema

- **`schemaVersion`** *int*

- **`mediaType`** *string*

- **`config`** *OCI Descriptor*

  OCI descriptor that points to the original package artifact manifest.
  See [`otaclient release specification`](https://tier4.atlassian.net/wiki/spaces/OTA/pages/3486056633/4.+The+release+format+of+otaclient) for the schema of the original package artifact manifest.

- **`layers`** *array of OCI Descriptors*

  A list of descriptors that each points an otaclient package artifact.
  Typically, we will have at least two otaclient APP image artifacts for `x86_64` and `arm64` architectures.

## Example OTAClient package artifact manifest

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