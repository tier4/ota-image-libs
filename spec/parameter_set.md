# Parameter Set

A parameter set carries **the files of a few directories of an ECU's rootfs** (its *slots*), delivered on their own: a small OTA image (a *parameter image*) whose payload for an ECU replaces those directories in the rootfs that ECU runs.
The consumer does not write a standby slot and does not reboot: it lays the set over the running base and runs what makes the change take effect.

A set names no base. Which bases a set suits is decided where the release is evaluated, not by the image: a set is applied on whatever base the ECU runs, as long as that base has the set's slots and the commands that apply them.
A slot may hold any regular file, executables included.

Schema as code: [`parameter_set/schema.py`](../src/ota_image_libs/v1/parameter_set/schema.py), [`parameter_set/slots.py`](../src/ota_image_libs/v1/parameter_set/slots.py), the layer in [`parameter_set/layer.py`](../src/ota_image_libs/v1/parameter_set/layer.py).

## Media Types

Listed in [media_types.md](media_types.md#parameter-set-media-types).

## Parameter Image

A parameter image is an OTA image like any other — `index.json`, `index.jwt`, the blob storage and the [artifact](ota_image_distribution.md) — whose [image index](image_index.md) lists a parameter set as an ECU's payload, identified by `ecu_id` and `ota_release_key`: the signature over the index binds the set to the ECU.
It carries no file table and no resource table, and only parameter sets: an index MUST NOT list a parameter set beside a base payload.

A parameter image is usually made for one ECU. A release made of it names the ECUs it has a set for; the other ECUs keep what they have.

## Image Manifest

An OCI image manifest (`application/vnd.oci.image.manifest.v1+json`, `schemaVersion` `2`) with `artifactType` `application/vnd.tier4.ota.parameter-set.v1`.
Its descriptor in the image index carries the same `artifactType`, which is REQUIRED there: it tells the set apart from a base payload, with which it shares the media type.

- **`config`** points to the [parameter set config](#parameter-set-config).
- **`layers`** has exactly one entry: the set's [layer](#layer) (`application/vnd.oci.image.layer.v1.tar+zstd`), or for an empty set the OCI empty descriptor (`application/vnd.oci.empty.v1+json`, the 2-byte blob `{}`).
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
  "annotations": {
    "vnd.tier4.pilot-auto.platform.ecu": "autoware",
    "vnd.tier4.ota.release-key": "dev",
    "vnd.tier4.ota.parameter-set.version": "6.1.0"
  }
}
```

## Parameter Set Config

Media type: `application/vnd.tier4.ota.parameter-set.config.v1+json`

- **`schemaVersion`** *int* — REQUIRED, MUST be `1`.
- **`mediaType`** *string* — REQUIRED, MUST be the media type above.
- **`name`** *string* — REQUIRED. The set's name: 1 to 64 letters, digits, `_`, `.` or `-`, starting with a letter or digit.
- **`version`** *string* — REQUIRED. The set's version, 1 to 128 letters, digits, `_`, `.`, `+` or `-`, starting with a letter or digit. The same as the manifest's `vnd.tier4.ota.parameter-set.version`.
- **`description`**, **`created`** *string* — OPTIONAL.
- **`slots`** *array of objects* — OPTIONAL, default empty. The [slots](#slots) the set fills.
- **`diff_ids`** *array of strings* — REQUIRED with a slot, one `sha256:…` per layer: the digest of the layer's uncompressed tar, as an OCI image config's `rootfs.diff_ids`. Empty for an empty set.
- **`files`** *array of objects* — OPTIONAL. The set's regular files, each `{path, size, digest}` with `path` relative to `/` and under one of `slots`. When present it lists exactly the regular files of the layer, and a consumer MUST refuse a set whose `files` disagree with its layer; the layer is what is applied.

A consumer MUST refuse a config whose `version` differs from the manifest's, or which fills a slot while the manifest carries the empty descriptor, or the other way round.

```json
{
  "schemaVersion": 1,
  "mediaType": "application/vnd.tier4.ota.parameter-set.config.v1+json",
  "name": "j6_gen2",
  "version": "6.1.0",
  "slots": [
    {
      "name": "individual_params",
      "path": "/opt/autoware/vehicle/vehicle.j6_gen2/individual_params",
      "apply": "/opt/autoware/vehicle/vehicle.j6_gen2/apply.sh"
    }
  ],
  "diff_ids": ["sha256:…"],
  "files": [{ "path": "opt/autoware/vehicle/vehicle.j6_gen2/individual_params/…", "size": 812, "digest": "sha256:…" }]
}
```

### Slots

A slot is a directory of the base's rootfs that the set replaces as a whole. The base ships the slot's default contents there, which is what the slot holds when no set fills it; the base declares nothing else.

- **`name`** *string* — REQUIRED. 1 to 64 letters, digits, `_`, `.` or `-`, starting with a letter or digit.
- **`path`** *string* — REQUIRED. The directory: absolute, normalized, not `/`.
- **`apply`** *string* — REQUIRED. How a change to the slot takes effect: the absolute path of an executable of the base that the consumer runs once the slot's new contents are in place, and again once they are taken away; or `reboot`.
  The executable restarts what reads the slot, and fails when that does not come back; it changes no file.

Names are unique, and no slot's `path` is inside, or the same as, another's.
No slot is over what a consumer reads for itself (`/boot`, `/etc/fstab`, `/opt/ota`, `/usr/share/ota`: the same path, inside, or containing it), and no slot's `apply` is inside a slot: what the consumer runs is the base's, so that it is there to run again when the set is taken away.

## Layer

An OCI image layer: a tar, compressed with zstd.
Paths are relative to `/` and normalized (a leading `./` is allowed). For each slot in the config's `slots`, the layer holds:

- the slot's directory itself,
- the opaque whiteout `.wh..wh..opq` directly in it: an empty regular file, which says that the slot's directory **replaces** the base's rather than adding to it,
- the regular files and directories below it, each directory before what it holds.

Nothing else: no member outside a slot, no symbolic or hard link, no device, FIFO or sparse file, no whiteout other than the slot's opaque one, no setuid, setgid or sticky bit, no path twice.
Owners and times carry no meaning: a consumer creates the files as its own (root on a device) with the members' permission bits, the execute bits included.
The builder writes members in a fixed order with owner `0:0` and time `0`, so the same slot contents always make the same layer.

### Empty Set

An empty set fills no slot: its config has no `slots` and no `diff_ids`, and its manifest's one layer is the OCI empty descriptor.
Applied, it takes away the set before, if any: every slot goes back to the base's defaults.

## Applying a Set

Applying a set makes the ECU's state **the base plus this one set**: each slot the set fills holds exactly the set's files, and every slot of the set before that this set does not fill goes back to the base's defaults.

A consumer:

1. Verifies the parameter image's `index.jwt` and the chain from it to the set's manifest, config and layer, as for any OTA image, and takes the set the index lists for its own ECU.
2. Refuses, without changing anything, a set the running base has no room for: a slot whose `path` is not a directory of the base, or an `apply` that is not an executable file of the base, either at its real path (no symbolic link on the way).
3. Stores the set where it survives a restart of the consumer and a reboot, and never in the standby slot.
4. Unpacks the layer into a place of its own and checks it against the config's `diff_ids` (and the layer descriptor's digest), then lays each slot over the base without writing the base's files — a read-only bind mount of the unpacked directory (`nosuid`, `nodev`; execution allowed), or an overlay whose upper directory is opaque.
   Its unpacked copy and what mounts it at boot (a managed block of `/etc/fstab`, say) are the consumer's own, and may live in the running slot when that slot is writable; the files under the slots' paths are never written.
5. Runs the `apply` of each slot whose contents changed (filled by one of the two sets and not the other, or by both with other files, by path and digest), or reboots for one whose `apply` is `reboot`; a slot whose contents are the same is not applied again. The `apply` of a slot taken away is the one the set before named.
   When placing a slot or an `apply` fails, it restores the previous state, runs the `apply` again and reports the failure.
6. On a later boot, lays the stored set again before what reads the slots starts.
   What the ECU runs changes by an update only: a consumer that finds its stored copy changed (a file edited, added or removed) keeps it in place and records the finding, and the next update of the set replaces the copy and runs the `apply` of every slot it fills, whatever the file lists say.

A full update to a base does not carry a stored set over: the ECU runs with the new base's defaults until a set is delivered again.

A consumer whose layout cannot take a parameter set refuses the ECU's set, an empty one included, without changing anything: a release that names such an ECU fails there, so such an ECU is given base images only.

## Compatibility

A consumer whose ota-image-libs does not know parameter sets refuses a parameter image without changing anything:
from 0.6.0 on, an index entry with an unknown `artifactType` fails the parse of the whole index; before 0.6.0, the entry is taken for a file-based payload and its manifest, which has no file table, fails to parse.
