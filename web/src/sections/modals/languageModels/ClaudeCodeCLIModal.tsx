"use client";

import { useState, useCallback } from "react";
import { useSWRConfig } from "swr";
import { Formik } from "formik";
import { LLMProviderFormProps } from "@/interfaces/llm";
import * as Yup from "yup";
import { useWellKnownLLMProvider } from "@/hooks/useLLMProviders";
import {
  buildDefaultInitialValues,
  buildDefaultValidationSchema,
  buildAvailableModelConfigurations,
  buildOnboardingInitialValues,
} from "@/sections/modals/llmConfig/utils";
import {
  submitLLMProvider,
  submitOnboardingProvider,
} from "@/sections/modals/llmConfig/svc";
import {
  ModelsField,
  DisplayNameField,
  ModelsAccessField,
  FieldSeparator,
  SingleDefaultModelField,
  LLMConfigurationModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import { useField } from "formik";

const CLAUDE_CODE_CLI_PROVIDER_NAME = "claude_code_cli";
const DEFAULT_DEFAULT_MODEL_NAME = "claude-sonnet-4-6";

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
        setTestState({ status: "error", message: data.error || "Unknown error" });
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
              disabled={
                !tokenField.value || testState.status === "testing"
              }
            >
              {testState.status === "testing" ? "Testing..." : "Test Token"}
            </button>
            {testState.status === "success" && (
              <span className="text-sm text-green-700">
                Token validated successfully
              </span>
            )}
            {testState.status === "error" && (
              <span className="text-sm text-red-700">
                {testState.message}
              </span>
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
  open,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const [isTesting, setIsTesting] = useState(false);
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(
    CLAUDE_CODE_CLI_PROVIDER_NAME
  );

  if (open === false) return null;

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const existingCliPath =
    existingLlmProvider?.custom_config?.["cli_path"] ?? "";
  const existingAuthMode =
    existingLlmProvider?.custom_config?.["auth_mode"] ?? "api_key";
  const existingOAuthToken =
    existingLlmProvider?.custom_config?.["oauth_token"] ?? "";

  const initialValues = isOnboarding
    ? {
        ...buildOnboardingInitialValues(),
        name: CLAUDE_CODE_CLI_PROVIDER_NAME,
        provider: CLAUDE_CODE_CLI_PROVIDER_NAME,
        api_key: "",
        default_model_name: DEFAULT_DEFAULT_MODEL_NAME,
        custom_config_cli_path: "",
        custom_config_auth_mode: "api_key",
        custom_config_oauth_token: "",
      }
    : {
        ...buildDefaultInitialValues(
          existingLlmProvider,
          modelConfigurations,
          defaultModelName
        ),
        api_key: existingLlmProvider?.api_key ?? "",
        default_model_name:
          (defaultModelName &&
          modelConfigurations.some((m) => m.name === defaultModelName)
            ? defaultModelName
            : undefined) ??
          wellKnownLLMProvider?.recommended_default_model?.name ??
          DEFAULT_DEFAULT_MODEL_NAME,
        is_auto_mode: existingLlmProvider?.is_auto_mode ?? true,
        custom_config_cli_path: existingCliPath,
        custom_config_auth_mode: existingAuthMode,
        custom_config_oauth_token: existingOAuthToken,
      };

  const validationSchema = isOnboarding
    ? Yup.object().shape({
        default_model_name: Yup.string().required("Model name is required"),
      })
    : buildDefaultValidationSchema();

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      validateOnMount={true}
      onSubmit={async (values, { setSubmitting }) => {
        // Pack CLI path, auth_mode, and oauth_token into custom_config
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
        const submitValues = {
          ...values,
          custom_config: customConfig,
          // When OAuth mode, API key is not needed
          api_key:
            values.custom_config_auth_mode === "oauth"
              ? "not-required"
              : values.api_key || "not-required",
        };

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: CLAUDE_CODE_CLI_PROVIDER_NAME,
            payload: {
              ...submitValues,
              model_configurations: modelConfigsToUse,
              is_auto_mode:
                values.default_model_name === DEFAULT_DEFAULT_MODEL_NAME,
            },
            onboardingState,
            onboardingActions,
            isCustomProvider: false,
            onClose,
            setIsSubmitting: setSubmitting,
          });
        } else {
          await submitLLMProvider({
            providerName: CLAUDE_CODE_CLI_PROVIDER_NAME,
            values: submitValues,
            initialValues,
            modelConfigurations,
            existingLlmProvider,
            shouldMarkAsDefault,
            setIsTesting,
            mutate,
            onClose,
            setSubmitting,
          });
        }
      }}
    >
      {(formikProps) => (
        <LLMConfigurationModalWrapper
          providerEndpoint={CLAUDE_CODE_CLI_PROVIDER_NAME}
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isDirty={formikProps.dirty}
          isTesting={isTesting}
          isSubmitting={formikProps.isSubmitting}
        >
          <CLIPathField />

          <FieldSeparator />
          <AuthModeField />

          {!isOnboarding && (
            <>
              <FieldSeparator />
              <DisplayNameField disabled={!!existingLlmProvider} />
            </>
          )}

          <FieldSeparator />
          {isOnboarding ? (
            <SingleDefaultModelField placeholder="E.g. claude-sonnet-4-6" />
          ) : (
            <ModelsField
              modelConfigurations={modelConfigurations}
              formikProps={formikProps}
              recommendedDefaultModel={
                wellKnownLLMProvider?.recommended_default_model ?? null
              }
              shouldShowAutoUpdateToggle={true}
            />
          )}

          {!isOnboarding && (
            <>
              <FieldSeparator />
              <ModelsAccessField formikProps={formikProps} />
            </>
          )}
        </LLMConfigurationModalWrapper>
      )}
    </Formik>
  );
}
