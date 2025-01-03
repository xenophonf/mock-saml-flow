import random
import string
from html.parser import HTMLParser
from pathlib import Path
from pprint import pprint
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

import pytest
from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
from saml2.client import Saml2Client
from saml2.config import Config, IdPConfig
from saml2.request import AuthnRequest
from saml2.samlp import AuthnRequest as AuthnRequestElement
from saml2.samlp import Response
from saml2.server import Server
from saml2.sigver import encrypt_cert_from_item


class Saml2AcsFormParser(HTMLParser):
    """Extract the SAML response from an HTML form."""

    saml_response: str | None
    relay_state: str | None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saml_response = None
        self.relay_state = None

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Any]]):
        """Retrieve the values of the `SAMLResponse` or the
        `RelayState` input tags.

        """
        if "input" == tag.casefold():
            # I don't know why attrs is a list of tuples, and at this
            # point, I'm too afraid to ask.
            attributes = dict(attrs)

            # Skip this input tag if it doesn't have a name or a value
            # attribute.
            if "name" not in attributes or "value" not in attributes:
                return

            if "samlresponse" == attributes["name"].casefold():
                self.saml_response = attributes["value"]
            elif "relaystate" == attributes["name"].casefold():
                self.relay_state = attributes["value"]


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
    # View output with pytest -s;
    # cf. https://docs.pytest.org/en/latest/capture.html.
    pprint(
        {
            "request_id": request_id,
            "request_binding": request_binding,
            "request_http_args": request_http_args,
        }
    )

    # At this point, a web browser would forward the authentication
    # request to the IdP, so extract it from the URL, same as any web
    # framework would.
    qs = parse_qs(urlparse(redirect_url).query)
    encoded_saml_request = qs["SAMLRequest"][0]
    assert encoded_saml_request
    pprint({"encoded_saml_request": encoded_saml_request})

    # Parse the authentication request.
    server = Server(config=IdPConfig().load(saml2_idp_config))
    saml_request = server.parse_authn_request(encoded_saml_request, request_binding)
    assert isinstance(saml_request, AuthnRequest)
    authn_req: AuthnRequestElement = saml_request.message
    pprint({"saml_request": saml_request})

    # Determine how to respond.
    response_args = server.response_args(authn_req)
    for key in [
        "binding",
        "destination",
        "in_response_to",
        "name_id_policy",
        "sp_entity_id",
    ]:
        assert key in response_args
    assert BINDING_HTTP_POST == response_args["binding"]
    assert saml2_sp_entityid == response_args["sp_entity_id"]
    assert response_args["destination"].startswith(saml2_sp_entityid)
    pprint({"response_args": response_args})

    # Respond to the authentication request.
    saml_response: Response = server.create_authn_request_response(
        {}, encrypt_cert=encrypt_cert_from_item(authn_req), **response_args
    )
    assert saml_response
    pprint({"saml_response": saml_response})
