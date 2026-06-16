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
"""Shared test fixtures for ota-image-libs tests."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    EllipticCurvePrivateKey,
    EllipticCurvePublicKey,
)
from cryptography.hazmat.primitives.hashes import HashAlgorithm
from cryptography.x509 import Certificate
from cryptography.x509.oid import NameOID

from ota_image_libs._crypto.x509_utils import X5cX509CertChain
from ota_image_libs.common.oci_spec import Sha256Digest
from ota_image_libs.v1.image_index.schema import ImageIndex

TEST_OTA_IMAGE = Path(__file__).parent / "data" / "ota-image.zip"


@pytest.fixture
def test_artifact() -> Path:
    """Provide test OTA image artifact path."""
    return TEST_OTA_IMAGE


@pytest.fixture(scope="session")
def extracted_ota_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Extract the test OTA image to a temporary folder."""
    extract_dir = tmp_path_factory.mktemp("ota_image")
    with ZipFile(TEST_OTA_IMAGE, "r") as zf:
        zf.extractall(extract_dir)
    return extract_dir


def ecdsa_keypair() -> tuple[EllipticCurvePrivateKey, EllipticCurvePublicKey]:
    """Generate ECDSA key pair for testing."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    return private_key, public_key


#
# ------------ Shared JWT / AWS KMS signing test helpers ------------ #
#
# A representative KMS key ARN; only its shape matters for these tests.
FAKE_KMS_KEY_ID = (
    "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab"
)


def b64url_decode(segment: str | bytes) -> bytes:
    """base64url-decode a JWS segment, restoring the stripped padding."""
    raw = segment.encode("ascii") if isinstance(segment, str) else segment
    raw += b"=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw)


def ecdsa_der_sign(
    priv_key: EllipticCurvePrivateKey, message: bytes, digest: HashAlgorithm
) -> bytes:
    """Produce a DER-encoded ECDSA signature over ``message``.

    AWS KMS `Sign` with `MessageType=RAW` hashes the message with the signing
    algorithm's digest and returns the signature DER-encoded (ANSI X9.62-2005 /
    RFC 3279 section 2.2.3); cryptography's ``sign(msg, ECDSA(hash))`` does the
    same, so it stands in for the KMS crypto here.
    """
    return priv_key.sign(message, ec.ECDSA(digest))


def simulate_kms_sign_response(
    priv_key: EllipticCurvePrivateKey,
    message: bytes,
    *,
    digest: HashAlgorithm,
    signing_algorithm: str,
    key_id: str = FAKE_KMS_KEY_ID,
) -> dict[str, str]:
    """Build a self-generated AWS KMS `Sign` response (no live AWS needed).

    Mirrors the documented response syntax::

        {"KeyId": str, "Signature": blob, "SigningAlgorithm": str}

    On the JSON/HTTP wire the `Signature` blob is standard-base64 encoded (boto3
    hands it back already decoded to ``bytes``); we model the wire form here so
    the test exercises the same decode a real caller must perform.

    See https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html#API_Sign_ResponseSyntax
    """
    der_sig = ecdsa_der_sign(priv_key, message, digest)
    return {
        "KeyId": key_id,
        "Signature": base64.b64encode(der_sig).decode("ascii"),
        "SigningAlgorithm": signing_algorithm,
    }


@pytest.fixture(scope="session")
def root_ca_cert() -> tuple[Certificate, EllipticCurvePrivateKey]:
    """Generate a self-signed root CA certificate."""
    private_key, public_key = ecdsa_keypair()

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "JP"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "TOKYO"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Root CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Root CA"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    return cert, private_key


@pytest.fixture(scope="session")
def intermediate_ca_cert(
    root_ca_cert: tuple[Certificate, EllipticCurvePrivateKey],
) -> tuple[Certificate, EllipticCurvePrivateKey]:
    """Generate an intermediate CA certificate signed by root CA."""
    root_cert, root_key = root_ca_cert

    # Generate new key for intermediate CA
    intermediate_key, _ = ecdsa_keypair()

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "JP"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "TOKYO"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Intermediate CA"),
            x509.NameAttribute(NameOID.COMMON_NAME, "Intermediate CA"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(root_cert.subject)
        .public_key(intermediate_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=180))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        )
        .sign(root_key, hashes.SHA256())
    )

    return cert, intermediate_key


@pytest.fixture(scope="session")
def end_entity_cert(intermediate_ca_cert):
    """Generate an end-entity certificate signed by intermediate CA."""
    intermediate_cert, intermediate_key = intermediate_ca_cert

    # Generate new key for end-entity
    ee_key, _ = ecdsa_keypair()

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "JP"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "TOKYO"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Test Organization"),
            x509.NameAttribute(NameOID.COMMON_NAME, "End Entity"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(intermediate_cert.subject)
        .public_key(ee_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=90))
        .sign(intermediate_key, hashes.SHA256())
    )

    return cert, ee_key


@pytest.fixture(scope="session")
def cert_chain(
    intermediate_ca_cert: tuple[Certificate, EllipticCurvePrivateKey],
    end_entity_cert: tuple[Certificate, EllipticCurvePrivateKey],
) -> X5cX509CertChain:
    """Create a certificate chain with end-entity and intermediate certs."""
    intermediate_cert, _ = intermediate_ca_cert
    ee_cert, _ = end_entity_cert

    chain = X5cX509CertChain.validator([ee_cert, intermediate_cert])
    return chain


@pytest.fixture(scope="session")
def image_descriptor() -> ImageIndex.Descriptor:
    """Create a sample image descriptor."""
    _image_index_payload = b"imageindex" * 64
    return ImageIndex.Descriptor(
        digest=Sha256Digest(sha256(_image_index_payload).digest()),
        size=len(_image_index_payload),
    )
