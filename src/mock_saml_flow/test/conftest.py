"""Configure test fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from _pytest.assertion import truncate
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from faker import Faker
from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
from saml2.config import Config, IdPConfig
from saml2.metadata import create_metadata_string
from saml2.saml import (
    NAME_FORMAT_UNSPECIFIED,
    NAMEID_FORMAT_PERSISTENT,
    NAMEID_FORMAT_TRANSIENT,
)

# Increase the long string truncation limit when running pytest in
# verbose mode; cf. https://stackoverflow.com/a/60321834.
truncate.DEFAULT_MAX_LINES = 999999
truncate.DEFAULT_MAX_CHARS = 999999


def generate_key_pair() -> Dict[str, str]:
    """Return a self-signed X.509 certificate and private key."""

    # Generate the key pair first.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # SAML does not use certificate name attributes.
    subject = issuer = x509.Name([])

    # Now generate an X.509 certificate.
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before := datetime.now(timezone.utc))
        .not_valid_after(not_valid_before + timedelta(days=3650))
        .sign(key, hashes.SHA256())
    )

    # Return the certificate and key in PEM format.
    return {
        "cert": cert.public_bytes(serialization.Encoding.PEM).decode("utf-8"),
        "key": key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8"),
    }


@pytest.fixture
def saml2_idp_entityid(faker: Faker) -> str:
    """Uniquely identify a mock SAML 2.0 identity provider."""
    return f"https://{faker.hostname()}/"


@pytest.fixture
def saml2_idp_config(
    saml2_idp_entityid: str, tmp_path_factory: pytest.TempPathFactory
) -> Dict[str, Any]:
    """Configure a mock SAML 2.0 identity provider (IdP).  Remember to
    add service provider metadata, whether to this configuration prior
    to starting the SP or afterwards via
    saml2.entity.Entity::reload_metadata().

    :param saml2_idp_entityid: The mock SP entity ID.
    :param tmp_path_factory: pysaml2 stores keying material on disk.
        These files must persist for the lifetime of the IdP
        configuration.

    """

    # Save IdP keymat to disk.
    idp_keymat = generate_key_pair()
    cert_file = tmp_path_factory.getbasetemp() / "idp-cert.pem"
    with cert_file.open("w") as cf:
        cf.write(idp_keymat["cert"])
    key_file = tmp_path_factory.getbasetemp() / "idp-key.pem"
    with key_file.open("w") as kf:
        kf.write(idp_keymat["key"])

    return {
        "entityid": saml2_idp_entityid,
        "xmlsec_binary": None,
        "crypto_backend": "XMLSecurity",  # NB: requires pyXMLSecurity; XML-DSIG only
        "key_file": str(kf.name),
        "cert_file": str(cf.name),
        "service": {
            "idp": {
                "endpoints": {
                    "single_sign_on_service": [
                        (
                            f"{saml2_idp_entityid}saml2/redirect",
                            BINDING_HTTP_REDIRECT,
                        ),
                        (
                            f"{saml2_idp_entityid}saml2/post",
                            BINDING_HTTP_POST,
                        ),
                    ],
                },
                "name_id_format": [
                    NAMEID_FORMAT_PERSISTENT,
                    NAMEID_FORMAT_TRANSIENT,
                    NAME_FORMAT_UNSPECIFIED,
                ],
                "policy": {
                    "default": {
                        "attribute_restrictions": None,
                        "fail_on_missing_requested": False,
                        "lifetime": {
                            "minutes": 15,
                        },
                        "name_form": NAME_FORMAT_UNSPECIFIED,
                        "sign_response": True,
                        "sign_assertion": True,
                    },
                },
            }
        },
    }


@pytest.fixture
def saml2_idp_metadata(
    saml2_idp_config: Dict[str, Any], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Generate metadata for a mock SAML 2.0 identity provider (IdP).
    This needs an IdP configuration with at least an entity ID and
    assertion consumer service URL.

    :param saml2_idp_config: The mock IdP configuration (a fixture).
    :param tmp_path_factory: The directory containing the metadata
        document (a fixture).
    :return: The pathname of a file containing the mock IdP metadata.

    """
    idp_metadata = tmp_path_factory.getbasetemp() / "idp-metadata.xml"
    with idp_metadata.open("wb") as idpm:
        idpm.write(
            create_metadata_string(None, config=IdPConfig().load(saml2_idp_config))
        )
    return idp_metadata


@pytest.fixture
def saml2_sp_entityid(faker: Faker) -> str:
    """Uniquely identify a mock SAML 2.0 service provider."""
    return f"https://{faker.hostname()}/"


@pytest.fixture
def saml2_sp_config(
    saml2_sp_entityid: str, tmp_path_factory: pytest.TempPathFactory
) -> Dict[str, Any]:
    """Configure a mock SAML 2.0 service provider (SP).  Remember to
    add identity provider metadata, whether to this configuration
    prior to starting the SP or afterwards via
    saml2.entity.Entity::reload_metadata().

    :param saml2_sp_entityid: The mock SP entity ID.
    :param tmp_path_factory: pysaml2 stores keying material on disk.
        These files must persist for the lifetime of the SP
        configuration.

    """

    # Save SP keymat to disk.
    sp_keymat = generate_key_pair()
    cert_file = tmp_path_factory.getbasetemp() / "sp-cert.pem"
    with cert_file.open("w") as cf:
        cf.write(sp_keymat["cert"])
    key_file = tmp_path_factory.getbasetemp() / "sp-key.pem"
    with key_file.open("w") as kf:
        kf.write(sp_keymat["key"])

    # Build the SAML 2.0 assertion consumer service URL from the
    # entity ID.  Mind the path separators.
    acs_url = f"{saml2_sp_entityid}saml2/response"

    return {
        "entityid": saml2_sp_entityid,
        "xmlsec_binary": None,
        "crypto_backend": "XMLSecurity",  # NB: requires pyXMLSecurity; XML-DSIG only
        "key_file": str(key_file),
        "cert_file": str(cert_file),
        "service": {
            "sp": {
                "endpoints": {
                    "assertion_consumer_service": [(acs_url, BINDING_HTTP_POST)]
                },
                "want_assertions_or_response_signed": True,
            }
        },
    }


@pytest.fixture
def saml2_sp_metadata(
    saml2_sp_config: Dict[str, Any], tmp_path_factory: pytest.TempPathFactory
) -> Path:
    """Generate metadata for a mock SAML 2.0 service provider (SP).
    This needs an SP configuration with at least an entity ID and
    assertion consumer service URL.

    :param saml2_sp_config: The mock SP configuration (a fixture).
    :param tmp_path_factory: The directory containing the metadata
        document (a fixture).
    :return: The pathname of a file containing the mock SP metadata.

    """
    sp_metadata = tmp_path_factory.getbasetemp() / "sp-metadata.xml"
    with sp_metadata.open("wb") as spm:
        spm.write(create_metadata_string(None, config=Config().load(saml2_sp_config)))
    return sp_metadata
