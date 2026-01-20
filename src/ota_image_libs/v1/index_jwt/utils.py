# Copyright 2025 TIER IV, INC. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import time

from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
)

from ota_image_libs._crypto.jwt_utils import (
    compose_jwt,
    get_unverified_jwt_headers,
    get_verified_jwt_payload,
)
from ota_image_libs._crypto.x509_utils import X5cX509CertChain
from ota_image_libs.v1.consts import ALLOWED_JWT_ALG

from .schema import ImageIndex, IndexJWTClaims

X5C_FNAME = "x5c"


def compose_index_jwt(
    index_descriptor: ImageIndex.Descriptor,
    *,
    sign_cert_chain: X5cX509CertChain,
    sign_key: bytes,
    sign_key_passwd: bytes | None = None,
) -> str:
    """
    Compose JWS for index.json with signing certificate chain and signing key.

    The algorithm used for signing is ES256 (EdDSA with SHA-256).
    The signing certificate chain is included in the JWT header as `x5c` field.

    Args:
        index_json_digest (bytes): The digest of the index.json.
        index_json_size (int): The size of the index.json.
        sign_cert_chain (X5cX509CertChain): The certificate chain used for signing.
        sign_key (bytes): The private key used for signing.

    Returns:
        str: The composed index.jwt string.
    """
    claims = IndexJWTClaims(
        iat=int(time.time()),
        image_index=index_descriptor,
    )
    claims_dict = claims.model_dump(by_alias=True, exclude_none=True)

    extra_headers = {X5C_FNAME: sign_cert_chain.serializer()}

    try:
        _loaded_priv_key = load_pem_private_key(sign_key, sign_key_passwd)
        assert isinstance(_loaded_priv_key, EllipticCurvePrivateKey)
    except Exception as e:
        raise ValueError("Not an ECDSA private key") from e

    return compose_jwt(
        payload=claims_dict,
        headers=extra_headers,
        priv_key=_loaded_priv_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        ),
        alg=ALLOWED_JWT_ALG,
    )


def get_index_jwt_sign_cert_chain(_input: str) -> X5cX509CertChain:
    """
    Extract the signing certificate chain from index.jwt.

    Caller should use this function to retrieve the certificate chain,
    first verify the signing certificate chain before using the signing
    certificate to verify the signature of the index.jwt.

    Args:
        _input (str): The index.jwt string to decode.

    Raises:
        ValueError: If the x5c header is missing or not invalid.

    Returns:
        X509CertChain: The extracted signing certificate chain.
    """
    headers = get_unverified_jwt_headers(_input)
    x5c = headers.get(X5C_FNAME)
    if not x5c:
        raise ValueError(f"Missing {X5C_FNAME} header in JWT")

    if not isinstance(x5c, list):
        raise ValueError(
            f"{X5C_FNAME} header MUST be a list of PEM-encoded certificates"
        )

    return X5cX509CertChain.validator(x5c)


def decode_index_jwt_with_verification(
    _input: str, sign_cert: X5cX509CertChain
) -> IndexJWTClaims:
    """Decode index.jwt and verify the signature.

    NOTE that this function doesn't check whether the pubkey itself is trustworthness or not,
        the caller should validate the cert chain before using this function.

    Args:
        _input (str): The index.jwt string to decode.

    Raises:
        ValueError: If the end-entity certificate is invalid.
        Other exceptions raised from JWT verification/parsing routine.

    Returns:
        IndexJWTClaims: The decoded claims.
    """
    try:
        ee = sign_cert.ee
        assert ee is not None, "End-entity certificate must be set in the chain"
        pubkey = ee.public_key()
        assert isinstance(pubkey, EllipticCurvePublicKey), "Must be an ECDSA cert"
    except AssertionError as e:
        raise ValueError(
            f"Invalid end-entity certificate in the signing certificate chain: {e}"
        ) from e

    raw_claims = get_verified_jwt_payload(
        _input,
        pub_key=pubkey.public_bytes(
            encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo
        ),
        allowed_algs=[ALLOWED_JWT_ALG],
    )
    return IndexJWTClaims.model_validate(raw_claims)
