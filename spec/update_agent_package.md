# Update Agent Release Package

The update agent release package is an optional entry of the [image index](image_index.md) that ships the agents which apply the OTA image, in the image itself.
A consumer whose own agent is older than the one shipped here installs it and hands over to it, and that one applies the payload; a consumer already running something at least as new ignores it.
Comparing versions is the consumer's business: the package only says what it ships.

One entry carries a **bundle** per agent the image serves. A bundle says what it is (its type) and what it runs on (its architecture), and a consumer takes only a bundle of a type it implements and can run: what it does with one is install it and execute it as root, so a bundle of any other type is inert to it.
This is what lets a single image serve ECUs that run different agents.

The [OTAClient release package](otaclient_package.md) is the same concept for otaclient specifically and predates this one; an image MAY carry both.

Schema as code: [`update_agent_package/schema.py`](../src/ota_image_libs/v1/update_agent_package/schema.py)

## Index Entry

The descriptor in the index's `manifests`:

- **`mediaType`** — `application/vnd.tier4.ota.update-agent.release-package.manifest.v1+json`.
- **`artifactType`** — `application/vnd.tier4.ota.update-agent.release-package.v1`.

An index carries at most one such entry. It is known to consumers from ota-image-libs 0.6.0 on; a consumer that predates it refuses the whole index (see [image_index.md](image_index.md)).

## Update Agent Package Manifest Schema

An [OCI image manifest](https://github.com/opencontainers/image-spec/blob/main/manifest.md):

- **`schemaVersion`** *int* — REQUIRED, MUST be `2`.
- **`mediaType`** *string* — REQUIRED, MUST be `application/vnd.oci.image.manifest.v1+json`.
- **`artifactType`** *string* — the descriptor's, `application/vnd.tier4.ota.update-agent.release-package.v1`.
- **`config`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — REQUIRED, the [OCI empty descriptor](https://github.com/opencontainers/image-spec/blob/main/manifest.md#guidance-for-an-empty-descriptor): media type `application/vnd.oci.empty.v1+json`, size `2`, digest `sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a`, the blob `{}`. The package has nothing to configure; the blob is in the blob storage like any other.
- **`layers`** *array of [bundle descriptors](#bundle-descriptor)* — REQUIRED, non-empty.
  At most one bundle per type and architecture (architecture names compared as [below](#architecture-names)), and a bundle that names no architecture is the only bundle of its type: a consumer is never left to choose between two.

### Bundle Descriptor

- **`mediaType`** — `application/vnd.tier4.ota.update-agent.bundle.v1`.
- **`digest`**, **`size`** — of the bundle as stored.
- **`annotations`** — REQUIRED:
  - **`vnd.tier4.ota.update-agent.type`** *string* — REQUIRED. What the bundle is; a consumer takes only a type it implements. The types defined here:
    - `tier4.otaclient.squashfs.v1` — otaclient's squashfs release image, as in the OTAClient release package.
    - `tier4.ota.agent.v1` — the agent that applies [partition-based payloads](partition_image.md), as a gzip-compressed tar.

    Other values are other consumers' types, opaque to this specification.
  - **`vnd.tier4.ota.update-agent.version`** *string* — REQUIRED. The version of the agent in the bundle.
  - **`vnd.tier4.ota.update-agent.architecture`** *string* — OPTIONAL. The machine it runs on. A bundle without one is one the publisher says runs on any machine.

### Architecture Names

The same machine goes by several names across the tools that build and consume an image; they are compared as one: `x86_64` and `amd64` are `x86_64`, `aarch64` and `arm64` are `arm64`, in any case. Any other name is compared exactly as it is.

## Selecting a Bundle

A consumer of type `T` running on machine `M` takes the bundle of type `T` whose architecture is `M`, or, failing that, the bundle of type `T` that names no architecture; with the rule above there is at most one.
A consumer told by its campaign which version it is to become takes that bundle only when its version is exactly that one.
No bundle is a valid outcome: the image ships nothing for this consumer, which applies the payload with the agent it runs.

## Example

```json
{
  "schemaVersion": 2,
  "mediaType": "application/vnd.oci.image.manifest.v1+json",
  "config": {
    "mediaType": "application/vnd.oci.empty.v1+json",
    "size": 2,
    "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
  },
  "layers": [
    {
      "mediaType": "application/vnd.tier4.ota.update-agent.bundle.v1",
      "size": 1830400,
      "digest": "sha256:0c5f…",
      "annotations": {
        "vnd.tier4.ota.update-agent.type": "tier4.ota.agent.v1",
        "vnd.tier4.ota.update-agent.version": "2.10.0",
        "vnd.tier4.ota.update-agent.architecture": "arm64"
      }
    },
    {
      "mediaType": "application/vnd.tier4.ota.update-agent.bundle.v1",
      "size": 1835008,
      "digest": "sha256:9a41…",
      "annotations": {
        "vnd.tier4.ota.update-agent.type": "tier4.ota.agent.v1",
        "vnd.tier4.ota.update-agent.version": "2.10.0",
        "vnd.tier4.ota.update-agent.architecture": "x86_64"
      }
    }
  ]
}
```
