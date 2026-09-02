import ProviderSignInButton from "@/app/auth/login/ProviderSignInButton";
import { render } from "@tests/setup/test-utils";

const provider = {
  name: "authentik",
  displayName: "Authentik",
  providerType: "OIDC" as const,
  authorizeUrl: "/api/auth/oidc/authentik/authorize",
};

describe("ProviderSignInButton", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(() => new Promise<Response>(() => {}));
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("starts authentication without a click when auto redirect is enabled", () => {
    render(
      <ProviderSignInButton
        provider={provider}
        nextUrl="/app/agents"
        autoRedirect
      />
    );

    expect(fetchSpy).toHaveBeenCalledWith(
      new URL(
        "/api/auth/oidc/authentik/authorize?next=%2Fapp%2Fagents",
        window.location.origin
      ).toString(),
      { credentials: "include" }
    );
  });
});
