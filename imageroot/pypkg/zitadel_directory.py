# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
import os
import ssl
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

import agent
from agent.ldapproxy import Ldapproxy

STATE = Path(os.environ.get("AGENT_STATE_DIR", "."))
MAPPING = STATE / "directory-organizations.json"
CREDENTIAL = STATE / "directory-api.json"
POLICY_FIELDS = (
    "allowUsernamePassword", "allowRegister", "allowExternalIdp", "forceMfa",
    "passwordlessType", "hidePasswordReset", "ignoreUnknownUsernames", "defaultRedirectUri",
    "passwordCheckLifetime", "externalLoginCheckLifetime", "mfaInitSkipLifetime",
    "secondFactorCheckLifetime", "multiFactorCheckLifetime", "allowDomainDiscovery",
    "disableLoginWithEmail", "disableLoginWithPhone", "forceMfaLocalOnly",
)


def read(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def write(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        try:
            json.dump(value, stream)
            stream.close()
            os.replace(stream.name, path)
        finally:
            Path(stream.name).unlink(missing_ok=True)


def available():
    proxy = Ldapproxy()
    return [{"name": name, "schema": proxy.domains[name]["schema"]}
            for name in sorted(proxy.get_domains_list())
            if proxy.domains.get(name, {}).get("schema") in ("rfc2307", "ad")]


def selected(request):
    current = read(MAPPING).get("selected", [])
    if "ldap_domain" not in request and "ldap_additional_domains" not in request:
        return current
    primary = request.get("ldap_domain", current[0] if current else "")
    additional = request.get("ldap_additional_domains", current[1:] if primary and current else [])
    names = [primary, *additional] if primary else []
    if (additional and not primary or len(names) != len(set(names)) or
            not set(names).issubset({item["name"] for item in available()})):
        agent.set_status("validation-failed")
        json.dump([{"field": "ldap_domain", "parameter": "ldap_domain", "value": "",
                    "error": "ldap_invalid_selection"}], sys.stdout)
        raise SystemExit(3)
    return names


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class APIError(Exception):
    pass


class Zitadel:
    def __init__(self, host):
        credentials = read(CREDENTIAL)
        if credentials.get("host") != host or not credentials.get("token"):
            raise APIError("Install a directory management token for this Zitadel hostname")
        self.host = host
        self.token = credentials["token"]
        tls = ssl.create_default_context()
        for bundle in ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt"):
            if Path(bundle).is_file():
                tls.load_verify_locations(cafile=bundle)
        self.opener = build_opener(NoRedirect(), ProxyHandler({}), HTTPSHandler(context=tls))

    def call(self, method, path, org=None, data=None, missing=False):
        headers = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json"}
        if org:
            headers["x-zitadel-orgid"] = org
        request = Request("https://" + self.host + path, method=method, headers=headers,
                          data=json.dumps(data).encode() if data is not None else None)
        try:
            with self.opener.open(request, timeout=15) as response:
                return json.loads(response.read() or b"{}")
        except HTTPError as error:
            if missing and error.code == 404:
                return None
            raise APIError(f"Zitadel returned HTTP {error.code} for {method} {path}") from None
        except (URLError, TimeoutError, ValueError):
            raise APIError(f"Zitadel request failed for {method} {path}") from None


def ldap_payload(domain, name):
    attrs = Ldapproxy().get_domain(domain)
    if not attrs or attrs.get("schema") not in ("rfc2307", "ad"):
        raise APIError(f"LDAP proxy credentials are unavailable for {domain}")
    ad = attrs["schema"] == "ad"
    username = "sAMAccountName" if ad else "uid"
    return {
        "name": name, "servers": [f"ldap://accountprovider:{int(attrs['port'])}"],
        "startTls": False, "baseDn": attrs["base_dn"], "bindDn": attrs["bind_dn"],
        "bindPassword": attrs["bind_password"], "userBase": username,
        "userObjectClasses": ["user"] if ad else ["posixAccount"],
        "userFilters": [username], "timeout": "10s",
        "attributes": {"idAttribute": "objectGUID" if ad else "entryUUID",
                       "preferredUsernameAttribute": username, "firstNameAttribute": "givenName",
                       "lastNameAttribute": "sn", "displayNameAttribute": "cn", "emailAttribute": "mail"},
        "providerOptions": {"isCreationAllowed": True, "isAutoCreation": True,
                            "isAutoUpdate": True, "isLinkingAllowed": False},
    }


def reconcile_provider(api, state, domain):
    records = state["organizations"]
    new = domain not in records
    if new:
        records[domain] = {"id": str(uuid4())}
        write(MAPPING, state)
    item = records[domain]
    org = item["id"]
    org_name = "NS8 directory (" + domain + ")"
    if not item.get("created"):
        existing = None if new else api.call("GET", "/management/v1/orgs/me", org, missing=True)
        if not existing:
            result = api.call("POST", "/v2/organizations", data={"organizationId": org, "name": org_name})
            if result.get("organizationId") != org:
                raise APIError("Unexpected organization identifier")
        elif (existing.get("org") or {}).get("id") != org or existing["org"].get("name") != org_name:
            raise APIError("Reserved Zitadel organization identifier is already in use")
        item["created"] = True
        write(MAPPING, state)

    key = hashlib.sha256(domain.encode()).hexdigest()[:12]
    name = f"NS8 LDAP ({domain}) [{key}]"
    payload = ldap_payload(domain, name)
    provider = item.get("provider")
    if not provider:
        candidates = api.call("POST", "/management/v1/idps/templates/_search", org, data={}).get("result", [])
        matches = [p["id"] for p in candidates if p.get("name") == name and p.get("type") == "PROVIDER_TYPE_LDAP" and p.get("owner") == "IDP_OWNER_TYPE_ORG"]
        if len(matches) > 1:
            raise APIError("Multiple providers use the reserved NS8 LDAP name")
        provider = matches[0] if matches else api.call(
            "POST", "/management/v1/idps/ldap", org, payload)["id"]
        item["provider"] = provider
        write(MAPPING, state)
    else:
        api.call("PUT", "/management/v1/idps/ldap/" + quote(provider, safe=""), org,
                 {**payload, "id": provider})

    path = "/management/v1/policies/login"
    result = api.call("GET", path, org)
    policy = result["policy"]
    settings = {key: policy[key] for key in POLICY_FIELDS if key in policy}
    settings["allowExternalIdp"] = True
    link = {"idpId": provider, "ownerType": "IDP_OWNER_TYPE_ORG"}
    if policy.get("isDefault", result.get("isDefault", False)):
        for field, suffix in (("secondFactors", "second_factors"), ("multiFactors", "auth_factors")):
            settings[field] = api.call("POST", path + "/" + suffix + "/_search", org).get("result", [])
        api.call("POST", path, org, {**settings, "idps": [link]})
    else:
        if not policy.get("allowExternalIdp"):
            api.call("PUT", path, org, settings)
        links = api.call("POST", path + "/idps/_search", org, {}).get("result", [])
        if not any(entry.get("idpId") == provider for entry in links):
            api.call("POST", path + "/idps", org, link)
    item["active"] = True
    write(MAPPING, state)


def reconcile(host, names=None):
    with agent.exclusive_file_lock(str(STATE / "directory-lock")):
        state = read(MAPPING)
        desired = state.get("selected", []) if names is None else names
        if not desired and not state.get("organizations"):
            return
        state.setdefault("organizations", {})
        available_names = {item["name"] for item in available()}
        connected = [name for name in desired if name in available_names]
        active = any(item.get("active") for item in state["organizations"].values())
        api = Zitadel(host) if connected or active else None
        rdb = agent.redis_connect()
        existing = agent.get_bound_domain_list(rdb)
        previous = set(state.get("selected", [])) | set(state["organizations"])
        bindings = list(dict.fromkeys([*(name for name in existing if name not in previous), *connected]))
        staging = list(dict.fromkeys([*existing, *bindings]))
        if set(existing) != set(staging) and not agent.bind_user_domains(staging):
            raise APIError("Could not bind the selected NS8 directories")
        for name in connected:
            reconcile_provider(api, state, name)
        for name, item in state["organizations"].items():
            if name not in connected and item.get("active"):
                api.call("DELETE", "/management/v1/policies/login/idps/" + quote(item["provider"], safe=""),
                         item["id"], missing=True)
                item["active"] = False
        if set(staging) != set(bindings) and not agent.bind_user_domains(bindings):
            raise APIError("Could not release obsolete NS8 directory bindings")
        state["selected"] = desired
        write(MAPPING, state)
