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
  APIKeyField,
  ModelsField,
  DisplayNameField,
  ModelsAccessField,
  FieldSeparator,
  SingleDefaultModelField,
  LLMConfigurationModalWrapper,
} from "@/sections/modals/llmConfig/shared";

const CODEX_PROVIDER_NAME = "openai_codex";
const DEFAULT_DEFAULT_MODEL_NAME = "gpt-5.4";

type OAuthState =
  | { status: "idle" }
  | {
      status: "pending";
      userCode: string;
      verificationUri: string;
      deviceCode: string;
    }
  | {
      status: "authorized";
      accessToken: string;
      refreshToken: string | null;
      expiresAt: number;
    }
  | { status: "error"; message: string };

function OAuthSection({
  onTokenReceived,
}: {
  onTokenReceived: (
    accessToken: string,
    refreshToken: string | null,
    expiresAt: number,
    idToken?: string | null
  ) => void;
}) {
  const [oauthState, setOAuthState] = useState<OAuthState>({ status: "idle" });

  const startDeviceAuth = useCallback(async () => {
    try {
      const response = await fetch("/api/admin/llm/codex/device-auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!response.ok) throw new Error("Failed to start device auth");
      const data = await response.json();

      setOAuthState({
        status: "pending",
        userCode: data.user_code,
        verificationUri: data.verification_uri,
        deviceCode: data.device_code,
      });

      // Start polling
      const interval = (data.interval || 5) * 1000;
      const pollUntil = Date.now() + data.expires_in * 1000;

      const poll = async () => {
        if (Date.now() > pollUntil) {
          setOAuthState({
            status: "error",
            message: "Device code expired. Please try again.",
          });
          return;
        }
        try {
          const pollRes = await fetch(
            "/api/admin/llm/codex/device-auth/poll",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ device_code: data.device_code, user_code: data.user_code }),
            }
          );
          const pollData = await pollRes.json();

          if (pollData.status === "authorized") {
            const expiresAt =
              Math.floor(Date.now() / 1000) + pollData.expires_in;
            setOAuthState({
              status: "authorized",
              accessToken: pollData.access_token,
              refreshToken: pollData.refresh_token,
              expiresAt,
            });
            onTokenReceived(
              pollData.access_token,
              pollData.refresh_token,
              expiresAt,
              pollData.id_token
            );
            return;
          }
          if (pollData.status === "error") {
            setOAuthState({ status: "error", message: pollData.error });
            return;
          }
          // Still pending, continue polling
          setTimeout(poll, interval);
        } catch {
          setTimeout(poll, interval);
        }
      };

      setTimeout(poll, interval);
    } catch (e) {
      setOAuthState({
        status: "error",
        message: e instanceof Error ? e.message : "Unknown error",
      });
    }
  }, [onTokenReceived]);

  return (
    <div className="space-y-3">
      <label className="text-sm font-medium">Authentication</label>
      <p className="text-xs text-muted-foreground">
        Sign in with your ChatGPT account via OAuth, or provide an API key
        below.
      </p>

      {oauthState.status === "idle" && (
        <button
          type="button"
          className="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-md hover:bg-green-700"
          onClick={startDeviceAuth}
        >
          Sign in with ChatGPT
        </button>
      )}

      {oauthState.status === "pending" && (
        <div className="p-4 bg-muted rounded-md space-y-2">
          <p className="text-sm">
            Go to{" "}
            <a
              href={oauthState.verificationUri}
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-600 underline"
            >
              {oauthState.verificationUri}
            </a>{" "}
            and enter this code:
          </p>
          <p className="text-2xl font-mono font-bold text-center">
            {oauthState.userCode}
          </p>
          <p className="text-xs text-muted-foreground text-center">
            Waiting for authorization...
          </p>
        </div>
      )}

      {oauthState.status === "authorized" && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-md">
          <p className="text-sm text-green-700">
            Successfully authenticated with ChatGPT.
          </p>
        </div>
      )}

      {oauthState.status === "error" && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md space-y-2">
          <p className="text-sm text-red-700">{oauthState.message}</p>
          <button
            type="button"
            className="text-xs text-red-600 underline"
            onClick={startDeviceAuth}
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}

export default function CodexModal({
  variant = "llm-configuration",
  existingLlmProvider,
  shouldMarkAsDefault,
  onOpenChange,
  defaultModelName,
  onboardingState,
  onboardingActions,
  llmDescriptor,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const [isTesting, setIsTesting] = useState(false);
  const { mutate } = useSWRConfig();
  const { wellKnownLLMProvider } = useWellKnownLLMProvider(CODEX_PROVIDER_NAME);

  const onClose = () => onOpenChange?.(false);

  const modelConfigurations = buildAvailableModelConfigurations(
    existingLlmProvider,
    wellKnownLLMProvider ?? llmDescriptor
  );

  const initialValues = isOnboarding
    ? {
        ...buildOnboardingInitialValues(),
        name: CODEX_PROVIDER_NAME,
        provider: CODEX_PROVIDER_NAME,
        api_key: "",
        default_model_name: DEFAULT_DEFAULT_MODEL_NAME,
        codex_access_token: "",
        codex_refresh_token: "",
        codex_id_token: "",
        codex_token_expires_at: "",
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
        codex_access_token:
          existingLlmProvider?.custom_config?.["codex_access_token"] ?? "",
        codex_refresh_token:
          existingLlmProvider?.custom_config?.["codex_refresh_token"] ?? "",
        codex_id_token:
          existingLlmProvider?.custom_config?.["codex_id_token"] ?? "",
        codex_token_expires_at:
          existingLlmProvider?.custom_config?.["codex_token_expires_at"] ?? "",
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
        // Pack OAuth tokens into custom_config
        const customConfig: Record<string, string> = {};
        if (values.codex_access_token) {
          customConfig["codex_access_token"] = values.codex_access_token;
        }
        if (values.codex_refresh_token) {
          customConfig["codex_refresh_token"] = values.codex_refresh_token;
        }
        if (values.codex_id_token) {
          customConfig["codex_id_token"] = values.codex_id_token;
        }
        if (values.codex_token_expires_at) {
          customConfig["codex_token_expires_at"] =
            String(values.codex_token_expires_at);
        }
        const submitValues = {
          ...values,
          custom_config: customConfig,
          // Use OAuth token as api_key if no api_key provided
          api_key:
            values.api_key || values.codex_access_token || "not-required",
        };

        if (isOnboarding && onboardingState && onboardingActions) {
          const modelConfigsToUse =
            (wellKnownLLMProvider ?? llmDescriptor)?.known_models ?? [];

          await submitOnboardingProvider({
            providerName: CODEX_PROVIDER_NAME,
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
            providerName: CODEX_PROVIDER_NAME,
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
          providerEndpoint={CODEX_PROVIDER_NAME}
          existingProviderName={existingLlmProvider?.name}
          onClose={onClose}
          isFormValid={formikProps.isValid}
          isDirty={formikProps.dirty}
          isTesting={isTesting}
          isSubmitting={formikProps.isSubmitting}
        >
          <OAuthSection
            onTokenReceived={(accessToken, refreshToken, expiresAt, idToken) => {
              formikProps.setFieldValue("codex_access_token", accessToken);
              formikProps.setFieldValue(
                "codex_refresh_token",
                refreshToken ?? ""
              );
              formikProps.setFieldValue(
                "codex_id_token",
                idToken ?? ""
              );
              formikProps.setFieldValue(
                "codex_token_expires_at",
                String(expiresAt)
              );
            }}
          />

          <FieldSeparator />
          <APIKeyField providerName="OpenAI (optional, alternative to OAuth)" />

          {!isOnboarding && (
            <>
              <FieldSeparator />
              <DisplayNameField disabled={!!existingLlmProvider} />
            </>
          )}

          <FieldSeparator />
          {isOnboarding ? (
            <SingleDefaultModelField placeholder="E.g. gpt-5.4" />
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
