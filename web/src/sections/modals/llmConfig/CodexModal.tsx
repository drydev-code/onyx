"use client";

import { useState, useCallback } from "react";
import { useSWRConfig } from "swr";
import { useFormikContext } from "formik";
import { LLMProviderFormProps, LLMProviderName } from "@/interfaces/llm";
import {
  useInitialValues,
  buildValidationSchema,
  BaseLLMFormValues,
} from "@/sections/modals/llmConfig/utils";
import { submitProvider } from "@/sections/modals/llmConfig/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics";
import {
  APIKeyField,
  ModelSelectionField,
  DisplayNameField,
  ModelAccessField,
  ModalWrapper,
} from "@/sections/modals/llmConfig/shared";
import * as InputLayouts from "@/layouts/input-layouts";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { toast } from "@/hooks/useToast";

interface CodexFormValues extends BaseLLMFormValues {
  codex_access_token: string;
  codex_refresh_token: string;
  codex_id_token: string;
  codex_token_expires_at: string;
}

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

/**
 * OAuth device-flow section. Rendered inside Formik context so it can
 * write token values directly via useFormikContext.
 */
function OAuthSection() {
  const { setFieldValue } = useFormikContext<CodexFormValues>();
  const [oauthState, setOAuthState] = useState<OAuthState>({ status: "idle" });

  const onTokenReceived = useCallback(
    (
      accessToken: string,
      refreshToken: string | null,
      expiresAt: number,
      idToken?: string | null
    ) => {
      setFieldValue("codex_access_token", accessToken);
      setFieldValue("codex_refresh_token", refreshToken ?? "");
      setFieldValue("codex_id_token", idToken ?? "");
      setFieldValue("codex_token_expires_at", String(expiresAt));
    },
    [setFieldValue]
  );

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
              body: JSON.stringify({
                device_code: data.device_code,
                user_code: data.user_code,
              }),
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
  onSuccess,
}: LLMProviderFormProps) {
  const isOnboarding = variant === "onboarding";
  const { mutate } = useSWRConfig();

  const onClose = () => onOpenChange?.(false);

  const baseInitialValues = useInitialValues(
    isOnboarding,
    LLMProviderName.OPENAI_CODEX,
    existingLlmProvider
  );

  const initialValues: CodexFormValues = {
    ...baseInitialValues,
    api_key: existingLlmProvider?.api_key ?? "",
    codex_access_token:
      existingLlmProvider?.custom_config?.["codex_access_token"] ?? "",
    codex_refresh_token:
      existingLlmProvider?.custom_config?.["codex_refresh_token"] ?? "",
    codex_id_token:
      existingLlmProvider?.custom_config?.["codex_id_token"] ?? "",
    codex_token_expires_at:
      existingLlmProvider?.custom_config?.["codex_token_expires_at"] ?? "",
  };

  const validationSchema = buildValidationSchema(isOnboarding);

  return (
    <ModalWrapper<CodexFormValues>
      providerName={LLMProviderName.OPENAI_CODEX}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
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
          customConfig["codex_token_expires_at"] = String(
            values.codex_token_expires_at
          );
        }

        const submitValues: CodexFormValues = {
          ...values,
          custom_config: customConfig,
          api_key:
            values.api_key || values.codex_access_token || "not-required",
        };

        await submitProvider<CodexFormValues>({
          analyticsSource: isOnboarding
            ? LLMProviderConfiguredSource.CHAT_ONBOARDING
            : LLMProviderConfiguredSource.ADMIN_PAGE,
          providerName: LLMProviderName.OPENAI_CODEX,
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
      <OAuthSection />

      <InputLayouts.FieldSeparator />
      <APIKeyField providerName="OpenAI (optional, alternative to OAuth)" />

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
