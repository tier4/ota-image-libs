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

import base64
import json

import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurve,
    EllipticCurvePrivateKey,
)
from cryptography.hazmat.primitives.hashes import HashAlgorithm
from jwt.exceptions import InvalidSignatureError

from ota_image_libs._crypto.aws_kms import (
    AWS_ALG_JWT_ALG_MAPPING,
    JWT_ALG_AWS_ALG_MAPPING,
    AWSKMSignAlgorithm,
    compose_jwt_from_aws_kms_sign_response,
    compose_unsigned_jwt_for_aws_kms_sign,
    get_aws_sign_alg,
)
from ota_image_libs._crypto.jwt_utils import JWTAlgorithm, get_verified_jwt_payload

# (jwt_alg, aws_alg, curve, hash, raw r||s signature length in bytes)
# raw length is 2 * ceil(key_size / 8): P-256 -> 64, P-384 -> 96, P-521 -> 132.
ES_CURVE_CASES = [
    ("ES256", "ECDSA_SHA_256", ec.SECP256R1, hashes.SHA256, 64),
    ("ES384", "ECDSA_SHA_384", ec.SECP384R1, hashes.SHA384, 96),
    ("ES512", "ECDSA_SHA_512", ec.SECP521R1, hashes.SHA512, 132),
]


def _b64url_decode(segment: bytes) -> bytes:
    """base64url-decode a JWS segment, restoring the stripped padding."""
    pad = b"=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


# A representative KMS key ARN; only its shape matters for these tests.
_FAKE_KEY_ID = (
    "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab"
)


def _ecdsa_der_sign(
    priv_key: EllipticCurvePrivateKey, message: bytes, digest: HashAlgorithm
) -> bytes:
    """Produce a DER-encoded ECDSA signature over ``message``.

    AWS KMS `Sign` with `MessageType=RAW` hashes the message with the signing
    algorithm's digest and returns the signature DER-encoded (ANSI X9.62-2005 /
    RFC 3279 section 2.2.3); cryptography's ``sign(msg, ECDSA(hash))`` does the
    same, so it stands in for the KMS crypto here.
    """
    return priv_key.sign(message, ec.ECDSA(digest))


def _simulate_kms_sign_response(
    priv_key: EllipticCurvePrivateKey,
    message: bytes,
    *,
    digest: HashAlgorithm,
    signing_algorithm: str,
    key_id: str = _FAKE_KEY_ID,
) -> dict[str, str]:
    """Build a self-generated AWS KMS `Sign` response (no live AWS needed).

    Mirrors the documented response syntax::

        {"KeyId": str, "Signature": blob, "SigningAlgorithm": str}

    On the JSON/HTTP wire the `Signature` blob is standard-base64 encoded (boto3
    hands it back already decoded to ``bytes``); we model the wire form here so
    the test exercises the same decode a real caller must perform.

    See https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html#API_Sign_ResponseSyntax
    """
    der_sig = _ecdsa_der_sign(priv_key, message, digest)
    return {
        "KeyId": key_id,
        "Signature": base64.b64encode(der_sig).decode("ascii"),
        "SigningAlgorithm": signing_algorithm,
    }


#
# ------------ Unit tests ------------ #
#
class TestGetAwsSignAlg:
    @pytest.mark.parametrize(
        "jwt_alg, expected_aws_alg",
        [(jwt_alg, aws_alg) for jwt_alg, aws_alg, *_ in ES_CURVE_CASES],
    )
    def test_maps_each_es_alg(self, jwt_alg: str, expected_aws_alg: str):
        result = get_aws_sign_alg(jwt_alg)
        assert isinstance(result, AWSKMSignAlgorithm)
        assert str(result) == expected_aws_alg

    @pytest.mark.parametrize("bad_alg", ["RS256", "HS256", "ES128", "", "garbage"])
    def test_rejects_unsupported_alg(self, bad_alg: str):
        with pytest.raises(ValueError):
            get_aws_sign_alg(bad_alg)


class TestAlgorithmMappings:
    def test_jwt_aws_mapping_covers_all_jwt_algorithms(self):
        """Every JWTAlgorithm member must have a KMS counterpart."""
        assert set(JWT_ALG_AWS_ALG_MAPPING) == set(JWTAlgorithm)

    def test_aws_mapping_is_inverse_of_jwt_mapping(self):
        assert AWS_ALG_JWT_ALG_MAPPING == {
            v: k for k, v in JWT_ALG_AWS_ALG_MAPPING.items()
        }
        # round-trips both ways
        for jwt_alg, aws_alg in JWT_ALG_AWS_ALG_MAPPING.items():
            assert AWS_ALG_JWT_ALG_MAPPING[aws_alg] == jwt_alg


class TestComposeUnsignedJwtForAwsKmsSign:
    @pytest.mark.parametrize(
        "jwt_alg, expected_aws_alg",
        [(jwt_alg, aws_alg) for jwt_alg, aws_alg, *_ in ES_CURVE_CASES],
    )
    def test_returns_aws_alg_and_two_segment_input(
        self, jwt_alg: str, expected_aws_alg: str
    ):
        aws_alg, signing_input = compose_unsigned_jwt_for_aws_kms_sign(
            {"sub": "img"}, {"typ": "JWT"}, alg=jwt_alg
        )
        assert isinstance(aws_alg, AWSKMSignAlgorithm)
        assert str(aws_alg) == expected_aws_alg
        # only header + payload, no signature segment yet
        assert isinstance(signing_input, str)
        assert signing_input.count(".") == 1

    def test_header_carries_alg_and_typ_and_merges_custom_headers(self):
        _, signing_input = compose_unsigned_jwt_for_aws_kms_sign(
            {"sub": "img"}, {"kid": "key-1"}, alg="ES256"
        )
        header_seg = signing_input.split(".", 1)[0]
        header = json.loads(_b64url_decode(header_seg.encode()))
        assert header["alg"] == "ES256"
        assert header["typ"] == "JWT"
        assert header["kid"] == "key-1"

    def test_payload_round_trips(self):
        payload = {"sub": "img", "iat": 123, "nested": {"a": 1}}
        _, signing_input = compose_unsigned_jwt_for_aws_kms_sign(payload, alg="ES256")
        payload_seg = signing_input.split(".")[1]
        assert json.loads(_b64url_decode(payload_seg.encode())) == payload

    def test_works_without_extra_headers(self):
        aws_alg, signing_input = compose_unsigned_jwt_for_aws_kms_sign(
            {"sub": "img"}, alg="ES256"
        )
        assert str(aws_alg) == "ECDSA_SHA_256"
        assert signing_input.count(".") == 1

    @pytest.mark.parametrize("bad_alg", ["RS256", "HS256", "nonsense"])
    def test_rejects_unsupported_alg(self, bad_alg: str):
        with pytest.raises(ValueError):
            compose_unsigned_jwt_for_aws_kms_sign({"sub": "img"}, alg=bad_alg)


class TestComposeJwtFromAwsKmsSignResponse:
    @pytest.mark.parametrize("jwt_alg, aws_alg, curve, digest, raw_len", ES_CURVE_CASES)
    def test_signature_segment_is_base64url_encoded_raw_signature(
        self,
        jwt_alg: str,
        aws_alg: str,
        curve: type[EllipticCurve],
        digest: type[HashAlgorithm],
        raw_len: int,
    ):
        """The third segment must be base64url(raw r||s), not raw DER bytes."""
        priv = ec.generate_private_key(curve())
        der_sig = _ecdsa_der_sign(priv, b"header.payload", digest())

        token = compose_jwt_from_aws_kms_sign_response(
            b"header.payload", kms_sign_resp=der_sig, kms_sign_algorithm=aws_alg
        )

        assert isinstance(token, bytes)
        assert token.count(b".") == 2
        sig_seg = token.rsplit(b".", 1)[1]
        # must be valid (padding-less) base64url, i.e. no raw binary leaked through
        assert sig_seg == base64.urlsafe_b64encode(_b64url_decode(sig_seg)).rstrip(b"=")
        # decoded signature is the fixed-length raw r||s form JWS expects
        assert len(_b64url_decode(sig_seg)) == raw_len

    @pytest.mark.parametrize("bad_alg", ["ECDSA_SHA_128", "RS256", "", "garbage"])
    def test_rejects_unsupported_kms_algorithm(self, bad_alg: str):
        with pytest.raises(ValueError):
            compose_jwt_from_aws_kms_sign_response(
                b"header.payload", kms_sign_resp=b"\x00", kms_sign_algorithm=bad_alg
            )


#
# ------------ Integration tests ------------ #
#
class TestAwsKmsSigningRoundTrip:
    @pytest.mark.parametrize("jwt_alg, aws_alg, curve, digest, raw_len", ES_CURVE_CASES)
    def test_full_sign_and_verify_round_trip(
        self,
        jwt_alg: str,
        aws_alg: str,
        curve: type[EllipticCurve],
        digest: type[HashAlgorithm],
        raw_len: int,
    ):
        """Compose unsigned -> KMS sign (simulated) -> compose final -> verify."""
        priv = ec.generate_private_key(curve())
        pub_pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        payload = {"sub": "img", "iat": 123}

        # 1. compose the unsigned signing input
        composed_aws_alg, signing_input = compose_unsigned_jwt_for_aws_kms_sign(
            payload, {"typ": "JWT"}, alg=jwt_alg
        )
        assert str(composed_aws_alg) == aws_alg

        # 2. AWS KMS Sign: self-generate a response shaped like the real API
        kms_resp = _simulate_kms_sign_response(
            priv,
            signing_input.encode(),
            digest=digest(),
            signing_algorithm=str(composed_aws_alg),
        )
        assert set(kms_resp) == {"KeyId", "Signature", "SigningAlgorithm"}

        # 3. extract the DER signature from the response as a real caller would
        #    (boto3 returns bytes; from the raw JSON wire it is base64-encoded)
        #    and compose the complete JWT
        der_sig = base64.b64decode(kms_resp["Signature"])
        token = compose_jwt_from_aws_kms_sign_response(
            signing_input.encode(),
            kms_sign_resp=der_sig,
            kms_sign_algorithm=kms_resp["SigningAlgorithm"],
        )

        # 4a. verifiable by a plain pyJWT consumer
        assert jwt.decode(token, key=pub_pem, algorithms=[jwt_alg]) == payload
        # 4b. verifiable through the library's own verification helper
        assert (
            get_verified_jwt_payload(
                token.decode(), pub_key=pub_pem, allowed_algs=[jwt_alg]
            )
            == payload
        )

    def test_tampered_payload_fails_verification(self):
        priv = ec.generate_private_key(ec.SECP256R1())
        pub_pem = priv.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        _, signing_input = compose_unsigned_jwt_for_aws_kms_sign(
            {"sub": "img"}, {"typ": "JWT"}, alg="ES256"
        )
        kms_resp = _simulate_kms_sign_response(
            priv,
            signing_input.encode(),
            digest=hashes.SHA256(),
            signing_algorithm="ECDSA_SHA_256",
        )
        token = compose_jwt_from_aws_kms_sign_response(
            signing_input.encode(),
            kms_sign_resp=base64.b64decode(kms_resp["Signature"]),
            kms_sign_algorithm=kms_resp["SigningAlgorithm"],
        )

        # flip the payload segment to a different (validly-encoded) value
        header_seg, _, sig_seg = token.split(b".")
        forged_payload = base64.urlsafe_b64encode(b'{"sub": "evil"}').rstrip(b"=")
        forged = header_seg + b"." + forged_payload + b"." + sig_seg

        with pytest.raises(InvalidSignatureError):
            jwt.decode(forged, key=pub_pem, algorithms=["ES256"])

    def test_wrong_key_fails_verification(self):
        priv = ec.generate_private_key(ec.SECP256R1())
        other_pub_pem = (
            ec.generate_private_key(ec.SECP256R1())
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

        _, signing_input = compose_unsigned_jwt_for_aws_kms_sign(
            {"sub": "img"}, {"typ": "JWT"}, alg="ES256"
        )
        kms_resp = _simulate_kms_sign_response(
            priv,
            signing_input.encode(),
            digest=hashes.SHA256(),
            signing_algorithm="ECDSA_SHA_256",
        )
        token = compose_jwt_from_aws_kms_sign_response(
            signing_input.encode(),
            kms_sign_resp=base64.b64decode(kms_resp["Signature"]),
            kms_sign_algorithm=kms_resp["SigningAlgorithm"],
        )

        with pytest.raises(InvalidSignatureError):
            jwt.decode(token, key=other_pub_pem, algorithms=["ES256"])


class TestAwsKmsSigningWithIndexJwtReadPath:
    """A KMS-signed token must be consumable by the existing index_jwt path."""

    def test_kms_signed_index_jwt_verifies_via_index_jwt_utils(
        self, cert_chain, end_entity_cert, image_descriptor
    ):
        from ota_image_libs.v1.index_jwt.schema import IndexJWTClaims
        from ota_image_libs.v1.index_jwt.utils import (
            X5C_FNAME,
            decode_index_jwt_with_verification,
            get_index_jwt_sign_cert_chain,
        )

        _, ee_key = end_entity_cert  # conftest end-entity key is P-256 (ES256)

        # Build the same payload/header that compose_index_jwt would, but sign
        # it via the AWS KMS path instead of with a local private key.
        claims = IndexJWTClaims(iat=123, image_index=image_descriptor)
        headers = {X5C_FNAME: cert_chain.serializer()}

        _, signing_input = compose_unsigned_jwt_for_aws_kms_sign(
            claims.model_dump(by_alias=True, exclude_none=True),
            headers,
            alg="ES256",
        )
        kms_resp = _simulate_kms_sign_response(
            ee_key,
            signing_input.encode(),
            digest=hashes.SHA256(),
            signing_algorithm="ECDSA_SHA_256",
        )
        token = compose_jwt_from_aws_kms_sign_response(
            signing_input.encode(),
            kms_sign_resp=base64.b64decode(kms_resp["Signature"]),
            kms_sign_algorithm=kms_resp["SigningAlgorithm"],
        ).decode()

        # the existing read path extracts the x5c chain and verifies the signature
        extracted_chain = get_index_jwt_sign_cert_chain(token)
        assert extracted_chain.ee.subject == cert_chain.ee.subject

        verified = decode_index_jwt_with_verification(token, extracted_chain)
        assert verified.image_index.digest == image_descriptor.digest
        assert verified.image_index.size == image_descriptor.size
