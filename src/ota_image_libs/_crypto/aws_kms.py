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
"""Support for using AWS KMS to sign the OTA image JWT.

Only support algorithm that supports by the `jwt_utils` module, which is ES* series.
"""

from __future__ import annotations

from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.utils import base64url_encode

from .jwt_utils import (
    JWT_ALG_CURVE_MAPPING,
    JWTAlgorithm,
    _StrEnum,
    ec_sign_der_to_raw_signature,
)


class AWSKMSignAlgorithm(_StrEnum):
    ECDSA_SHA_256 = "ECDSA_SHA_256"
    ECDSA_SHA_384 = "ECDSA_SHA_384"
    ECDSA_SHA_512 = "ECDSA_SHA_512"


JWT_ALG_AWS_ALG_MAPPING = {
    JWTAlgorithm.ES256: AWSKMSignAlgorithm.ECDSA_SHA_256,
    JWTAlgorithm.ES384: AWSKMSignAlgorithm.ECDSA_SHA_384,
    JWTAlgorithm.ES512: AWSKMSignAlgorithm.ECDSA_SHA_512,
}
"""Mapping between JWT ES* series algorithm to AWS KMS signing algorithm set.

Also see https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html#API_Sign_RequestSyntax
and https://datatracker.ietf.org/doc/html/rfc7518#section-3.4.
"""

AWS_ALG_JWT_ALG_MAPPING = {v: k for k, v in JWT_ALG_AWS_ALG_MAPPING.items()}


def get_aws_sign_alg(jwt_sign_alg: str) -> AWSKMSignAlgorithm:
    try:
        return JWT_ALG_AWS_ALG_MAPPING[JWTAlgorithm(jwt_sign_alg)]
    except ValueError:
        raise ValueError(f"unsupported or unknown {jwt_sign_alg=}") from None
    except KeyError:
        raise ValueError(f"unsupported or unknown {jwt_sign_alg=}") from None


def compose_unsigned_jwt_for_aws_kms_sign(
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    *,
    alg: str,
) -> tuple[AWSKMSignAlgorithm, str]:
    """Compose a JWT with only header and payload parts,
    ready for signing with AWS KMS sign API.

    To simplify the implementation and avoid rebuild the wheel,
    we use pyJWT's infra to create an JWT and then strip away the signature
    to get the raw headers+payload.

    NOTE: the returned signing input is meant to be passed to KMS `Sign` as the
        `Message`. With `MessageType=RAW`, KMS caps `Message` at 4096 bytes; an
        embedded `x5c` cert chain can push the input past that for long chains.
        If so, the caller should hash the signing input with the algorithm's
        digest (SHA-256/384/512) and call `Sign` with `MessageType=DIGEST`.
        See https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html#API_Sign_RequestSyntax.

    Raises:
        ValueError
    """
    _aws_alg = get_aws_sign_alg(alg)
    _raw_payload = jwt.encode(
        payload=payload,
        headers=headers,
        key=ec.generate_private_key(JWT_ALG_CURVE_MAPPING[JWTAlgorithm(alg)]()),
        algorithm=alg,
    ).rsplit(".", 1)[0]
    return (_aws_alg, _raw_payload)


def compose_jwt_from_aws_kms_sign_response(
    _jwt_payload: bytes, *, kms_sign_resp: bytes, kms_sign_algorithm: str
) -> str:
    """Compose the complete JWT from JWT payload and AWS KMS signing resp.

    Caller needs to encode the payload and signature beforehand.
    For the signature part, the caller needs to extract the signature from the
      full AWS KMS signing response JSON object, and then do BASE64_URL decode to
      get the raw DER format signature.

    NOTE: we don't do verification over the resp and payload to
          check whether the signing response is actually for the
          jwt_payload, we have no way to know that anyway(we don't
          know the private key).
    """
    try:
        _kms_sign_alg = AWSKMSignAlgorithm(kms_sign_algorithm)
    except ValueError:
        raise ValueError(f"unsupported or invalid {kms_sign_algorithm=}") from None

    try:
        _curve = JWT_ALG_CURVE_MAPPING[AWS_ALG_JWT_ALG_MAPPING[_kms_sign_alg]]
    except KeyError as e:
        raise ValueError(f"unsupported or invalid algorithm: {e!r}") from None

    _raw_sig = ec_sign_der_to_raw_signature(kms_sign_resp, _curve())
    return (_jwt_payload + b"." + base64url_encode(_raw_sig)).decode("ascii")
