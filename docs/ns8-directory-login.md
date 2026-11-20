# NS8 directory login in Zitadel

## Before you enable it

1. Back up the module and verify your local Zitadel instance administrator can sign in from a separate browser session. Keep an independent local account for recovery.
2. Configure the instance hostname and a certificate trusted by the NS8 node. The module calls the Zitadel API over HTTPS and checks the certificate.
3. Create a dedicated Zitadel service account with permission to create organizations and manage their identity providers and login policies. For the initial rollout, use the instance `IAM_OWNER` role and a time-limited personal access token. Treat this token as an instance administrator credential. Run `runagent -m zitadel1 zitadel-directory-token` interactively on the module's node and paste the token at the hidden prompt.
4. In NS8 **Settings**, choose a primary NS8 user domain. Add further domains using **Additional user domains**. Save and pilot one existing directory account before enabling this for users.

## Organizations and sign-in

The module creates a dedicated organization named `NS8 directory (<domain>)` for each selected domain. Each has its own LDAP provider. Two directories can have the same username because their users belong to different organizations. To use directory sign-in, start from an application targeting that organization or request the Zitadel OIDC scope `urn:zitadel:iam:org:id:<organization-id>`. The organization ID is available in Zitadel Console and in the module's `get-configuration` response. Select the LDAP provider on that organization's login screen.

Zitadel provisions users on their first successful LDAP sign-in and refreshes mapped attributes on later sign-ins. The connector does not import a directory in advance or copy LDAP groups into application roles. Automatic linking to existing local accounts is disabled. Pilot any account migration to confirm that existing users and application assignments remain accessible.

## How the module implements federation

- The agent discovers OpenLDAP and Samba AD user domains and binds the selected domains through NS8. Bind credentials are resolved from the node's LDAP proxy. LDAP traffic from the Zitadel pod uses the proxy's host-loopback listener.
- OpenLDAP users use `posixAccount`, `uid` and `entryUUID`. Samba AD users use `user`, `sAMAccountName` and `objectGUID`. Verify that pilot accounts expose the mapped names and email attributes.
- The module allocates and records an organization ID before making the organization API call. It records the LDAP provider ID and limits changes to the organizations and providers it manages. Organizations use the v2 API. LDAP provider and login-policy operations use the pinned v1 Management API.
- A domain-change event re-reads the selected domains and proxy configuration. If a domain disappears, reconciliation removes its policy link while retaining the organization, provider and users. If it returns, reconciliation can reattach the same provider.
- The management token is stored in a mode-0600 module state file scoped to the configured hostname. It is excluded from backups. Reinstall a token after restoring, cloning, rotating or changing the hostname, then save the directory configuration again. The organization mapping is included with the database backup.

## Rollback

Clear the primary selection to disconnect all managed domains or remove an additional domain to disconnect one. The module removes the managed policy link and releases the directory binding while retaining the Zitadel users and organizations. Keep the management token valid until the directory is disconnected. Verify the instance administrator's local account and existing applications afterwards. If the token expires, install a fresh one and save the settings again. Already-issued application sessions follow their own expiration and revocation policy.

[Zitadel LDAP federation](https://zitadel.com/docs/guides/integrate/identity-providers/ldap) · [Manual application OIDC and NS8 discovery](ns8-sso.md)
