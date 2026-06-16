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

from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurve
from jwt.utils import der_to_raw_signature

JWT_ALG_AWS_ALG_MAPPING = {
    # JWT alg: AWS sign algorithm
    "ES256": "ECDSA_SHA_256",
    "ES384": "ECDSA_SHA_384",
    "ES512": "ECDSA_SHA_512",
}
"""Mapping between JWT ES* series algorithm to AWS KMS signing algorithm set.

Also see https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html#API_Sign_RequestSyntax
and https://datatracker.ietf.org/doc/html/rfc7518#section-3.4.
"""

AWS_ALG_JWT_ALG_MAPPING = {v: k for k, v in JWT_ALG_AWS_ALG_MAPPING.items()}


def ec_sign_der_to_raw_signature(der_sig: bytes, ec_curve: EllipticCurve):
    """Util to convert a DER-format ECDSA sign to JWT signature format.

    JWT expects the signature to be in "raw" format, see https://datatracker.ietf.org/doc/html/rfc7518#section-3.4.
    ECDSA signing request response from AWS KMS sign is in DER format, so this convert is required.
    See https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html#API_Sign_ResponseSyntax.
    """
    return der_to_raw_signature(der_sig, ec_curve)


def get_aws_sign_alg(jwt_sign_alg: str) -> str:
    try:
        return JWT_ALG_AWS_ALG_MAPPING[jwt_sign_alg]
    except KeyError:
        raise ValueError(f"unsupported {jwt_sign_alg=}") from None


def compose_jwt(
    payload: dict[str, Any],
    headers: dict[str, Any] | None = None,
    *,
    priv_key: bytes,
    alg: str,
) -> str:
    return jwt.encode(
        payload=payload,
        headers=headers,
        key=priv_key,
        algorithm=alg,
    )


def get_verified_jwt_payload(
    token: str,
    *,
    pub_key: bytes,
    allowed_algs: list[str],
) -> dict[str, str]:
    """Parse the input JWT, verify its signature and then return its payload."""
    return jwt.decode(
        token,
        key=pub_key,
        algorithms=allowed_algs,
        options={"verify_signature": True},
    )


def get_unverified_jwt_headers(
    token: str,
) -> dict[str, Any]:
    """Parse the input JWT and return its headers.

    This is for caller get the x5c header, perform the sign cert verification,
        and then use verified sign cert's pubkey to verify the JWS signature.
    """
    return jwt.get_unverified_header(token)
