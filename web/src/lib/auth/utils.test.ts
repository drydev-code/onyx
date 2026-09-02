import { AuthTypeMetadata } from "@/lib/auth/types";
import { shouldAutoRedirectToSSO } from "@/lib/auth/utils";

function metadata(overrides: Partial<AuthTypeMetadata> = {}): AuthTypeMetadata {
  return {
    multiTenant: false,
    requiresVerification: false,
    anonymousUserEnabled: false,
    passwordMinLength: 8,
    passwordMaxLength: 64,
    passwordRequireUppercase: false,
    passwordRequireLowercase: false,
    passwordRequireDigit: false,
    passwordRequireSpecialChar: false,
    hasUsers: true,
    oauthEnabled: true,
    passwordAuthEnabled: false,
    ssoProviders: [
      {
        name: "authentik",
        displayName: "Authentik",
        providerType: "OIDC",
        authorizeUrl: "/api/auth/oidc/authentik/authorize",
      },
    ],
    ...overrides,
  };
}

describe("shouldAutoRedirectToSSO", () => {
  it("redirects when password login is disabled and one provider exists", () => {
    expect(shouldAutoRedirectToSSO(metadata())).toBe(true);
  });

  it("keeps the login page when password login is enabled", () => {
    expect(
      shouldAutoRedirectToSSO(metadata({ passwordAuthEnabled: true }))
    ).toBe(false);
  });

  it("keeps the login page when multiple providers are enabled", () => {
    const provider = metadata().ssoProviders![0]!;
    expect(
      shouldAutoRedirectToSSO(
        metadata({ ssoProviders: [provider, { ...provider, name: "backup" }] })
      )
    ).toBe(false);
  });

  it("keeps the login page for cloud deployments", () => {
    expect(shouldAutoRedirectToSSO(metadata({ multiTenant: true }))).toBe(
      false
    );
  });
});
