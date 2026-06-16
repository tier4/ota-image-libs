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
"""Tests for index_jwt utils module."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
)
from cryptography.x509 import Certificate
from cryptography.x509.oid import NameOID
from jwt.exceptions import InvalidSignatureError

from ota_image_libs._crypto.aws_kms import (
    AWSKMSSignAlgorithm,
    compose_jwt_from_aws_kms_sign_response,
    get_aws_sign_alg,
)
from ota_image_libs._crypto.x509_utils import X5cX509CertChain
from ota_image_libs.common.oci_spec import Sha256Digest
from ota_image_libs.v1.consts import ALLOWED_JWT_ALG
from ota_image_libs.v1.image_index.schema import ImageIndex
from ota_image_libs.v1.index_jwt.schema import IndexJWTClaims
from ota_image_libs.v1.index_jwt.utils import (
    X5C_FNAME,
    compose_index_jwt,
    compose_unsigned_index_jwt_for_aws_kms_sign,
    decode_index_jwt_with_verification,
    get_index_jwt_sign_cert_chain,
)


def _b64url_decode(segment: str) -> bytes:
    """base64url-decode a JWS segment, restoring the stripped padding."""
    raw = segment.encode("ascii")
    raw += b"=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw)


def _simulate_kms_es256_sign(
    priv_key: EllipticCurvePrivateKey, signing_input: str
) -> str:
    """Stand in for an AWS KMS ``ECDSA_SHA_256`` ``Sign`` round-trip.

    KMS signs the ``header.payload`` input and returns a DER-encoded ECDSA
    signature; ``priv_key.sign(..., ec.ECDSA(SHA256))`` produces the same DER
    form, which we feed back through the library's response composer (along with
    the original signing input str) to get the complete JWT a caller would
    obtain after calling KMS.
    """
    der_sig = priv_key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    return compose_jwt_from_aws_kms_sign_response(
        signing_input,
        kms_sign_resp=der_sig,
        kms_sign_algorithm="ECDSA_SHA_256",
    )


class TestIndexJWTUtils:
    def test_get_index_jwt_sign_cert_chain_missing_x5c(self):
        """Test extracting cert chain from JWT without x5c header."""
        # A simple JWT without x5c header (header.payload.signature format)
        # Header: {"alg": "ES256", "typ": "JWT"}
        # This is just for testing error handling
        fake_jwt = (
            "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0ZXN0IjoidGVzdCJ9.fake_signature"
        )

        with pytest.raises(ValueError):
            get_index_jwt_sign_cert_chain(fake_jwt)

    def test_get_index_jwt_sign_cert_chain_invalid_x5c_format(self):
        """Test extracting cert chain with invalid x5c format (not a list)."""
        # JWT with x5c as string instead of list
        # Header: {"alg": "ES256", "typ": "JWT", "x5c": "invalid"}
        header = {"alg": "ES256", "typ": "JWT", "x5c": "not_a_list"}
        header_b64 = (
            base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
        )
        payload_b64 = base64.urlsafe_b64encode(b'{"test": "test"}').decode().rstrip("=")
        fake_jwt = f"{header_b64}.{payload_b64}.fake_signature"

        with pytest.raises(ValueError):
            get_index_jwt_sign_cert_chain(fake_jwt)

    def test_get_index_jwt_sign_cert_chain_with_valid_chain(
        self, end_entity_cert, intermediate_ca_cert, image_descriptor
    ):
        """Test extracting valid cert chain from JWT."""
        ee_cert, ee_key = end_entity_cert
        intermediate_cert, _ = intermediate_ca_cert

        # Create a cert chain
        chain = X5cX509CertChain.validator([ee_cert, intermediate_cert])

        # Create a JWT with this cert chain
        ee_key_pem = ee_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        jwt_token = compose_index_jwt(
            image_descriptor,
            sign_cert_chain=chain,
            sign_key=ee_key_pem,
        )

        # Extract the cert chain
        extracted_chain = get_index_jwt_sign_cert_chain(jwt_token)

        assert extracted_chain.ee.subject == ee_cert.subject
        assert len(extracted_chain.interms) == 1
        assert extracted_chain.interms[0].subject == intermediate_cert.subject

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_backward_compatibility_pem_certs_in_x5c_header(
        self,
        end_entity_cert: tuple[Certificate, EllipticCurvePrivateKey],
        intermediate_ca_cert: tuple[Certificate, EllipticCurvePrivateKey],
        image_descriptor: ImageIndex.Descriptor,
    ):
        """Test backward compatibility: x5c header with PEM certs instead of base64 DER.

        Although RFC 7515 specifies x5c should contain base64-encoded DER,
        we maintain backward compatibility by also accepting PEM format.
        """
        ee_cert, ee_key = end_entity_cert
        intermediate_cert, _ = intermediate_ca_cert

        # Create JWT manually with PEM certs in x5c (backward compatibility)
        ee_pem = ee_cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
        intermediate_pem = intermediate_cert.public_bytes(
            serialization.Encoding.PEM
        ).decode("utf-8")

        # Create claims
        from ota_image_libs.v1.index_jwt.schema import IndexJWTClaims

        claims = IndexJWTClaims(
            iat=int(datetime.now(timezone.utc).timestamp()),
            image_index=image_descriptor,
        )

        # Manually compose JWT with PEM certs
        from ota_image_libs._crypto.jwt_utils import compose_jwt

        ee_key_pem = ee_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        # Use PEM certs instead of base64 DER (backward compatibility)
        headers = {"x5c": [ee_pem, intermediate_pem]}

        jwt_token = compose_jwt(
            payload=claims.model_dump(by_alias=True, exclude_none=True),
            headers=headers,
            priv_key=ee_key_pem,
            alg="ES256",
        )

        # This should work despite using PEM instead of base64 DER
        extracted_chain = get_index_jwt_sign_cert_chain(jwt_token)

        assert extracted_chain.ee.subject == ee_cert.subject
        assert len(extracted_chain.interms) == 1
        assert extracted_chain.interms[0].subject == intermediate_cert.subject


class TestComposeIndexJwt:
    def test_compose_index_jwt_with_invalid_key(self, mocker):
        """Test compose_index_jwt with an invalid private key."""
        # Create a mock descriptor
        descriptor = ImageIndex.Descriptor(
            digest=Sha256Digest("0" * 64),
            size=1234,
        )

        # Create a mock cert chain
        mock_cert_chain = mocker.MagicMock()
        mock_cert_chain.serializer.return_value = ["cert1", "cert2"]

        # Invalid key (not ECDSA)
        invalid_key = b"invalid_key_data"

        with pytest.raises(ValueError):
            compose_index_jwt(
                descriptor,
                sign_cert_chain=mock_cert_chain,
                sign_key=invalid_key,
            )

    def test_compose_index_jwt_with_valid_ecdsa_key(self, mocker):
        """Test compose_index_jwt with a valid ECDSA key."""
        # Generate a real ECDSA key
        private_key = ec.generate_private_key(ec.SECP256R1())
        private_key_pem = private_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        # Create a mock descriptor
        descriptor = ImageIndex.Descriptor(
            digest=Sha256Digest("1" * 64),
            size=1234,
        )

        # Create a mock cert chain
        mock_cert_chain = mocker.MagicMock()
        mock_cert_chain.serializer.return_value = ["cert1", "cert2"]

        # This should not raise an error and should return a JWT string
        jwt = compose_index_jwt(
            descriptor,
            sign_cert_chain=mock_cert_chain,
            sign_key=private_key_pem,
        )

        assert isinstance(jwt, str)
        assert jwt.count(".") == 2  # JWT has 3 parts separated by dots

    def test_compose_index_jwt_end_to_end(
        self, cert_chain, end_entity_cert, image_descriptor
    ):
        """Test compose_index_jwt end-to-end with real certificate chain."""
        _, ee_key = end_entity_cert

        ee_key_pem = ee_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        jwt_token = compose_index_jwt(
            image_descriptor,
            sign_cert_chain=cert_chain,
            sign_key=ee_key_pem,
        )

        # Verify it's a valid JWT structure
        assert isinstance(jwt_token, str)
        assert jwt_token.count(".") == 2

        # Verify we can extract the cert chain back
        extracted_chain = get_index_jwt_sign_cert_chain(jwt_token)
        assert extracted_chain.ee.subject == cert_chain.ee.subject

    def test_compose_index_jwt_with_password_protected_key(
        self, cert_chain, end_entity_cert, image_descriptor
    ):
        """Test compose_index_jwt with password-protected key."""
        _, ee_key = end_entity_cert

        password = b"test_password"
        from cryptography.hazmat.primitives.serialization import BestAvailableEncryption

        ee_key_pem = ee_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=BestAvailableEncryption(password),
        )

        jwt_token = compose_index_jwt(
            image_descriptor,
            sign_cert_chain=cert_chain,
            sign_key=ee_key_pem,
            sign_key_passwd=password,
        )

        assert isinstance(jwt_token, str)
        assert jwt_token.count(".") == 2


class TestDecodeIndexJwtWithVerification:
    def test_decode_index_jwt_with_invalid_cert_chain(self, mocker):
        """Test decode with cert chain that has no end-entity cert."""
        fake_jwt = "fake.jwt.token"

        # Create mock cert chain without end-entity cert
        mock_cert_chain = mocker.MagicMock()
        mock_cert_chain.ee = None

        with pytest.raises(ValueError):
            decode_index_jwt_with_verification(fake_jwt, mock_cert_chain)

    def test_decode_index_jwt_with_non_ecdsa_cert(self, mocker):
        """Test decode with non-ECDSA certificate."""
        fake_jwt = "fake.jwt.token"

        # Create mock cert chain with non-ECDSA cert
        mock_cert_chain = mocker.MagicMock()
        mock_ee = mocker.MagicMock()
        mock_cert_chain.ee = mock_ee

        # Mock public_key to return non-ECDSA key
        from cryptography.hazmat.primitives.asymmetric import rsa

        mock_pubkey = mocker.MagicMock(spec=rsa.RSAPublicKey)
        mock_ee.public_key.return_value = mock_pubkey

        with pytest.raises(ValueError):
            decode_index_jwt_with_verification(fake_jwt, mock_cert_chain)

    def test_decode_index_jwt_with_verification_e2e(
        self,
        cert_chain: X5cX509CertChain,
        end_entity_cert: tuple[Certificate, EllipticCurvePrivateKey],
        image_descriptor,
    ):
        """Test decode and verify JWT end-to-end."""
        _, ee_key = end_entity_cert

        ee_key_pem = ee_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        # Create JWT
        jwt_token = compose_index_jwt(
            image_descriptor,
            sign_cert_chain=cert_chain,
            sign_key=ee_key_pem,
        )

        # Extract and verify
        extracted_chain = get_index_jwt_sign_cert_chain(jwt_token)
        claims = decode_index_jwt_with_verification(jwt_token, extracted_chain)

        # Verify claims
        assert claims.image_index.digest == image_descriptor.digest
        assert claims.image_index.size == image_descriptor.size
        assert claims.iat is not None

    def test_decode_index_jwt_with_wrong_key(
        self, cert_chain, end_entity_cert, image_descriptor
    ):
        """Test decode fails when using wrong signing certificate."""
        _, ee_key = end_entity_cert

        ee_key_pem = ee_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        # Create JWT
        jwt_token = compose_index_jwt(
            image_descriptor,
            sign_cert_chain=cert_chain,
            sign_key=ee_key_pem,
        )

        # Create a different cert chain
        different_key = ec.generate_private_key(ec.SECP256R1())
        different_subject = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Different Cert")]
        )
        different_issuer = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "Different CA")]
        )
        different_cert = (
            x509.CertificateBuilder()
            .subject_name(different_subject)
            .issuer_name(different_issuer)
            .public_key(different_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(timezone.utc))
            .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
            .sign(different_key, hashes.SHA256())
        )

        wrong_chain = X5cX509CertChain()
        wrong_chain.add_ee(different_cert)

        # Verification should fail with invalid signature
        with pytest.raises(InvalidSignatureError):
            decode_index_jwt_with_verification(jwt_token, wrong_chain)

    @pytest.mark.filterwarnings("ignore::DeprecationWarning")
    def test_e2e_with_backward_compatible_pem(
        self, end_entity_cert, intermediate_ca_cert
    ):
        """Test full workflow: compose with PEM certs (backward compatibility) and verify.

        This tests the backward compatibility feature where x5c header can contain
        PEM certificates instead of base64-encoded DER as per RFC 7515.
        """
        ee_cert, ee_key = end_entity_cert
        intermediate_cert, _ = intermediate_ca_cert

        # Create JWT manually with PEM certs in x5c (backward compatibility)
        ee_pem = ee_cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")
        intermediate_pem = intermediate_cert.public_bytes(
            serialization.Encoding.PEM
        ).decode("utf-8")

        # Create claims
        from ota_image_libs.v1.index_jwt.schema import IndexJWTClaims

        descriptor = ImageIndex.Descriptor(
            digest=Sha256Digest("c" * 64),
            size=7777,
        )
        claims = IndexJWTClaims(
            iat=int(datetime.now(timezone.utc).timestamp()),
            image_index=descriptor,
        )

        # Manually compose JWT with PEM certs
        from ota_image_libs._crypto.jwt_utils import compose_jwt

        ee_key_pem = ee_key.private_bytes(
            encoding=Encoding.PEM,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=NoEncryption(),
        )

        # Use PEM certs instead of base64 DER (backward compatibility)
        headers = {"x5c": [ee_pem, intermediate_pem]}

        jwt_token = compose_jwt(
            payload=claims.model_dump(by_alias=True, exclude_none=True),
            headers=headers,
            priv_key=ee_key_pem,
            alg="ES256",
        )

        # Extract cert chain from JWT (should work with PEM)
        extracted_chain = get_index_jwt_sign_cert_chain(jwt_token)

        # Verify the JWT
        verified_claims = decode_index_jwt_with_verification(jwt_token, extracted_chain)

        # Verify claims are correct
        assert verified_claims.image_index.digest == descriptor.digest
        assert verified_claims.image_index.size == descriptor.size


class TestComposeUnsignedIndexJwtForAwsKmsSign:
    def test_returns_kms_alg_and_two_segment_signing_input(
        self, cert_chain: X5cX509CertChain, image_descriptor: ImageIndex.Descriptor
    ):
        """Returns the KMS algorithm plus the unsigned ``header.payload`` input."""
        aws_alg, signing_input = compose_unsigned_index_jwt_for_aws_kms_sign(
            image_descriptor, sign_cert_chain=cert_chain
        )

        assert isinstance(aws_alg, AWSKMSSignAlgorithm)
        # the index.jwt alg is fixed to ALLOWED_JWT_ALG (ES256 -> ECDSA_SHA_256)
        assert aws_alg == AWSKMSSignAlgorithm.ECDSA_SHA_256
        assert aws_alg == get_aws_sign_alg(ALLOWED_JWT_ALG)

        # signing input is the unsigned `header.payload`, no signature segment yet
        assert isinstance(signing_input, str)
        assert signing_input.count(".") == 1

    def test_header_carries_alg_typ_and_x5c_chain(
        self, cert_chain: X5cX509CertChain, image_descriptor: ImageIndex.Descriptor
    ):
        """The JWT header advertises ES256/JWT and embeds the x5c cert chain."""
        _, signing_input = compose_unsigned_index_jwt_for_aws_kms_sign(
            image_descriptor, sign_cert_chain=cert_chain
        )

        header = json.loads(_b64url_decode(signing_input.split(".", 1)[0]))
        assert header["alg"] == ALLOWED_JWT_ALG
        assert header["typ"] == "JWT"
        # x5c carries the base64-DER serialized signing cert chain (RFC 7515)
        assert header[X5C_FNAME] == cert_chain.serializer()

    def test_payload_carries_image_index_and_iat(
        self, cert_chain: X5cX509CertChain, image_descriptor: ImageIndex.Descriptor
    ):
        """The payload stamps ``iat`` and round-trips the image_index descriptor."""
        before = int(datetime.now(timezone.utc).timestamp())
        _, signing_input = compose_unsigned_index_jwt_for_aws_kms_sign(
            image_descriptor, sign_cert_chain=cert_chain
        )
        after = int(datetime.now(timezone.utc).timestamp())

        payload = json.loads(_b64url_decode(signing_input.split(".")[1]))

        assert isinstance(payload["iat"], int)
        assert before <= payload["iat"] <= after

        # the payload re-validates into the same claims the read path expects
        claims = IndexJWTClaims.model_validate(payload)
        assert claims.image_index.digest == image_descriptor.digest
        assert claims.image_index.size == image_descriptor.size

    def test_x5c_header_uses_chain_serializer_output(
        self, mocker, image_descriptor: ImageIndex.Descriptor
    ):
        """The x5c header is populated verbatim from ``sign_cert_chain.serializer()``."""
        mock_cert_chain = mocker.MagicMock()
        mock_cert_chain.serializer.return_value = ["cert-a", "cert-b"]

        _, signing_input = compose_unsigned_index_jwt_for_aws_kms_sign(
            image_descriptor, sign_cert_chain=mock_cert_chain
        )

        mock_cert_chain.serializer.assert_called_once_with()
        header = json.loads(_b64url_decode(signing_input.split(".", 1)[0]))
        assert header[X5C_FNAME] == ["cert-a", "cert-b"]


class TestComposeUnsignedIndexJwtForAwsKmsSignRoundTrip:
    """A KMS-signed unsigned index.jwt must verify through the read path."""

    def test_full_round_trip_via_index_jwt_read_path(
        self,
        cert_chain: X5cX509CertChain,
        end_entity_cert: tuple[Certificate, EllipticCurvePrivateKey],
        image_descriptor: ImageIndex.Descriptor,
    ):
        """compose unsigned -> KMS sign (simulated) -> extract chain -> verify."""
        _, ee_key = end_entity_cert  # conftest end-entity key is P-256 (ES256)

        # 1. compose the unsigned signing input for the descriptor
        aws_alg, signing_input = compose_unsigned_index_jwt_for_aws_kms_sign(
            image_descriptor, sign_cert_chain=cert_chain
        )
        assert aws_alg == AWSKMSSignAlgorithm.ECDSA_SHA_256

        # 2. AWS KMS Sign (simulated with the EE key) + compose the final JWT
        token = _simulate_kms_es256_sign(ee_key, signing_input)
        assert token.count(".") == 2

        # 3. the existing read path extracts the x5c chain and verifies the sig
        extracted_chain = get_index_jwt_sign_cert_chain(token)
        assert extracted_chain.ee.subject == cert_chain.ee.subject

        verified = decode_index_jwt_with_verification(token, extracted_chain)
        assert verified.image_index.digest == image_descriptor.digest
        assert verified.image_index.size == image_descriptor.size

    def test_signature_from_unrelated_key_fails_verification(
        self, cert_chain: X5cX509CertChain, image_descriptor: ImageIndex.Descriptor
    ):
        """A signature from a key unrelated to the x5c end-entity cert is rejected."""
        _, signing_input = compose_unsigned_index_jwt_for_aws_kms_sign(
            image_descriptor, sign_cert_chain=cert_chain
        )

        # sign with a key that does NOT match the end-entity cert in the chain
        wrong_key = ec.generate_private_key(ec.SECP256R1())
        token = _simulate_kms_es256_sign(wrong_key, signing_input)

        extracted_chain = get_index_jwt_sign_cert_chain(token)
        with pytest.raises(InvalidSignatureError):
            decode_index_jwt_with_verification(token, extracted_chain)
