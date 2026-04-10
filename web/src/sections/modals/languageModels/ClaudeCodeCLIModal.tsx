"use client";

import { useState, useCallback } from "react";
import { useSWRConfig } from "swr";
import { useField } from "formik";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import * as InputLayouts from "@/layouts/input-layouts";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { toast } from "@/hooks/useToast";

interface ClaudeCodeCLIFormValues extends BaseLLMFormValues {
  custom_config_cli_path: string;
  custom_config_auth_mode: string;
  custom_config_oauth_token: string;
}

function CLIPathField() {
  const [field] = useField("custom_config_cli_path");
  return (
    <div>
      <label className="text-sm font-medium" htmlFor="custom_config_cli_path">
        CLI Path
      </label>
      <p className="text-xs text-muted-foreground mb-2">
        Path to the <code>claude</code> CLI binary. Leave empty to use the
        default (&quot;claude&quot; on PATH).
      </p>
      <input
        id="custom_config_cli_path"
        type="text"
        className="w-full border rounded-md px-3 py-2 text-sm"
        placeholder="claude"
        {...field}
      />
    </div>
  );
}

type TokenTestState =
  | { status: "idle" }
  | { status: "testing" }
  | { status: "success" }
  | { status: "error"; message: string };

function AuthModeField() {
  const [authField, , authHelpers] = useField("custom_config_auth_mode");
  const [tokenField, , tokenHelpers] = useField("custom_config_oauth_token");
  const [cliPathField] = useField("custom_config_cli_path");
  const [testState, setTestState] = useState<TokenTestState>({
    status: "idle",
  });
  const isOAuth = authField.value === "oauth";

  const testToken = useCallback(async () => {
    const token = tokenField.value;
    if (!token) return;

    setTestState({ status: "testing" });
    try {
      const response = await fetch("/api/admin/llm/claude-cli/setup-token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          oauth_token: token,
          cli_path: cliPathField.value || "claude",
        }),
      });
      const data = await response.json();
      if (data.status === "ok") {
        setTestState({ status: "success" });
      } else {
        setTestState({
          status: "error",
          message: data.error || "Unknown error",
        });
      }
    } catch (e) {
      setTestState({
        status: "error",
        message: e instanceof Error ? e.message : "Request failed",
      });
    }
  }, [tokenField.value, cliPathField.value]);

  return (
    <div>
      <label className="text-sm font-medium">Authentication Mode</label>
      <p className="text-xs text-muted-foreground mb-2">
        Choose how the CLI authenticates with Anthropic.
      </p>
      <div className="flex gap-4">
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="radio"
            name="custom_config_auth_mode"
            value="api_key"
            checked={!isOAuth}
            onChange={() => authHelpers.setValue("api_key")}
          />
          API Key
        </label>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="radio"
            name="custom_config_auth_mode"
            value="oauth"
            checked={isOAuth}
            onChange={() => authHelpers.setValue("oauth")}
          />
          OAuth Token
        </label>
      </div>
      {isOAuth && (
        <div className="mt-3 space-y-3">
          <div>
            <label
              className="text-sm font-medium"
              htmlFor="custom_config_oauth_token"
            >
              OAuth Token
            </label>
            <p className="text-xs text-muted-foreground mb-2">
              Generate a token at{" "}
              <a
                href="https://console.anthropic.com/settings/oauth-tokens"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 underline"
              >
                console.anthropic.com
              </a>{" "}
              or run <code>claude setup-token</code> locally, then paste it
              here.
            </p>
            <input
              id="custom_config_oauth_token"
              type="password"
              className="w-full border rounded-md px-3 py-2 text-sm font-mono"
              placeholder="Paste your OAuth token..."
              value={tokenField.value || ""}
              onChange={(e) => {
                tokenHelpers.setValue(e.target.value);
                if (testState.status !== "idle") {
                  setTestState({ status: "idle" });
                }
              }}
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={testToken}
              disabled={!tokenField.value || testState.status === "testing"}
            >
              {testState.status === "testing" ? "Testing..." : "Test Token"}
            </button>
            {testState.status === "success" && (
              <span className="text-sm text-green-700">
                Token validated successfully
              </span>
            )}
            {testState.status === "error" && (
              <span className="text-sm text-red-700">{testState.message}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ClaudeCodeCLIModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const baseInitialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.CLAUDE_CODE_CLI,
    existingLlmProvider
  );

  const existingCliPath =
    existingLlmProvider?.custom_config?.["cli_path"] ?? "";
  const existingAuthMode =
    existingLlmProvider?.custom_config?.["auth_mode"] ?? "api_key";
  const existingOAuthToken =
    existingLlmProvider?.custom_config?.["oauth_token"] ?? "";

  const initialValues: ClaudeCodeCLIFormValues = {
    ...baseInitialValues,
    api_key: existingLlmProvider?.api_key ?? "",
    custom_config_cli_path: existingCliPath,
    custom_config_auth_mode: existingAuthMode,
    custom_config_oauth_token: existingOAuthToken,
  };

  const validationSchema = buildValidationSchema(isOnboarding);

  return (
    <ModalWrapper<ClaudeCodeCLIFormValues>
      providerName={LLMProviderName.CLAUDE_CODE_CLI}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const customConfig: Record<string, string> = {};
        if (values.custom_config_cli_path) {
          customConfig["cli_path"] = values.custom_config_cli_path;
        }
        if (values.custom_config_auth_mode) {
          customConfig["auth_mode"] = values.custom_config_auth_mode;
        }
        if (
          values.custom_config_auth_mode === "oauth" &&
          values.custom_config_oauth_token
        ) {
          customConfig["oauth_token"] = values.custom_config_oauth_token;
        }

        const submitValues: ClaudeCodeCLIFormValues = {
          ...values,
          custom_config: customConfig,
          api_key:
            values.custom_config_auth_mode === "oauth"
              ? "not-required"
              : values.api_key || "not-required",
        };

        await submitProvider<ClaudeCodeCLIFormValues>({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.CLAUDE_CODE_CLI,
          values: submitValues,
          initialValues,
          existingLlmProvider,
          shouldMarkAsDefault,
          setStatus,
          setSubmitting,
          onClose,
          onSuccess: async () => {
            if (onSuccess) {
              await onSuccess();
            } else {
              await refreshLlmProviderCaches(mutate);
              toast.success(
                existingLlmProvider
                  ? "Provider updated successfully!"
                  : "Provider enabled successfully!"
              );
            }
          },
        });
      }}
    >
      <CLIPathField />

      <InputLayouts.FieldSeparator />
      <AuthModeField />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputLayouts.FieldSeparator />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputLayouts.FieldSeparator />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
