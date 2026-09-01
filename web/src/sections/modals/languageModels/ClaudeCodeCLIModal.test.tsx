import { render, screen, setupUser } from "@tests/setup/test-utils";
import ClaudeCodeCLIModal from "@/sections/modals/languageModels/ClaudeCodeCLIModal";

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

jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: () => false,
}));

describe("ClaudeCodeCLIModal", () => {
  beforeAll(() => {
    Object.defineProperties(HTMLElement.prototype, {
      hasPointerCapture: { value: () => false },
      releasePointerCapture: { value: () => undefined },
      setPointerCapture: { value: () => undefined },
      scrollIntoView: { value: () => undefined },
    });
  });

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders current provider fields and defaults to API key authentication", () => {
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    expect(screen.getByLabelText("CLI Path")).toHaveAttribute(
      "placeholder",
      "claude"
    );
    expect(screen.getByLabelText("Authentication Mode")).toHaveTextContent(
      "API Key"
    );
    expect(screen.getAllByText("API Key").length).toBeGreaterThan(0);
    expect(
      screen.queryByPlaceholderText("Paste your OAuth token")
    ).not.toBeInTheDocument();
  });

  it("switches to OAuth token authentication", async () => {
    const user = setupUser();
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    await user.click(screen.getByLabelText("Authentication Mode"));
    await user.click(screen.getByRole("option", { name: "OAuth Token" }));

    expect(screen.getByLabelText("OAuth Token")).toHaveAttribute(
      "placeholder",
      "Paste your OAuth token"
    );
    expect(screen.queryByLabelText("API Key")).not.toBeInTheDocument();
  });

  it("does not expose the obsolete token-test control", () => {
    render(<ClaudeCodeCLIModal onOpenChange={() => {}} />);

    expect(
      screen.queryByRole("button", { name: "Test Token" })
    ).not.toBeInTheDocument();
  });
});
