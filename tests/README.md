# Zitadel tests

The standard QEMU suite installs the module, checks HTTPS, and reads back the default directory settings. The mocked reconciliation test runs with `python3 tests/test_directory.py`.

## Live directory validation with an existing test installation

`directory_live.robot` uses the same SSH-based Robot test runner as the other NS8 identity modules. It needs an existing NS8 test node with the candidate Zitadel module configured for one OpenLDAP domain and one Samba AD domain. The test uses existing accounts and OIDC applications. It does not provision services, create accounts, or outage a directory. The test exercises Zitadel’s actual login forms and exchanges the authorization code. Zitadel itself may create a user on the first successful LDAP login.

Use Login V1 and public web OIDC applications with authorization code and S256 PKCE. Use fixture accounts for which the test login policy permits the password flow. Register the same HTTPS callback on all three applications. The test captures the callback instead of contacting it. The test node must resolve the Zitadel hostname and trust its certificate. Provide an existing token with permission to read the managed login policies and the test users.

On the **test node**, put a JSON fixture in a file readable only by its owner, such as `/root/zitadel-directory-fixture.json` with mode `0600`. The exact field names are shown below. Keep the file out of Git and CI artifacts.

```json
{
  "module_id": "zitadel1",
  "host": "zitadel.test.example",
  "callback": "https://test-app.example/oidc/callback",
  "read_token": "<existing read token>",
  "local_admin": {
    "client_id": "<local admin OIDC application>",
    "login_name": "<existing local administrator login>",
    "password": "<test password>",
    "user_id": "<existing local administrator ID>"
  },
  "directories": {
    "openldap": {
      "domain": "ldap.test.example",
      "organization_id": "<managed Zitadel organization ID>",
      "provider_id": "<managed Zitadel LDAP provider ID>",
      "client_id": "<OpenLDAP OIDC application client ID>",
      "username": "<test directory username>",
      "password": "<test password>",
      "user_id": "<Zitadel user ID after the first sign-in>"
    },
    "samba_ad": {
      "domain": "ad.test.example",
      "organization_id": "<managed Zitadel organization ID>",
      "provider_id": "<managed Zitadel LDAP provider ID>",
      "client_id": "<Samba AD OIDC application client ID>",
      "username": "<test directory username>",
      "password": "<test password>",
      "user_id": "<Zitadel user ID after the first sign-in>"
    }
  }
}
```

If needed, set the optional `ca_file` to an existing CA bundle path on the test node. The `user_id` in each directory entry is required for the `unlinked` scenario.

Run the live suite from the module repository using the same Robot runner and SSH access as the smoke tests:

```bash
robot --suite 'Directory Live' \
  --variable NODE_ADDR:<test-node-address> \
  --variable SSH_KEYFILE:<test-node-ssh-key> \
  --variable ZITADEL_DIRECTORY_FIXTURE:/root/zitadel-directory-fixture.json \
  --variable ZITADEL_DIRECTORY_SCENARIO:online tests
```

- **online** verifies both successful directory logins, rejection of invalid passwords, that the negotiated users belong to different managed organizations, and independent local administrator login.
- **outage** is run after making both test directories unavailable to the target instance while leaving the providers linked. The test requires valid directory credentials to be rejected and local administrator login to succeed in a fresh session.
- **unlinked** is run after clearing both selections in NS8 Settings. The test requires the LDAP login links to be absent and checks that both provisioned accounts remain in their organizations and the independent administrator can still sign in.

The QEMU workflow reports the live case as skipped when no fixture path is supplied.
