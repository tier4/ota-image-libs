# index.jwt Specification

## index.jwt Algorithm

`ES256` is used as the signing algorithm for the `index.jwt` file.
OTA image builder will only use `ES256` for signing the `index.jwt`, thus only supports `ECDSA` type of keys.

Client application MUST only accept an OTA image which its `index.jwt` is signed with `ES256` algorithm.

Other algorithms MIGHT be supported in the future, but for OTA Image version 1, `ES256` is the only supported algorithm.

## index.jwt Claims Schema

- **`iat`** *int*

    OPTIONAL. This field indicates when the JWT is created. It MUST be a integer of UNIX timestamp in seconds.
    OTA Image builder will set this field when signing the image.

- **`image_index`** *index.json OCI Descriptor*

    REQUIRED. This field indicates the index.json of the image being signed.

## index.jwt headers Schema

The following headers MUST be present in the `index.jwt`:

- **`x5c`** *array of strings*

    REQUIRED. This field contains the X.509 certificate chain used to sign the JWT.
    This array MUST contain at least one certificate, which is the signing certificate. Optionally but recommended, intermediate CA certs can also be added to the array to form a complete certificate chain.

- **`alg`** *string*

    REQUIRED. This field indicates the signing algorithm used for the index.jwt.
    For OTA Image version 1, It MUST be `ES256`.

- **`typ`** *string*

    REQUIRED. This field indicates the type of the JWT. It MUST be `JWT`.

For OTA image builder, the headers of `index.jwt` will be properly created.
Client application MUST verify the above headers are present, and reject any `index.jwt` that doesn't set these headers properly.
