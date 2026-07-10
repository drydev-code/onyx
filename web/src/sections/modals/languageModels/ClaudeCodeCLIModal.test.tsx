/**
 * Integration Test: ClaudeCodeCLIModal
 *
 * Tests the Claude Code CLI LLM provider configuration modal,
 * focusing on the auth mode toggle (API Key vs OAuth) and
 * the OAuth token field visibility.
 */

import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ClaudeCodeCLIModal from "@/sections/modals/llmConfig/ClaudeCodeCLIModal";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockMutate = jest.fn();
jest.mock("swr", () => {
  const actual = jest.requireActual("swr");
  return {
    ...actual,
    useSWRConfig: () => ({ mutate: mockMutate }),
    __esModule: true,
    default: () => ({ data: undefined, error: undefined, isLoading: false }),
  };
});

jest.mock("@/hooks/useToast", () => {
  const success = jest.fn();
  const error = jest.fn();
  const toastFn = Object.assign(jest.fn(), {
    success,
    error,
    info: jest.fn(),
    warning: jest.fn(),
    dismiss: jest.fn(),
    clearAll: jest.fn(),
    _markLeaving: jest.fn(),
  });
  return {
    toast: toastFn,
    useToast: () => ({
      toast: toastFn,
      dismiss: toastFn.dismiss,
      clearAll: toastFn.clearAll,
    }),
  };
});

jest.mock("@/components/settings/usePaidEnterpriseFeaturesEnabled", () => ({
  usePaidEnterpriseFeaturesEnabled: () => false,
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ClaudeCodeCLIModal", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("renders the CLI Path field", () => {
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    expect(screen.getByLabelText(/cli path/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("claude")).toBeInTheDocument();
  });

  test("renders the Authentication Mode radio buttons", () => {
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    expect(screen.getByText("Authentication Mode")).toBeInTheDocument();
    expect(screen.getByLabelText("API Key")).toBeInTheDocument();
    expect(screen.getByLabelText("OAuth Token")).toBeInTheDocument();
  });

  test("defaults to API Key auth mode", () => {
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    const apiKeyRadio = screen.getByLabelText("API Key") as HTMLInputElement;
    const oauthRadio = screen.getByLabelText("OAuth Token") as HTMLInputElement;

    expect(apiKeyRadio.checked).toBe(true);
    expect(oauthRadio.checked).toBe(false);
  });

  test("does not show OAuth token input when API Key mode is selected", () => {
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    // The OAuth token input should not be visible in API Key mode
    expect(
      screen.queryByPlaceholderText(/paste your oauth token/i)
    ).not.toBeInTheDocument();
  });

  test("shows OAuth token input when OAuth mode is selected", async () => {
    const user = setupUser();

    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    // Click the OAuth Token radio
    const oauthRadio = screen.getByLabelText("OAuth Token");
    await user.click(oauthRadio);

    // The OAuth token input should now appear
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText(/paste your oauth token/i)
      ).toBeInTheDocument();
    });

    // The "Test Token" button should also appear
    expect(
      screen.getByRole("button", { name: /test token/i })
    ).toBeInTheDocument();
  });

  test("Test Token button is disabled when OAuth token field is empty", async () => {
    const user = setupUser();

    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    // Switch to OAuth mode
    const oauthRadio = screen.getByLabelText("OAuth Token");
    await user.click(oauthRadio);

    await waitFor(() => {
      const testButton = screen.getByRole("button", { name: /test token/i });
      expect(testButton).toBeDisabled();
    });
  });

  test("Test Token button is enabled when OAuth token is provided", async () => {
    const user = setupUser();

    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    // Switch to OAuth mode
    await user.click(screen.getByLabelText("OAuth Token"));

    // Type a token value
    const tokenInput = await screen.findByPlaceholderText(
      /paste your oauth token/i
    );
    await user.type(tokenInput, "my-test-token");

    await waitFor(() => {
      const testButton = screen.getByRole("button", { name: /test token/i });
      expect(testButton).not.toBeDisabled();
    });
  });

  test("shows success message after successful token test", async () => {
    const user = setupUser();
    const fetchSpy = jest.spyOn(global, "fetch");

    // Mock the token test endpoint
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "ok" }),
    } as Response);

    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    // Switch to OAuth mode and enter a token
    await user.click(screen.getByLabelText("OAuth Token"));
    const tokenInput = await screen.findByPlaceholderText(
      /paste your oauth token/i
    );
    await user.type(tokenInput, "valid-token");

    // Click Test Token
    const testButton = screen.getByRole("button", { name: /test token/i });
    await user.click(testButton);

    // Verify success message
    await waitFor(() => {
      expect(
        screen.getByText(/token validated successfully/i)
      ).toBeInTheDocument();
    });

    // Verify the correct API endpoint was called
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/claude-cli/setup-token",
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining("valid-token"),
      })
    );

    fetchSpy.mockRestore();
  });

  test("shows error message after failed token test", async () => {
    const user = setupUser();
    const fetchSpy = jest.spyOn(global, "fetch");

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "error", error: "Token expired" }),
    } as Response);

    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    // Switch to OAuth mode and enter a token
    await user.click(screen.getByLabelText("OAuth Token"));
    const tokenInput = await screen.findByPlaceholderText(
      /paste your oauth token/i
    );
    await user.type(tokenInput, "expired-token");

    // Click Test Token
    await user.click(screen.getByRole("button", { name: /test token/i }));

    // Verify error message
    await waitFor(() => {
      expect(screen.getByText("Token expired")).toBeInTheDocument();
    });

    fetchSpy.mockRestore();
  });

  test("renders MCP Configuration field", () => {
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    expect(
      screen.getByLabelText(/mcp configuration/i)
    ).toBeInTheDocument();
  });

});
