"""Exercise reconciliation without a live NS8 node or Zitadel instance."""
import importlib.util
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


class DirectoryTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        self.bindings = []
        self.schemas = {"ldap.test": "rfc2307", "ad.test": "ad"}
        agent = ModuleType("agent")
        agent.exclusive_file_lock = lambda path: nullcontext()
        agent.redis_connect = lambda: None
        agent.get_bound_domain_list = lambda rdb: self.bindings

        def bind(names):
            self.bindings = names
            return True

        agent.bind_user_domains = bind
        proxy = ModuleType("agent.ldapproxy")

        class Proxy:
            def __init__(proxy_self):
                proxy_self.domains = {name: {"schema": schema} for name, schema in self.schemas.items()}

            def get_domains_list(proxy_self):
                return self.schemas

            def get_domain(proxy_self, name):
                return {"schema": self.schemas[name], "port": 12345, "base_dn": "dc=site,dc=test",
                        "bind_dn": "cn=test", "bind_password": "mock-secret"}

        proxy.Ldapproxy = Proxy
        implementation = Path(__file__).parents[1] / "imageroot/pypkg/zitadel_directory.py"
        spec = importlib.util.spec_from_file_location("zitadel_directory", implementation)
        self.directory = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"agent": agent, "agent.ldapproxy": proxy}):
            spec.loader.exec_module(self.directory)
        self.directory.MAPPING = Path(self.state.name) / "mapping.json"
        self.directory.STATE = Path(self.state.name)
        self.calls = []
        self.linked = set()
        self.directory.Zitadel = lambda host: self

    def call(self, method, path, org=None, data=None, missing=False):
        self.calls.append((method, path, org, data))
        if path == "/v2/organizations":
            return {"organizationId": data["organizationId"]}
        if path == "/management/v1/idps/ldap":
            return {"id": "provider-" + org}
        if method == "GET" and path.endswith("/policies/login"):
            return {"policy": {"isDefault": org not in self.linked, "allowUsernamePassword": True}}
        if method == "POST" and path.endswith("/policies/login"):
            self.assertTrue(data["allowUsernamePassword"])
            self.linked.add(org)
        if path.endswith("/policies/login/idps/_search") and org in self.linked:
            return {"result": [{"idpId": "provider-" + org}]}
        return {"result": []}

    def test_two_domains_reuse_organizations_and_remove_policy_link(self):
        directory = self.directory
        directory.reconcile("zitadel.example.test", ["ldap.test", "ad.test"])
        current = directory.read(directory.MAPPING)["organizations"]
        self.assertNotEqual(current["ldap.test"]["id"], current["ad.test"]["id"])
        providers = [data for _, path, _, data in self.calls if path == "/management/v1/idps/ldap"]
        self.assertEqual([p["attributes"]["idAttribute"] for p in providers], ["entryUUID", "objectGUID"])
        self.calls.clear()
        directory.reconcile("zitadel.example.test", ["ad.test"])
        self.assertEqual(self.bindings, ["ad.test"])
        self.assertEqual([org for method, _, org, _ in self.calls if method == "DELETE"],
                         [current["ldap.test"]["id"]])
        self.assertFalse(any(path == "/v2/organizations" for _, path, _, _ in self.calls))
        self.assertEqual(directory.MAPPING.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
