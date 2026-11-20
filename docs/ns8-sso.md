# Zitadel and NS8 single sign-on

## Configure an application with manual OIDC

1. In Zitadel Console, select the organization, create or open a Project, and add an OIDC Application for the consuming NS8 module.
2. Choose the application type and client authentication method required by the consumer. For a confidential web application, use authorization code flow and register the exact HTTPS callback shown by the module. Register its post-logout URL if the module supports it.
3. In the consuming module, choose manual OIDC and enter the issuer `https://<zitadel-host>`, client ID, and client secret where required. The discovery document is `https://<zitadel-host>/.well-known/openid-configuration`. If the UI asks for an issuer, enter the issuer URL rather than the discovery document URL.
4. Test a fresh sign-in while retaining a working administrator session. Consumers such as Warpgate, Termix and Postal have their own session and account-linking settings. If the consumer supports requested scopes, use Zitadel's organization scope or a project authorization policy to route directory users to the intended organization.

## Why the NS8 provider picker does not list Zitadel

Zitadel serves one issuer per instance. Its Organizations and Projects share the issuer in discovery and in signed tokens. Current NS8 OIDC consumers derive the expected issuer from the provider's `issuer_url_prefix` and the selected user domain, then verify registration and discovery against that derived URL. Publishing a Zitadel service with a fabricated per-domain suffix would fail those checks and change how relying parties validate tokens.

The directory-login integration provisions LDAP identity providers on Zitadel. Client registration and NS8 provider advertisement remain future work. Keep JWT issuer validation strict. A proxy can route requests, but a rewrite alone cannot change the issuer of an existing signed token.

## What to change upstream

- Define a provider contract in which `register-client` returns the exact issuer alongside the client ID, secret and organization context. The proposed `srv/http/oidc-client` capability is a discussion point for that contract.
- Update consumers to validate discovery and token issuer against the exact registered issuer. Preserve support for existing realm-based providers.
- Define how a provider supplies organization context, requested scopes and authorization restrictions. Consumers need a stable provider and domain identity across renewals, movement and restore.
- Define registration ownership, callback updates, secret rotation, cleanup and recovery. Test across a realm-based provider, a shared issuer such as Zitadel, and Authentik's per-application issuers.
- Document how JIT LDAP provisioning differs from role or group synchronization. A deployment that needs LDAP groups in tokens must configure explicit mappings through Zitadel project roles or Actions and verify the resulting claims.

## Keeping this guide current

Reviewed against Zitadel **v4.20.5**, NS8 core stable ref `0656e83d2d46ddcbbf2436d072c6c5be5950d307`, and the `ns8-idp` reference commit `428668941469be93fc200c508718171f3c9cdd04`. These are contract review references. Record the exact NS8 core and IdP revisions from the next end-to-end validation run. Revisit the provider contract when the community discussion or NS8 implementation changes.

[Follow the NethServer community discussion on Authentik and Zitadel provider blockers](https://community.nethserver.org/t/ns8-idp-via-authentik-and-zitadel-identified-blockers-for-the-ns8-sso-provider-and-suggested-improvements/29433)
