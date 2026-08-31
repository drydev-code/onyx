"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Button, Text } from "@opal/components";
import { InputDivider, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import {
  BaseLLMFormValues,
  buildValidationSchema,
  useInitialValues,
} from "@/sections/modals/languageModels/utils";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import {
  APIKeyField,
  DisplayNameField,
  ModalWrapper,
  ModelAccessField,
  ModelSelectionField,
} from "@/sections/modals/languageModels/shared";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";

interface CodexFormValues extends BaseLLMFormValues {
  codex_access_token: string;
  codex_refresh_token: string;
  codex_id_token: string;
  codex_token_expires_at: string;
}

interface DeviceAuthStartResponse {
  device_code: string;
  user_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
}

interface DeviceAuthPollResponse {
  status: "pending" | "authorized" | "error";
  access_token?: string;
  refresh_token?: string | null;
  id_token?: string | null;
  expires_in?: number;
  error?: string;
}

type OAuthState =
  | { status: "idle" }
  | {
      status: "pending";
      userCode: string;
      verificationUri: string;
    }
  | { status: "authorized" }
  | { status: "error"; message: string };

function hasCodexAuthentication(values: unknown): boolean {
  if (typeof values !== "object" || values === null) return false;
  return Boolean(
    Reflect.get(values, "api_key") || Reflect.get(values, "codex_access_token")
  );
}

function OAuthSection() {
  const t = useTranslations("admin.languageModels.modals.codex");
  const { setFieldValue } = useFormikContext<CodexFormValues>();
  const [oauthState, setOAuthState] = useState<OAuthState>({ status: "idle" });
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const stopPolling = useCallback(() => {
    if (pollTimeoutRef.current) {
      clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = null;
    }
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const storeTokens = useCallback(
    async (response: DeviceAuthPollResponse) => {
      const accessToken = response.access_token;
      if (!accessToken) {
        throw new Error(t("errors.missingAccessToken"));
      }
      const expiresAt =
        Math.floor(Date.now() / 1000) + (response.expires_in ?? 3600);
      await Promise.all([
        setFieldValue("codex_access_token", accessToken),
        setFieldValue("codex_refresh_token", response.refresh_token ?? ""),
        setFieldValue("codex_id_token", response.id_token ?? ""),
        setFieldValue("codex_token_expires_at", String(expiresAt)),
      ]);
    },
    [setFieldValue, t]
  );

  const startDeviceAuth = useCallback(async () => {
    stopPolling();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await fetch("/api/admin/llm/codex/device-auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(t("errors.startFailed"));
      const data = (await response.json()) as DeviceAuthStartResponse;
      const expiresAt = Date.now() + data.expires_in * 1000;
      const interval = Math.max(data.interval, 1) * 1000;

      setOAuthState({
        status: "pending",
        userCode: data.user_code,
        verificationUri: data.verification_uri,
      });

      const poll = async () => {
        if (Date.now() > expiresAt) {
          setOAuthState({ status: "error", message: t("errors.expired") });
          return;
        }

        try {
          const pollResponse = await fetch(
            "/api/admin/llm/codex/device-auth/poll",
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                device_code: data.device_code,
                user_code: data.user_code,
              }),
              signal: controller.signal,
            }
          );
          if (!pollResponse.ok) throw new Error(t("errors.pollFailed"));
          const pollData =
            (await pollResponse.json()) as DeviceAuthPollResponse;

          if (pollData.status === "authorized") {
            await storeTokens(pollData);
            setOAuthState({ status: "authorized" });
            stopPolling();
            return;
          }
          if (pollData.status === "error") {
            setOAuthState({
              status: "error",
              message: pollData.error || t("errors.pollFailed"),
            });
            stopPolling();
            return;
          }
        } catch (error) {
          if (controller.signal.aborted) return;
          if (Date.now() > expiresAt) {
            setOAuthState({
              status: "error",
              message: t("errors.expired"),
            });
            return;
          }
        }

        pollTimeoutRef.current = setTimeout(() => void poll(), interval);
      };

      pollTimeoutRef.current = setTimeout(() => void poll(), interval);
    } catch (error) {
      if (controller.signal.aborted) return;
      setOAuthState({
        status: "error",
        message: error instanceof Error ? error.message : t("errors.unknown"),
      });
    }
  }, [stopPolling, storeTokens, t]);

  return (
    <div className="flex flex-col gap-3 px-4">
      <Text font="main-ui-action">{t("authentication.title")}</Text>
      <Text font="secondary-body" color="text-03">
        {t("authentication.description")}
      </Text>

      {oauthState.status === "idle" && (
        <Button onClick={() => void startDeviceAuth()} width="fit">
          {t("signInButton.label")}
        </Button>
      )}

      {oauthState.status === "pending" && (
        <div className="flex flex-col gap-2 rounded-08 bg-background-tint-02 p-4">
          <Text font="secondary-body">{t("pending.instructions")}</Text>
          <a
            href={oauthState.verificationUri}
            target="_blank"
            rel="noopener noreferrer"
            className="text-action-link-05 underline"
          >
            {oauthState.verificationUri}
          </a>
          <Text font="secondary-body">{t("pending.codePrompt")}</Text>
          <Text font="heading-h2" color="text-04">
            {oauthState.userCode}
          </Text>
          <Text font="secondary-body" color="text-03">
            {t("pending.waiting")}
          </Text>
        </div>
      )}

      {oauthState.status === "authorized" && (
        <div className="rounded-08 bg-status-success-01 p-3">
          <Text font="secondary-body">{t("authorized.message")}</Text>
        </div>
      )}

      {oauthState.status === "error" && (
        <div className="flex flex-col gap-2 rounded-08 bg-status-error-01 p-3">
          <Text font="secondary-body">{oauthState.message}</Text>
          <Button
            prominence="tertiary"
            size="sm"
            onClick={() => void startDeviceAuth()}
            width="fit"
          >
            {t("tryAgainButton.label")}
          </Button>
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
  analyticsSource,
}: LLMProviderFormProps) {
  const t = useTranslations("admin.languageModels.modals");
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
      existingLlmProvider?.custom_config?.codex_access_token ?? "",
    codex_refresh_token:
      existingLlmProvider?.custom_config?.codex_refresh_token ?? "",
    codex_id_token: existingLlmProvider?.custom_config?.codex_id_token ?? "",
    codex_token_expires_at:
      existingLlmProvider?.custom_config?.codex_token_expires_at ?? "",
  };

  const validationSchema = buildValidationSchema(t, isOnboarding).test(
    "codex-auth",
    t("codex.validation.authenticationRequired"),
    hasCodexAuthentication
  );

  return (
    <ModalWrapper<CodexFormValues>
      providerName={LLMProviderName.OPENAI_CODEX}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const customConfig = {
          ...existingLlmProvider?.custom_config,
        };
        const tokenValues = {
          codex_access_token: values.codex_access_token,
          codex_refresh_token: values.codex_refresh_token,
          codex_id_token: values.codex_id_token,
          codex_token_expires_at: values.codex_token_expires_at,
        };
        Object.entries(tokenValues).forEach(([key, value]) => {
          if (value) customConfig[key] = value;
          else delete customConfig[key];
        });

        const submitValues: CodexFormValues = {
          ...values,
          custom_config: customConfig,
          api_key:
            values.api_key || values.codex_access_token || "not-required",
        };

        await submitProvider<CodexFormValues>({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
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
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <OAuthSection />

      <InputDivider />
      <APIKeyField providerName="OpenAI" optional />

      {!isOnboarding && (
        <>
          <InputDivider />
          <DisplayNameField disabled={!!existingLlmProvider} />
        </>
      )}

      <InputDivider />
      <ModelSelectionField shouldShowAutoUpdateToggle={true} />

      {!isOnboarding && (
        <>
          <InputDivider />
          <ModelAccessField />
        </>
      )}
    </ModalWrapper>
  );
}
