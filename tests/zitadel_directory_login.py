"""Verify the v1 login flow against an existing NS8 test installation."""
import base64
import hashlib
import http.cookiejar
import json
import secrets
import ssl
import subprocess
import sys
from pathlib import Path
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)


class LoginPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.links = []
        self.forms = []
        self.form = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "a" and "href" in data:
            self.links.append(data["href"])
        if tag == "form":
            self.form = {"action": data.get("action", ""), "method": data.get("method", "get"),
                         "inputs": {}, "buttons": []}
            self.forms.append(self.form)
        if self.form is not None and tag == "input" and data.get("name"):
            if data.get("type") not in ("submit", "button", "checkbox"):
                self.form["inputs"][data["name"]] = data.get("value", "")
        if self.form is not None and tag == "button" and data.get("id"):
            self.form["buttons"].append(data["id"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.form = None

    def form_for(self, field):
        return next((form for form in self.forms if field in form["inputs"]), None)

    def ldap_link(self, idp):
        # The rendered provider link includes the LDAP identity provider ID.
        return next((link for link in self.links
                     if parse_qs(urlsplit(link).query).get("idpConfigID") == [idp]), None)


class Callback(HTTPRedirectHandler):
    def __init__(self, uri, origin):
        self.uri = uri
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl.partition("?")[0] == self.uri:
            raise AuthorizationResult(parse_qs(urlsplit(newurl).query))
        assert newurl.startswith(self.origin + "/"), "Unexpected login redirect origin"
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class AuthorizationResult(Exception):
    def __init__(self, parameters):
        self.parameters = parameters


class ZitadelTest:
    def __init__(self, host, ca, token, callback):
        self.base = f"https://{host}"
        self.callback = callback
        self.context = ssl.create_default_context(cafile=ca)
        self.token = token
        self.discovery = self.request("/.well-known/openid-configuration", authenticated=False)
        assert self.discovery["issuer"] == self.base, "Unexpected Zitadel issuer"
        for name in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
            assert self.discovery[name].startswith(self.base + "/"), "Unexpected Zitadel endpoint origin"

    def request(self, path, payload=None, org=None, authenticated=True):
        headers = {}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.token
        if org:
            headers["x-zitadel-orgid"] = org
        if payload is not None:
            headers["Content-Type"] = "application/json"
        req = Request(urljoin(self.base, path), json.dumps(payload).encode() if payload is not None else None,
                      headers)
        with build_opener(ProxyHandler({}), HTTPSHandler(context=self.context)).open(req, timeout=20) as response:
            return json.load(response)

    def authorization(self, client, org=None):
        verifier = secrets.token_urlsafe(40)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(20)
        scope = "openid profile"
        if org:
            scope += f" urn:zitadel:iam:org:id:{org}"
        query = urlencode({"response_type": "code", "client_id": client, "redirect_uri": self.callback,
                           "scope": scope, "state": state, "code_challenge": challenge,
                           "code_challenge_method": "S256", "prompt": "login"})
        return self.discovery["authorization_endpoint"] + "?" + query, state, verifier

    def browser(self):
        return build_opener(ProxyHandler({}), HTTPSHandler(context=self.context),
                            HTTPCookieProcessor(http.cookiejar.CookieJar()), Callback(self.callback, self.base))

    @staticmethod
    def open_page(browser, url, data=None, referer=None):
        headers = {"Referer": referer} if referer else {}
        with browser.open(Request(url, data, headers), timeout=25) as response:
            return response.geturl(), LoginPage(response.read().decode())

    def submit(self, browser, url, form, **fields):
        assert form is not None, f"Missing login form at {urlsplit(url).path}"
        data = urlencode({**form["inputs"], **fields})
        action = urljoin(url, form["action"])
        assert action.startswith(self.base + "/"), "Unexpected login form origin"
        if form["method"].lower() == "post":
            return self.open_page(browser, action, data.encode(), referer=url)
        return self.open_page(browser, action + ("&" if "?" in action else "?") + data)

    def sign_in(self, client, username, password, org=None, idp=None, expect_rejection=False):
        browser = self.browser()
        authorize, state, verifier = self.authorization(client, org)
        url, page = self.open_page(browser, authorize)
        try:
            if idp:
                if not page.form_for("ldappassword"):
                    link = page.ldap_link(idp)
                    assert link, f"Missing LDAP provider link at {urlsplit(url).path}"
                    link = urljoin(url, link)
                    assert link.startswith(self.base + "/"), "Unexpected LDAP login URL"
                    url, page = self.open_page(browser, link)
                url, page = self.submit(browser, url, page.form_for("ldappassword"),
                                        ldapusername=username, ldappassword=password)
                if expect_rejection:
                    assert page.form_for("ldappassword"), "The LDAP login did not report rejection"
                    return None
            else:
                url, page = self.submit(browser, url, page.form_for("loginName"), loginName=username)
                url, page = self.submit(browser, url, page.form_for("password"), password=password)
            completion = next((form for form in page.forms if "redirect-button" in form["buttons"]), None)
            assert completion is not None, f"Sign-in did not complete at {urlsplit(url).path}"
            self.submit(browser, url, completion)
        except AuthorizationResult as result:
            assert result.parameters.get("state") == [state]
            if expect_rejection:
                assert "code" not in result.parameters, "LDAP sign-in unexpectedly succeeded"
                assert result.parameters.get("error") in (["access_denied"], ["login_required"])
                return None
            assert "code" in result.parameters, "Zitadel rejected sign-in"
            code = result.parameters["code"][0]
        else:
            raise AssertionError("No authorization code was returned")
        token_request = urlencode({"grant_type": "authorization_code", "client_id": client, "code": code,
                                   "redirect_uri": self.callback, "code_verifier": verifier}).encode()
        with self.browser().open(self.discovery["token_endpoint"], token_request, timeout=20) as response:
            # This is the response from the test server over verified TLS. Use
            # the returned access token at UserInfo to identify the actual user.
            access_token = json.load(response)["access_token"]
        request = Request(self.discovery["userinfo_endpoint"], headers={"Authorization": "Bearer " + access_token})
        with self.browser().open(request, timeout=20) as response:
            return json.load(response)["sub"]

    def user(self, user_id):
        return self.request(f"/v2/users/{user_id}")["user"]

    def provider(self, org):
        results = self.request("/management/v1/policies/login/idps/_search", {}, org).get("result", [])
        return next(item["idpId"] for item in results if item.get("idpName", "").startswith("NS8 LDAP ("))


def check_user(test, user_id, fixture):
    user = test.user(user_id)
    assert user["details"]["resourceOwner"] == fixture["organization_id"], "User belongs to a different organization"
    assert user["username"] == fixture["username"], "Zitadel returned a different user"


def check_recovery(test, admin):
    user_id = test.sign_in(admin["client_id"], admin["login_name"], admin["password"])
    assert user_id == admin["user_id"], "The local sign-in resolved to a different user"


def main():
    fixture_path, scenario = sys.argv[1:]
    path = Path(fixture_path)
    assert path.stat().st_mode & 0o077 == 0, "The fixture must be readable only by its owner"
    fixture = json.loads(path.read_text())
    test = ZitadelTest(fixture["host"], fixture.get("ca_file"), fixture["read_token"], fixture["callback"])
    config = json.loads(subprocess.check_output(
        ["api-cli", "run", f"module/{fixture['module_id']}/get-configuration"],
        text=True,
    ))
    assert config["host"] == fixture["host"], "Fixture hostname does not match the NS8 module"
    directories = fixture["directories"]
    assert set(directories) == {"openldap", "samba_ad"}
    assert len({item["organization_id"] for item in directories.values()}) == 2
    if scenario in {"online", "outage"}:
        assert config["ldap_organizations"] == {
            item["domain"]: item["organization_id"] for item in directories.values()
        }, "Selected domains do not match the expected Zitadel organizations"
    elif scenario == "unlinked":
        assert not config["ldap_organizations"], "NS8 still reports active LDAP organizations"
    if scenario == "online":
        users = set()
        for backend, info in directories.items():
            print(f"Checking {backend} sign-in and organization membership", flush=True)
            org = info["organization_id"]
            assert test.provider(org) == info["provider_id"], "Unexpected managed LDAP provider"
            user_id = test.sign_in(info["client_id"], info["username"], info["password"],
                                   org, info["provider_id"])
            check_user(test, user_id, info)
            users.add(user_id)
            test.sign_in(info["client_id"], info["username"], secrets.token_urlsafe(32),
                         org, info["provider_id"], expect_rejection=True)
        assert len(users) == 2
        check_recovery(test, fixture["local_admin"])
    elif scenario == "outage":
        for backend, info in directories.items():
            print(f"Checking that {backend} cannot authenticate during the outage", flush=True)
            test.sign_in(info["client_id"], info["username"], info["password"],
                         info["organization_id"], info["provider_id"], expect_rejection=True)
        check_recovery(test, fixture["local_admin"])
    elif scenario == "unlinked":
        for backend, info in directories.items():
            print(f"Checking retained {backend} account and removed provider link", flush=True)
            org = info["organization_id"]
            check_user(test, info["user_id"], info)
            links = test.request("/management/v1/policies/login/idps/_search", {}, org).get("result", [])
            assert not any(link["idpId"] == info["provider_id"] for link in links)
            authorize, _, _ = test.authorization(info["client_id"], org)
            _, page = test.open_page(test.browser(), authorize)
            assert not page.form_for("ldappassword") and not page.ldap_link(info["provider_id"])
        check_recovery(test, fixture["local_admin"])
    else:
        raise ValueError("Choose online, outage, or unlinked")
    print("Zitadel directory validation passed:", scenario)


if __name__ == "__main__":
    try:
        main()
    except HTTPError as error:
        sys.exit(f"HTTP {error.code} at {urlsplit(error.url).path}")
