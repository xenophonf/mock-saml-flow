import random
import string
from pathlib import Path
from typing import Any, Dict

import pytest
from saml2 import BINDING_HTTP_REDIRECT
from saml2.client import Saml2Client
from saml2.config import Config


@pytest.mark.order("first")
@pytest.mark.smoke
def test_saml_flow(
    saml2_idp_entityid: str,
    saml2_idp_config: Dict[str, Any],
    saml2_idp_metadata: Path,
    saml2_sp_entityid: str,
    saml2_sp_config: Dict[str, Any],
    saml2_sp_metadata: Path,
):
    """Log into a mock SAML 2.0 service provider (SP) using a mock
    SAML 2.0 identity provider (IdP).

    """

    # Add the mock SP metadata to the mock IdP configuration.
    saml2_idp_config["metadata"] = {"local": [str(saml2_sp_metadata)]}

    # Add the mock IdP metadata to the mock SP configuration.
    saml2_sp_config["metadata"] = {"local": [str(saml2_idp_metadata)]}

    # Request authentication.  The SP should redirect to the IdP.
    # Include a random relay state.
    relay_state = "".join(random.sample(string.ascii_letters, 8))
    client = Saml2Client(config=Config().load(saml2_sp_config))
    request_id, request_binding, request_http_args = (
        client.prepare_for_negotiated_authenticate(
            entity_id=saml2_idp_entityid, relay_state=relay_state
        )
    )
    assert request_binding == BINDING_HTTP_REDIRECT
    redirect_url = dict(request_http_args["headers"])["Location"]
    assert saml2_idp_entityid in redirect_url
