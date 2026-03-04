# index.jwt Specification

`index.jwt` is a JSON Web Token (JWT/JWS) that wraps and signs the [image index](image_index.md) (`index.json`).
It provides integrity and authenticity verification for the OTA image — OTAClient MUST verify the signature to ensure the image index has not been tampered with and was signed by a trusted party.

Schema as code: [`index_jwt/schema.py`](../src/ota_image_libs/v1/index_jwt/schema.py)

## index.jwt Algorithm

`ES256` is used as the signing algorithm for the `index.jwt` file.
OTA image builder will only use `ES256` for signing the `index.jwt`, thus only supports `ECDSA` type of keys.

Client application MUST only accept an OTA image whose `index.jwt` is signed with the `ES256` algorithm.

Other algorithms MIGHT be supported in the future, but for OTA Image version 1, `ES256` is the only supported algorithm.

## index.jwt Claims Schema

- **`iat`** *int*

    OPTIONAL. This field indicates when the JWT is created. It MUST be an integer of UNIX timestamp in seconds.
    OTA image builder will always set this field when signing the image.

- **`image_index`** *[OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md)*

    REQUIRED. This field is an OCI descriptor that points to the `index.json` of the OTA image being signed.

## index.jwt headers Schema

The following headers MUST be present in the `index.jwt`:

- **`x5c`** *array of strings*

    REQUIRED. This field contains the X.509 certificate chain used to sign the JWT.
    This array MUST contain at least one certificate, which is the signing certificate. Optionally but recommended, intermediate CA certs can also be added to the array to form a complete certificate chain.

- **`alg`** *string*

    REQUIRED. This field indicates the signing algorithm used for the index.jwt.
    For OTA Image version 1, it MUST be `ES256`.

- **`typ`** *string*

    REQUIRED. This field indicates the type of the JWT. It MUST be `JWT`.

For OTA image builder, the headers of `index.jwt` will be properly created.
Client application MUST verify the above headers are present, and reject any `index.jwt` that doesn't set these headers properly.
