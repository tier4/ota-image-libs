# Parameter Set

A parameter set carries **the files of a few directories of an ECU's rootfs** (its *slots*), delivered on their own: a small OTA image (a *parameter image*) whose payload for an ECU replaces those directories in the rootfs that ECU runs.
The consumer does not write a standby slot and does not reboot: it lays the set over the running base and runs what makes the change take effect.

A set names no base. Which bases a set suits is decided where the release is evaluated, not by the image: a set is applied on whatever base the ECU runs, as long as that base has room for the set's slots and the commands that apply them, other than those the set carries itself.
A slot may hold any regular file, executables included, and the command that applies it.

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
- **`files`** *array of objects* — OPTIONAL. The set's regular files, each `{path, size, digest}` with `path` relative to `/` and under one of `slots`. When present, an empty list included, it lists exactly the regular files of the layer, and a consumer MUST refuse a set whose `files` disagree with its layer (by path, size and digest); the layer is what is applied.

A consumer MUST refuse a config whose `version` differs from the manifest's, or which fills a slot while the manifest carries the empty descriptor, or the other way round.

```json
{
  "schemaVersion": 1,
  "mediaType": "application/vnd.tier4.ota.parameter-set.config.v1+json",
  "name": "sample_vehicle",
  "version": "6.1.0",
  "slots": [
    {
      "name": "individual_params",
      "path": "/opt/autoware/vehicle/sample_vehicle/individual_params",
      "apply": "/opt/autoware/vehicle/sample_vehicle/apply.sh"
    }
  ],
  "diff_ids": ["sha256:…"],
  "files": [{ "path": "opt/autoware/vehicle/sample_vehicle/individual_params/…", "size": 812, "digest": "sha256:…" }]
}
```

### Slots

A slot is a directory of the base's rootfs that the set replaces as a whole. What the base has there is what the slot holds when no set fills it: its default contents, or nothing when the base does not have the directory; the base declares nothing else.

- **`name`** *string* — REQUIRED. 1 to 64 letters, digits, `_`, `.` or `-`, starting with a letter or digit.
- **`path`** *string* — REQUIRED. The directory: absolute, normalized, not `/`, and no component of it starts with `.wh.` (which a layer reads as a whiteout).
- **`apply`** *string* — REQUIRED. How a change to the slot takes effect: the absolute path of the executable that the consumer runs once the slot's new contents are in place, or `reboot`.
  What runs is the file at that path then: a file of the set when the path is inside one of the set's slots, the base's otherwise.
  The executable restarts what reads the slot, and fails when that does not come back; it changes no file.
  Nothing runs when a slot is taken away: that takes effect when what reads the slot restarts.

Names are unique, and no slot's `path` is inside, or the same as, another's.
No slot is over what a consumer, or the installer it drives, reads for itself (`/boot`, `/etc/fstab`, `/etc/ota`, `/opt/ota`, `/opt/data/ota`, `/usr/lib/ota`, `/usr/share/ota`: the same path, inside, or containing it), no slot's `apply` is in one of them, and no slot's `apply` is a slot's directory or a directory a slot is in.
An `apply` inside one of the set's slots is one of the set's regular files, executable, that others cannot write (neither the file nor a directory from its slot's directory down to it: it runs as root; the group is root's once the set is laid): when the config lists its `files`, it is among them.
A consumer MAY refuse, the same way, a slot over other paths it reads for itself; a path the base has behind a symbolic link is then reserved where the link leads as well.

## Layer

An OCI image layer: a tar, compressed with zstd.
Paths are relative to `/` and normalized (a leading `./` is allowed). For each slot in the config's `slots`, the layer holds:

- the slot's directory itself,
- the opaque whiteout `.wh..wh..opq` directly in it: an empty regular file, which says that the slot's directory **replaces** the base's rather than adding to it,
- the regular files and directories below it, each directory before what it holds.

Nothing else: no member outside a slot, no symbolic or hard link, no device, FIFO or sparse file, no whiteout other than the slot's opaque one, no setuid, setgid or sticky bit, no path twice.
After the last member comes the end-of-archive marker (two zero blocks), and after it zero padding only, 1 MiB at most for the marker and the padding together.
Owners and times carry no meaning: a consumer creates the files as its own (root on a device) with the members' permission bits, the execute bits included.
The builder writes members in a fixed order with owner `0:0` and time `0`, so the same slot contents always make the same tar, and so the same `diff_ids`; the compressed blob also depends on the compression level and the zstd library.

### Empty Set

An empty set fills no slot: its config has no `slots` and no `diff_ids`, and its manifest's one layer is the OCI empty descriptor.
Applied, it takes away the set before, if any: every slot goes back to the base's defaults, and nothing runs.

## Applying a Set

Applying a set makes the ECU's state **the base plus this one set**: each slot the set fills holds exactly the set's files, and every slot of the set before that this set does not fill goes back to the base's defaults.

A consumer:

1. Verifies the parameter image's `index.jwt` and the chain from it to the set's manifest, config and layer, as for any OTA image, and takes the set the index lists for its own ECU.
2. Refuses, without changing anything, a set the running base has no room for: a slot whose `path` the base has as something other than a directory, or reaches through anything other than directories, or an `apply` of the base (one outside the set's slots) that is not an executable file of the base, either at its real path (no symbolic link on the way).
   A slot directory the base does not have is room enough for a consumer that can make it: it makes it as the mount point when it lays the slot (an empty directory, and each missing parent, owned by root with mode `0755`), and leaves it when the slot is taken away. A consumer that cannot write the base refuses such a set here.
   An `apply` inside the set's slots is checked against the set instead (step 4); a config that lists its `files` and not that `apply` is refused here.
3. Stores the set, with the running base's image ID, where it survives a restart of the consumer and a reboot, never in the standby rootfs slot, and where only root can write (the store and every directory above it): in the running rootfs slot, or on a writable partition both rootfs slots share (the only place when the rootfs slots are read-only).
   The image ID is the `image_id` the image build writes into the base's version file, `/usr/share/ota/version.json` (not the payload's `ecu_id` and `ota_release_key`). A store both rootfs slots share needs it to tell the bases apart: a consumer with such a store refuses a set, without changing anything, when the running base has no image ID.
4. Unpacks the layer into a place of its own and checks it against the config's `diff_ids` (and the layer descriptor's digest), and each `apply` inside the set's slots against the unpacked files (an executable regular file, at its real path, that others cannot write), refusing the set as in step 2 before the stored set is replaced.
   It then lays each slot over the base without writing the base's files — a read-only bind mount of the unpacked directory (`nosuid`, `nodev`; execution allowed), or an overlay whose upper directory is opaque — checking again, right before it mounts, that the slot's path is a directory at its real path.
   Its unpacked copy is the consumer's own, and so is what lays it at boot (the consumer run by a unit the base ships, before what reads the slots, say); the files under the slots' paths are never written.
   It takes a slot's mount away without waiting for what uses the slot (a lazy unmount): a program that runs from the slot's files keeps them until it exits, and what opens them after sees what is there now.
5. Runs the `apply` of each slot this set fills whose contents changed (filled by this set only, or by both sets with other files, by path and digest), or reboots for one whose `apply` is `reboot`; a slot whose contents are the same is not applied again, and a slot taken away (filled by the set before only) runs nothing.
   When placing a slot or an `apply` fails, it restores the previous state, runs the `apply` of the slots the restored set fills that changed back, and reports the failure.
   What reads a slot that nothing runs for (taken away, or restored to the base's after a failed `apply`) goes on as it was (as the failed `apply` left it) until it restarts: from then on it reads the base's.
   Whenever a slot is taken away (by a set without it, by undoing a failed set, or by dropping a set), what mounts it at boot stops doing so first, before its mount is taken away: a later boot does not lay it again even when the rest fails.
6. On a later boot, lays the stored set again before what reads the slots starts, when the running base is the one the set was applied on (its image ID is the one stored with the set).
   A set stored for another base is not laid, and it is not the set before for a set applied on the running base (step 5 compares with, and restores to, the running base's defaults). The consumer keeps it while the update to the running base can still fall back, and drops it once the ECU has committed to that base: an ECU that falls back to the base the set was applied on lays it again.
   What the ECU runs changes by an update only: a consumer that finds its stored copy changed (a file edited, added or removed) keeps it in place and records the finding, and the next update of the set replaces the copy and runs the `apply` of every slot it fills, whatever the file lists say.

A full update to a base does not carry a stored set over: the ECU runs with the new base's defaults until a set is delivered again. A store both rootfs slots share holds the set, not laid, until the new base is committed (step 6).

A consumer whose layout cannot take a parameter set refuses the ECU's set, an empty one included, without changing anything: a release that names such an ECU fails there, so such an ECU is given base images only.

## Security Considerations

A set decides which directories of the running base it replaces and which executable runs once they are replaced, the base's or one it carries; the base does not limit them beyond the rules above.
A consumer applies the set as root, lays its files with their execute bits, lays the set again on every boot of the base it was applied on, and does not go through a standby slot that a failed boot would fall back from.
The signer of a parameter image is therefore trusted as much as the signer of a base image: a parameter image is signed under the same trust anchors, and with the same controls, as the base images of the ECUs it is for.
A stored set is not verified again at boot: what keeps it the set that was verified is that only root can write the store (step 3). The image ID check of step 6 keeps a set on the base it was applied on; it is not a trust boundary.

A set is bound to an ECU by `ecu_id` and `ota_release_key` only, not to a vehicle: the release that delivers it decides which vehicles get it.

## Compatibility

A consumer whose ota-image-libs does not know parameter sets refuses a parameter image without changing anything:
from 0.6.0 on, an index entry with an unknown `artifactType` fails the parse of the whole index; before 0.6.0, the entry is taken for a file-based payload and its manifest, which has no file table, fails to parse.
From 0.8.0 on, an `apply` may be inside the set's slots, a slot directory need not be in the base, and nothing runs when a slot is taken away.
A consumer of 0.7.0 refuses, without changing anything, a set that needs either: a config whose `apply` is inside a slot fails its parse there, and a slot the base has no directory for fails its `check_slots_in_tree`.
A 0.7.0 consumer runs the `apply` of a slot taken away (the base's, then the only kind) again; one of 0.8.0 runs nothing.
From 0.9.0 on, `check_slots` also refuses a slot over `/etc/ota`, `/opt/data/ota` or `/usr/lib/ota`, an `apply` in a reserved path, and an `apply` that is a directory a slot is in, at build time and when the config is parsed; `check_slots_in_tree` follows a reserved path's symbolic links.
A consumer of 0.8.0 takes such a slot or `apply` unless it reserves the path itself, and refuses an `apply` that is a directory only against the base or the set (not an executable file).
