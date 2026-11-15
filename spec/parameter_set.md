# Parameter Set

A parameter set carries **the files of a base image's parameter slots**, delivered without the base: a small OTA image of its own (a *parameter image*) whose payload for an ECU replaces a few directories of the rootfs that ECU runs.
The consumer does not write a standby slot and does not reboot: it lays the set over the running base and has what reads the parameters restart.

A set is made for one base payload and is applied only on it, so that what was tested is what runs: the two are identified by the digests of the base payload's manifest and of the set's manifest.

Schema as code: [`parameter_set/schema.py`](../src/ota_image_libs/v1/parameter_set/schema.py), [`parameter_set/slots.py`](../src/ota_image_libs/v1/parameter_set/slots.py), the layer in [`parameter_set/layer.py`](../src/ota_image_libs/v1/parameter_set/layer.py).

## Media Types

Listed in [media_types.md](media_types.md#parameter-set-media-types).

## Parameter Slots

A base image declares the directories a set may replace in its config: `parameter_slots` in the [image config](image_config.md) of a file-based payload, or in the [partition image config](partition_image.md#partition-image-config).
The field is OPTIONAL and a consumer that does not know it ignores it.

- **`parameter_slots`** *array of objects* — OPTIONAL, default empty. Names unique, and no slot's `path` is inside, or the same as, another's.
  No slot is over what a consumer reads for itself (`/boot`, `/etc/fstab`, `/opt/ota`, `/usr/share/ota`: the same path, inside, or containing it), and no slot's `apply` is inside a slot: a set carries files only, and what runs is the base's.
  - **`name`** *string* — REQUIRED. 1 to 64 letters, digits, `_`, `.` or `-`, starting with a letter or digit.
  - **`path`** *string* — REQUIRED. The directory the slot is: absolute, normalized, not `/`. The base ships the slot's default contents there, which is what the slot holds when no set fills it.
  - **`apply`** *string* — REQUIRED. How a change to the slot takes effect: the absolute path of an executable in the base that the consumer runs once the slot's new contents are in place, or `reboot`.
    The executable restarts what reads the parameters and changes no file.

```json
"parameter_slots": [
  {
    "name": "individual_params",
    "path": "/opt/autoware/vehicle/vehicle.j6_gen2/individual_params",
    "apply": "/opt/autoware/bin/apply-parameter-set"
  }
]
```

## Parameter Image

A parameter image is an OTA image like any other — `index.json`, `index.jwt`, the blob storage and the [artifact](ota_image_distribution.md) — whose [image index](image_index.md) lists a parameter set as each ECU's payload, identified by `ecu_id` and `ota_release_key`.
It carries no file table and no resource table, and only parameter sets: an index MUST NOT list a parameter set beside a base payload.

A release made of a parameter image names every ECU: an ECU that has no slot, or whose parameters this release does not change, gets the [empty set](#empty-set) or the same set again, not nothing.

## Image Manifest

An OCI image manifest (`application/vnd.oci.image.manifest.v1+json`, `schemaVersion` `2`) with `artifactType` `application/vnd.tier4.ota.parameter-set.v1`.
Its descriptor in the image index carries the same `artifactType`, which is REQUIRED there: it tells the set apart from a base payload, with which it shares the media type.

- **`config`** points to the [parameter set config](#parameter-set-config).
- **`layers`** has exactly one entry: the set's [layer](#layer) (`application/vnd.oci.image.layer.v1.tar+zstd`), or for an empty set the OCI empty descriptor (`application/vnd.oci.empty.v1+json`, the 2-byte blob `{}`).
- **`subject`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)* — REQUIRED. The manifest of the base payload, for the same ECU, that the set was made for: its media type, its `artifactType` (`application/vnd.tier4.ota.file-based-ota-image.v1` or `application/vnd.tier4.ota.partition-based-ota-image.v1`, REQUIRED), its digest and its size.
  This is a weak association: the parameter image does not carry the base's blobs.
- **`annotations`** — REQUIRED: `vnd.tier4.pilot-auto.platform.ecu`, `vnd.tier4.ota.release-key` and `vnd.tier4.ota.parameter-set.version`. The descriptor in the image index carries the first two, and MAY carry the version.

```json
{
  "schemaVersion": 2,
  "mediaType": "application/vnd.oci.image.manifest.v1+json",
  "artifactType": "application/vnd.tier4.ota.parameter-set.v1",
  "config": { "mediaType": "application/vnd.tier4.ota.parameter-set.config.v1+json", "digest": "sha256:…", "size": 640 },
  "layers": [
    { "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd", "digest": "sha256:…", "size": 18432 }
  ],
  "subject": {
    "mediaType": "application/vnd.oci.image.manifest.v1+json",
    "artifactType": "application/vnd.tier4.ota.file-based-ota-image.v1",
    "digest": "sha256:<the base payload's manifest>", "size": 818
  },
  "annotations": {
    "vnd.tier4.pilot-auto.platform.ecu": "autoware",
    "vnd.tier4.ota.release-key": "dev",
    "vnd.tier4.ota.parameter-set.version": "2026.10.29-1"
  }
}
```

## Parameter Set Config

Media type: `application/vnd.tier4.ota.parameter-set.config.v1+json`

- **`schemaVersion`** *int* — REQUIRED, MUST be `1`.
- **`mediaType`** *string* — REQUIRED, MUST be the media type above.
- **`name`** *string* — REQUIRED. The set's name; the same characters as a slot name.
- **`version`** *string* — REQUIRED. The set's version, 1 to 128 letters, digits, `_`, `.`, `+` or `-`, starting with a letter or digit. The same as the manifest's `vnd.tier4.ota.parameter-set.version`.
- **`description`**, **`created`** *string* — OPTIONAL.
- **`slots`** *array of objects* — OPTIONAL, default empty. The slots the set fills, each `{name, path}` as the base declares it; names unique, paths disjoint.
- **`diff_ids`** *array of strings* — REQUIRED with a slot, one `sha256:…` per layer: the digest of the layer's uncompressed tar, as an OCI image config's `rootfs.diff_ids`. Empty for an empty set.
- **`files`** *array of objects* — OPTIONAL. The set's regular files, each `{path, size, digest}` with `path` relative to `/` and under one of `slots`. When present it lists exactly the regular files of the layer, and a consumer MUST refuse a set whose `files` disagree with its layer; the layer is what is applied.

A consumer MUST refuse a config whose `version` differs from the manifest's, or which fills a slot while the manifest carries the empty descriptor, or the other way round.

## Layer

An OCI image layer: a tar, compressed with zstd.
Paths are relative to `/` and normalized (a leading `./` is allowed). For each slot in the config's `slots`, the layer holds:

- the slot's directory itself,
- the opaque whiteout `.wh..wh..opq` directly in it: an empty regular file, which says that the slot's directory **replaces** the base's rather than adding to it,
- the regular files and directories below it, each directory before what it holds.

Nothing else: no member outside a slot, no symbolic or hard link, no device, FIFO or sparse file, no whiteout other than the slot's opaque one, no setuid, setgid or sticky bit, no path twice.
Owners and times carry no meaning: a consumer creates the files as its own (root on a device) with the members' permission bits.
The builder writes members in a fixed order with owner `0:0` and time `0`, so the same slot contents always make the same layer.

### Empty Set

An empty set fills no slot: its config has no `slots` and no `diff_ids`, and its manifest's one layer is the OCI empty descriptor.
Applied, it leaves every slot with the base's defaults.

## Applying a Set

Applying a set makes the ECU's parameter state **the base plus this one set**: each slot the set fills holds exactly the set's files for it, and every other slot holds the base's defaults, whatever was applied before.
This is what makes the two digests enough to tell what runs.

A consumer:

1. Verifies the parameter image's `index.jwt` and the chain from it to the set's manifest, config and layer, as for any OTA image.
2. Refuses a set whose `subject.digest` is not the digest of the manifest of the base payload it runs, or that fills a slot the base does not declare at the same `path`.
3. Stores the set where it survives a restart of the consumer and a reboot of the same base, and never in the standby slot.
4. Unpacks the layer into a place of its own and checks it against the config's `diff_ids` (and the layer descriptor's digest), then lays each slot over the base without writing the base's files — a read-only bind mount of the unpacked directory, or an overlay whose upper directory is opaque.
   Its unpacked copy and what mounts it at boot (a managed block of `/etc/fstab`, say) are the consumer's own, and may live in the running slot when that slot is writable; the files under the slots' paths are never written.
5. Runs the `apply` of each slot whose contents changed (a slot's files, by path and digest, differ from what it held), or reboots for one whose `apply` is `reboot`; a slot whose contents are the same is not applied again.
   When placing a slot or an `apply` fails, it restores the previous state, runs the `apply` again and reports the failure.
6. On a later boot of the same base, lays the stored set again before what reads the parameters starts, and falls back to the base's defaults if the set no longer verifies.

After a full update to another base, a stored set is not applied: its `subject` no longer matches, and the ECU runs with the new base's defaults.

A consumer whose layout cannot take a parameter set refuses the ECU's set, an empty one included, without changing anything: a release that names such an ECU fails there, so such an ECU is given base images only.

## Compatibility

A consumer whose ota-image-libs does not know parameter sets refuses a parameter image without changing anything:
from 0.6.0 on, an index entry with an unknown `artifactType` fails the parse of the whole index; before 0.6.0, the entry is taken for a file-based payload and its manifest, which has no file table, fails to parse.
A consumer that does not know `parameter_slots` ignores the field in a base's image config.
