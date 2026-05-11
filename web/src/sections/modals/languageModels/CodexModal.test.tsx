/**
 * Integration Test: CodexModal
 *
 * Tests the Codex (OpenAI) LLM provider configuration modal,
 * focusing on the OAuth section rendering and the poll-based auth flow.
 */

import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import CodexModal from "@/sections/modals/llmConfig/CodexModal";

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

describe("CodexModal", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  test("renders the OAuth section with 'Sign in with ChatGPT' button", () => {
    render(<CodexModal onOpenChange={() => {}} />);

    expect(screen.getByText("Authentication")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign in with chatgpt/i })
    ).toBeInTheDocument();
  });

  test("renders the API key field as an alternative to OAuth", () => {
    render(<CodexModal onOpenChange={() => {}} />);

    // The API key field label includes "optional" to indicate OAuth is preferred
    expect(
      screen.getByText(/openai.*optional.*alternative to oauth/i)
    ).toBeInTheDocument();
  });

  test("shows user code after starting device auth flow", async () => {
    const user = setupUser();

    // Mock the device auth initiation endpoint
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        user_code: "ABCD-1234",
        verification_uri: "https://chatgpt.com/device",
        device_code: "dev_code_123",
        interval: 5,
        expires_in: 300,
      }),
    } as Response);

    render(<CodexModal onOpenChange={() => {}} />);

    const signInButton = screen.getByRole("button", {
      name: /sign in with chatgpt/i,
    });
    await user.click(signInButton);

    // Verify the user code is displayed
    await waitFor(() => {
      expect(screen.getByText("ABCD-1234")).toBeInTheDocument();
    });

    // Verify the verification URI link is present
    expect(screen.getByText("https://chatgpt.com/device")).toBeInTheDocument();
    expect(
      screen.getByText(/waiting for authorization/i)
    ).toBeInTheDocument();

    // Verify the device auth API was called
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/codex/device-auth",
      expect.objectContaining({ method: "POST" })
    );
  });

  test("shows success message after successful OAuth poll", async () => {
    jest.useFakeTimers();
    const user = setupUser({ delay: null });

    // Mock the device auth initiation
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        user_code: "TEST-CODE",
        verification_uri: "https://chatgpt.com/device",
        device_code: "dev_code_456",
        interval: 1, // 1 second interval for faster test
        expires_in: 300,
      }),
    } as Response);

    // Mock the poll response - authorized on first poll
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        status: "authorized",
        access_token: "test_access_token",
        refresh_token: "test_refresh_token",
        expires_in: 3600,
      }),
    } as Response);

    render(<CodexModal onOpenChange={() => {}} />);

    const signInButton = screen.getByRole("button", {
      name: /sign in with chatgpt/i,
    });
    await user.click(signInButton);

    // Wait for the user code to appear
    await waitFor(() => {
      expect(screen.getByText("TEST-CODE")).toBeInTheDocument();
    });

    // Advance timers to trigger poll
    jest.advanceTimersByTime(1500);

    // Wait for the success message
    await waitFor(() => {
      expect(
        screen.getByText(/successfully authenticated/i)
      ).toBeInTheDocument();
    });

    // Verify the poll endpoint was called
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/admin/llm/codex/device-auth/poll",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          device_code: "dev_code_456",
          user_code: "TEST-CODE",
        }),
      })
    );

    jest.useRealTimers();
  });

  test("shows error message when device auth initiation fails", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: "Service unavailable" }),
    } as Response);

    render(<CodexModal onOpenChange={() => {}} />);

    const signInButton = screen.getByRole("button", {
      name: /sign in with chatgpt/i,
    });
    await user.click(signInButton);

    await waitFor(() => {
      expect(
        screen.getByText(/failed to start device auth/i)
      ).toBeInTheDocument();
    });

    // Should show a "Try again" button
    expect(
      screen.getByRole("button", { name: /try again/i })
    ).toBeInTheDocument();
  });
});
