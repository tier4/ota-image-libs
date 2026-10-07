# Partition-based OTA Image Payload

A partition-based OTA image payload carries **whole partition images** instead of the files of a rootfs.
It is for devices whose root filesystem is read-only and integrity-protected (for example an ext4 image with a dm-verity hash tree appended), where an update cannot be assembled file by file on the device:
the update agent writes the images onto the standby slot of an A/B layout as they are, or hands one opaque vendor package to the platform's own updater.

It sits beside the file-based payload in the same OTA image: both are [image manifests](image_manifest.md) identified by `ecu_id` and `ota_release_key`, listed in the same [image index](image_index.md), signed by the same [index JWT](index_jwt.md) and packed into the same [artifact](ota_image_distribution.md).
One OTA image MAY carry payloads of both kinds for different ECUs.

Schema as code: [`partition_image/schema.py`](../src/ota_image_libs/v1/partition_image/schema.py)

## Media Types

Listed in [media_types.md](media_types.md#partition-based-ota-image-media-types).

## Image Manifest

The image manifest of a partition-based payload is an OCI image manifest (`application/vnd.oci.image.manifest.v1+json`, `schemaVersion` `2`) with `artifactType` set to `application/vnd.tier4.ota.partition-based-ota-image.v1`.

- **`config`** points to the [partition image config](#partition-image-config).
- **`layers`** lists every blob the payload ships — each partition image or, for a partition shipped as a delta, the delta; the boot files tar; each data image or its delta; the firmware package; the vendor package — so that tools can account for them without reading the config.
- **`annotations`** are the same as the file-based [image manifest](image_manifest.md#annotations-for-image-manifest): `vnd.tier4.pilot-auto.platform.ecu` and `vnd.tier4.ota.release-key` are REQUIRED and identify the payload; the descriptor of the manifest in the image index carries the same two.

A consumer that supports only file-based payloads MUST recognise the `artifactType` and refuse a partition-based payload rather than treat it as a rootfs.

## Partition Image Config

The partition image config is a per-payload JSON metadata file.

Media type: `application/vnd.tier4.ota.partition-based-ota-image.config.v1+json`

- **`schemaVersion`** *int* — REQUIRED, MUST be `1`.
- **`mediaType`** *string* — REQUIRED, MUST be the media type above.
- **`resource_digest_alg`** *string* — REQUIRED, MUST be `sha256`.
- **`description`** *string* — OPTIONAL.
- **`created`** *string* — OPTIONAL, ISO 8601.
- **`architecture`** *string* — REQUIRED, e.g. `x86_64`, `aarch64`.
- **`os`**, **`os.version`** *string* — OPTIONAL.
- **`image_version`** *string* — REQUIRED. The version the device reports once this payload is installed and running.
  An update agent MUST refuse a payload whose `image_version` differs from the version the campaign announces: after the reboot the device reports what the image carries, and a campaign whose version that is not can never be seen to finish.
- **`delivery`** *string* — REQUIRED, one of:
  - `direct` — the update agent writes each partition itself, from the images listed under `partitions`.
  - `vendor-package` — the payload is one opaque `package` that the platform's own updater applies; `partitions` then only documents what that package does.
- **`partitions`** *array of [partition entries](#partition-entry)* — REQUIRED, non-empty, names unique.
  It names every partition role the update concerns, including the ones it leaves alone: a role that is not listed is not part of the contract, and an agent MUST fail rather than guess.
- **`data_images`** *array of [Data Image Entry](#data-image-entry)* — OPTIONAL, default empty. Images the device keeps as files on a partition no update writes and mounts at a path, each updatable on its own.
  Applied by the agent under either delivery (a `vendor-package` writes partitions, not these). A payload whose partitions are all `keep` and whose `data_images` is not empty updates only those images.
- **`firmware`** *[Firmware Entry](#firmware-entry)* — OPTIONAL. A firmware package for the platform's own firmware updater: the parts of the device no partition image reaches (the bootloader and the firmware beside it), updated across the same trial boot as the partitions. Under either delivery.
- **`package`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — REQUIRED with `delivery: vendor-package`, MUST be absent with `direct`.
  Media type `application/vnd.tier4.ota.partition-based-ota-image.vendor-package.v1`, or `…vendor-package.v1+zstd` for one stored [compressed](#compressed-blobs); the OPTIONAL annotation `vnd.tier4.ota.partition-image.vendor-package.format` names the package format.
- **`sys_config`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — OPTIONAL, a [sys config](sys_config.md).
  Informational for a partition-based payload, see [sys_config.md](sys_config.md).
- **`labels`** *string-string map* — REQUIRED: `vnd.tier4.image.base-image`, `vnd.tier4.ota.image.blobs-count` and `vnd.tier4.ota.image.blobs-size` (the blobs of this payload); OPTIONAL `vnd.tier4.image.os`, `vnd.tier4.image.os.version`.

### Partition Entry

- **`name`** *string* — REQUIRED. The partition **role**, never a device path: the agent resolves a role to a device on the running system (for instance from a GPT partition name), and an unresolvable role is a hard error.
  The roles a two-slot layout typically declares: `rootfs`, `boot`, `scratch`, `identity`, `optdata`.
- **`action`** *string* — REQUIRED, one of:
  - `write` — the partition is written from `image` (or by the vendor package).
  - `mkfs` — the partition gets a fresh, empty filesystem.
  - `keep` — the partition is not touched. Anything that must survive the update (per-vehicle identity, persistent data) lives on a `keep` role.
- **`image`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — REQUIRED for `write` performed by the agent, MUST be absent otherwise. Either:
  - a **partition image** (`…partition.v1`): raw bytes written to the partition from its start.
    OPTIONAL annotations: `vnd.tier4.ota.partition-image.filesystem` (e.g. `ext4`); for an image with a dm-verity hash tree appended, `vnd.tier4.ota.partition-image.verity.root-hash` and `vnd.tier4.ota.partition-image.verity.hash-offset` (bytes), which let an installer verify what it wrote without parsing the boot files.
    With media type `…partition.v1+zstd` the blob is stored [compressed](#compressed-blobs) and the annotations also carry what it decodes to.
  - the **boot files** (`…boot-files.v1.tar`): a tar of regular files, without directories, to be unpacked into the slot's boot directory.
    It carries the kernel, the initramfs and the boot loader fragment that names the root's verity root hash, which is why a `boot` role is always written together with its `rootfs`.
- **`delta`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — OPTIONAL, media type `application/vnd.tier4.ota.partition-based-ota-image.partition-delta.v1.tar`; only with `action: write` performed by the agent, and only beside an `image`.
  It carries a [block diff](#partition-delta) that reconstructs `image` from bytes the device already has, so that a campaign transfers the change instead of the whole partition.
  REQUIRED annotations: `vnd.tier4.ota.partition-image.delta.algorithm` (how to apply it; `block-diff` is the one defined), `vnd.tier4.ota.partition-image.delta.source-digest` and `vnd.tier4.ota.partition-image.delta.source-size` (the bytes it applies to, named by digest because a digest identifies them exactly and a version string does not).
  **`image` still describes what the partition must end up holding** — its digest, its size and its verity annotations (for a compressed image, the uncompressed digest and size in its annotations) — and the agent MUST verify the reconstruction against it. A partition with a delta ships only the delta: the image's bytes are not in the [blob storage](#blob-storage), and the manifest's `layers` lists the delta and not the image.
  An agent that does not understand the delta's algorithm, or whose partition does not hash to `source-digest`, MUST refuse the payload rather than write anything: a device at another version needs a payload built for it.
  A delta whose `source-digest` is the image's own digest is valid: it is the smallest statement that the device already holds these bytes, and is how a release ships a partition or data image it does not change (a firmware-only release, say, or a rootfs release whose model sets are unchanged).
  A delta reconstructs a **partition image**; the boot files tar takes none, because it is unpacked into a directory and nothing on the device is the byte stream a patch would apply to.
- **`performed_by`** *string* — OPTIONAL, `agent` (default) or `package`. With `delivery: vendor-package` every `write` is `performed_by: package`. A `vendor-package` payload carries no `delta`: its own updater applies whatever delta the package contains.

### Data Image Entry

A data image is a read-only filesystem image (for instance a squashfs of ML models) with a dm-verity hash tree appended, like a partition image, but written to a **file** on a partition no update touches and mounted at a path, instead of to a slot. It changes on its own cadence: a payload may carry a new one beside a rootfs update, or carry nothing else.

- **`name`** *string* — REQUIRED. A directory name (`[A-Za-z0-9][A-Za-z0-9_.-]*`, at most 64 characters), unique in the config: the device keeps the image under it.
- **`version`** *string* — REQUIRED. The data image's own version, what the device reports for it.
- **`mount`** *string* — REQUIRED. An absolute path below `/` where the device mounts the image.
- **`requires`** *object* — OPTIONAL, default empty. What the running system must be for this image to be installed, keyed by `rootfs` (the root image's version) or another data image's name, each a half-open version range `{"min": "2.4.0", "max": "3.0.0"}` (`min` inclusive, `max` exclusive, either side optional; dotted components compared numerically where both are numbers). An agent MUST refuse an image whose requirements the device does not meet.
- **`image`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — REQUIRED. Media type `application/vnd.tier4.ota.partition-based-ota-image.data-image.v1`, or `…data-image.v1+zstd` for one stored [compressed](#compressed-blobs). The same OPTIONAL annotations as a partition image: `vnd.tier4.ota.partition-image.filesystem`, and the verity root hash and hash offset.
- **`delta`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — OPTIONAL. A [block diff](#partition-delta) against the data image the device currently holds, with the same annotations and rules as a partition's; the payload then ships only the delta and `image` describes the result.

### Firmware Entry

Firmware is what boots the device before any partition image is read: the bootloader chain and the firmware beside it, in storage the agent does not write. The platform's own updater does — from a package in its own format, which this payload carries so that it travels, is verified and is judged with the rest of the release. The agent stages the package where the platform's updater picks it up (a UEFI capsule on the EFI system partition, say) and arms nothing of its own for it; the platform applies it on the trial boot, and the same health check decides whether the device stays on what it brought up.

Firmware is slotted by the platform where it is slotted at all, and on a platform whose rootfs slot follows the boot chain a firmware update is also a slot switch: a payload carrying firmware there MUST write the slot roles too, if only as a delta that copies the committed slot. An agent MUST refuse a firmware package whose `format` its platform's updater does not take.

- **`name`** *string* — REQUIRED. A directory name (`[A-Za-z0-9][A-Za-z0-9_.-]*`, at most 64 characters), what a campaign and a version query address the firmware by; one namespace with the data image names.
- **`version`** *string* — REQUIRED. The firmware's own version, what the device reports for it afterwards.
- **`format`** *string* — REQUIRED. The package format, opaque to this specification; it MUST equal the package descriptor's format annotation.
- **`requires`** *object* — OPTIONAL, as a data image's.
- **`package`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — REQUIRED. Media type `application/vnd.tier4.ota.partition-based-ota-image.firmware-package.v1`, or `…firmware-package.v1+zstd` for one stored [compressed](#compressed-blobs); the REQUIRED annotation `vnd.tier4.ota.partition-image.firmware.format` names the format.

### Partition Delta

A delta is a **block diff**: the target image described as runs of fixed-size blocks that are copies of blocks the source already holds (named by offset), all zeros, or literal bytes the source does not have.
A filesystem image is made of blocks — ext4 places data and metadata on 4 KiB boundaries — so a file that moved between two builds is still found, block by block, wherever it went, and nothing is windowed: a source of any size is diffed in one pass on each side.
It is the block model platform updaters use for their own packages, so one pipeline shape — old image and new image in, delta out — serves every platform.

The blob is a **tar of two members, in this order**, so that it can be applied from a stream that cannot seek:

- `ops.json` — `{"block_size": B, "target_size": T, "source_size": S, "ops": [...]}`, each op one of `["c", length, source_offset]` (copy from the source), `["z", length]` (zeros) or `["l", length]` (the next `length` literal bytes). Lengths sum to `target_size`; a copy stays inside `source_size`.
- `literals.zst` — the literal runs, in target order, as one zstd stream compressed with long-range matching over a window of at most 128 MiB (`--long=27`), which a plain `zstd -d` accepts without a flag. The window is what shrinks them: the literals of a rebuild are largely compressed data, which a wider window finds repeated and a higher level does not.

Applying it reads the source at the offsets the runs name, decodes the literals as a stream and writes the result straight to the partition, hashing on the way: the source is never copied, and memory is bounded by the decoder's window.
The agent MUST check the ops against `source-size` and the image's size before writing, and MUST verify the reconstruction against `image`.

Reference implementation: [`ota_image_tools/libs/block_diff.py`](../src/ota_image_tools/libs/block_diff.py).

### Compressed Blobs

A partition image, a data image, a firmware package or a vendor package MAY be stored zstd-compressed, with the media type suffixed `+zstd`.
The descriptor's `digest` and `size` are then the stored bytes', as everywhere in OCI, and the annotations `vnd.tier4.ota.partition-image.uncompressed.digest` (`sha256:…`) and `vnd.tier4.ota.partition-image.uncompressed.size` are REQUIRED: they name what the partition ends up holding, which is what a reconstruction, a delta's `source-digest` and an installer's check refer to.
A consumer decodes the blob as a stream on the way to the partition (or, for a vendor package, while staging it for the platform's updater) and MUST verify the decoded bytes against the annotations.

The boot files tar and the delta are stored as they are (the delta compresses its own literals).

### Blob Storage

The blobs of a partition-based payload are stored in the blob storage **as they are**: the storage optimization filters of the [resource table](resource_table.md) (bundle, compress, slice) MUST NOT be applied to them, and they are not listed in the resource table.
An agent streams a partition image straight from the artifact onto the partition, and an installer may map a raw image in place, both of which need the blob's bytes contiguous; a `+zstd` blob is contiguous too, decoded on the way.

## Example

```json
{
  "schemaVersion": 1,
  "mediaType": "application/vnd.tier4.ota.partition-based-ota-image.config.v1+json",
  "resource_digest_alg": "sha256",
  "created": "2026-09-15T04:19:00Z",
  "architecture": "x86_64",
  "os": "linux",
  "os.version": "24.04",
  "image_version": "1.2.0",
  "delivery": "direct",
  "partitions": [
    {
      "name": "rootfs",
      "action": "write",
      "image": {
        "mediaType": "application/vnd.tier4.ota.partition-based-ota-image.partition.v1",
        "size": 1479573504,
        "digest": "sha256:4089a1b1…",
        "annotations": {
          "vnd.tier4.ota.partition-image.filesystem": "ext4",
          "vnd.tier4.ota.partition-image.verity.root-hash": "194fde59…",
          "vnd.tier4.ota.partition-image.verity.hash-offset": 1468006400
        }
      }
    },
    {
      "name": "boot",
      "action": "write",
      "image": {
        "mediaType": "application/vnd.tier4.ota.partition-based-ota-image.boot-files.v1.tar",
        "size": 82339840,
        "digest": "sha256:a9925ab2…"
      }
    },
    { "name": "scratch", "action": "mkfs" },
    { "name": "identity", "action": "keep" },
    { "name": "optdata", "action": "keep" }
  ],
  "data_images": [
    {
      "name": "models",
      "version": "2026.9.1",
      "mount": "/opt/models",
      "requires": { "rootfs": { "min": "1.2.0", "max": "2.0.0" } },
      "image": {
        "mediaType": "application/vnd.tier4.ota.partition-based-ota-image.data-image.v1+zstd",
        "size": 171000000,
        "digest": "sha256:7c0e2a19…",
        "annotations": {
          "vnd.tier4.ota.partition-image.filesystem": "squashfs",
          "vnd.tier4.ota.partition-image.verity.root-hash": "ab31c0…",
          "vnd.tier4.ota.partition-image.verity.hash-offset": 209715200,
          "vnd.tier4.ota.partition-image.uncompressed.digest": "sha256:9d4f…",
          "vnd.tier4.ota.partition-image.uncompressed.size": 211812352
        }
      }
    }
  ],
  "labels": {
    "vnd.tier4.image.base-image": "ubuntu:24.04",
    "vnd.tier4.image.os": "linux",
    "vnd.tier4.image.os.version": "24.04",
    "vnd.tier4.ota.image.blobs-count": 3,
    "vnd.tier4.ota.image.blobs-size": 1732913344
  }
}
```

With `delivery: vendor-package` the config carries `package` instead of images, and every written role says who performs it:

```json
{
  "delivery": "vendor-package",
  "package": {
    "mediaType": "application/vnd.tier4.ota.partition-based-ota-image.vendor-package.v1",
    "size": 3221225472,
    "digest": "sha256:…",
    "annotations": { "vnd.tier4.ota.partition-image.vendor-package.format": "example-updater-package" }
  },
  "partitions": [
    { "name": "rootfs", "action": "write", "performed_by": "package" },
    { "name": "boot", "action": "write", "performed_by": "package" },
    { "name": "scratch", "action": "mkfs", "performed_by": "package" },
    { "name": "identity", "action": "keep" },
    { "name": "optdata", "action": "keep" }
  ]
}
```
