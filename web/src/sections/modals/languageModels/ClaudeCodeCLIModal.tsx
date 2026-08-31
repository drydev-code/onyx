"use client";

import { useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { InputDivider, InputPadder, InputVertical, toast } from "@opal/layouts";
import {
  LLMProviderFormProps,
  LLMProviderName,
} from "@/lib/languageModels/types";
import { LLMProviderConfiguredSource } from "@/lib/analytics/utils";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import {
  APIKeyField,
  DisplayNameField,
  ModalWrapper,
  ModelAccessField,
  ModelSelectionField,
} from "@/sections/modals/languageModels/shared";
import { submitProvider } from "@/sections/modals/languageModels/svc";
import {
  BaseLLMFormValues,
  buildValidationSchema,
  useInitialValues,
} from "@/sections/modals/languageModels/utils";

const AUTH_MODE_API_KEY = "api_key";
const AUTH_MODE_OAUTH = "oauth";

function hasClaudeCodeAuthentication(values: unknown): boolean {
  if (typeof values !== "object" || values === null) return false;
  const authMode = Reflect.get(values, "custom_config_auth_mode");
  return authMode === AUTH_MODE_OAUTH
    ? Boolean(Reflect.get(values, "custom_config_oauth_token"))
    : Boolean(Reflect.get(values, "api_key"));
}

interface ClaudeCodeCLIFormValues extends BaseLLMFormValues {
  custom_config_cli_path: string;
  custom_config_auth_mode: string;
  custom_config_oauth_token: string;
}

function CLIPathField() {
  const t = useTranslations("admin.languageModels.modals.claudeCode");

  return (
    <InputPadder>
      <InputVertical
        withLabel="custom_config_cli_path"
        title={t("cliPath.title")}
        subDescription={t("cliPath.description")}
      >
        <InputTypeInField
          name="custom_config_cli_path"
          aria-label={t("cliPath.title")}
          placeholder={t("cliPath.placeholder")}
        />
      </InputVertical>
    </InputPadder>
  );
}

function AuthenticationFields() {
  const t = useTranslations("admin.languageModels.modals.claudeCode");
  const { values } = useFormikContext<ClaudeCodeCLIFormValues>();
  const isOAuth = values.custom_config_auth_mode === AUTH_MODE_OAUTH;

  return (
    <>
      <InputPadder>
        <InputVertical
          withLabel="custom_config_auth_mode"
          title={t("authMode.title")}
          subDescription={t("authMode.description")}
        >
          <InputSelectField name="custom_config_auth_mode">
            <InputSelect.Trigger aria-label={t("authMode.title")} />
            <InputSelect.Content>
              <InputSelect.Item value={AUTH_MODE_API_KEY}>
                {t("authMode.apiKey")}
              </InputSelect.Item>
              <InputSelect.Item value={AUTH_MODE_OAUTH}>
                {t("authMode.oauth")}
              </InputSelect.Item>
            </InputSelect.Content>
          </InputSelectField>
        </InputVertical>
      </InputPadder>

      <InputDivider />

      {isOAuth ? (
        <InputPadder>
          <InputVertical
            withLabel="custom_config_oauth_token"
            title={t("oauthToken.title")}
            subDescription={t("oauthToken.description")}
          >
            <PasswordInputTypeInField
              name="custom_config_oauth_token"
              aria-label={t("oauthToken.title")}
              placeholder={t("oauthToken.placeholder")}
            />
          </InputVertical>
        </InputPadder>
      ) : (
        <APIKeyField providerName="Anthropic" />
      )}
    </>
  );
}

export default function ClaudeCodeCLIModal({
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
    LLMProviderName.CLAUDE_CODE_CLI,
    existingLlmProvider
  );
  const initialValues: ClaudeCodeCLIFormValues = {
    ...baseInitialValues,
    api_key: existingLlmProvider?.api_key ?? "",
    custom_config_cli_path: existingLlmProvider?.custom_config?.cli_path ?? "",
    custom_config_auth_mode:
      existingLlmProvider?.custom_config?.auth_mode ?? AUTH_MODE_API_KEY,
    custom_config_oauth_token:
      existingLlmProvider?.custom_config?.oauth_token ?? "",
  };

  const validationSchema = buildValidationSchema(t, isOnboarding).test(
    "claude-code-auth",
    t("claudeCode.validation.authenticationRequired"),
    hasClaudeCodeAuthentication
  );

  return (
    <ModalWrapper<ClaudeCodeCLIFormValues>
      providerName={LLMProviderName.CLAUDE_CODE_CLI}
      llmProvider={existingLlmProvider}
      onClose={onClose}
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values, { setSubmitting, setStatus }) => {
        const customConfig = {
          ...existingLlmProvider?.custom_config,
        };
        const cliPath = values.custom_config_cli_path.trim();
        if (cliPath) customConfig.cli_path = cliPath;
        else delete customConfig.cli_path;

        customConfig.auth_mode = values.custom_config_auth_mode;
        delete customConfig.claude_code_disable_builtin_tools;
        if (
          values.custom_config_auth_mode === AUTH_MODE_OAUTH &&
          values.custom_config_oauth_token
        ) {
          customConfig.oauth_token = values.custom_config_oauth_token;
        } else {
          delete customConfig.oauth_token;
        }

        const submitValues: ClaudeCodeCLIFormValues = {
          ...values,
          custom_config: customConfig,
          api_key:
            values.custom_config_auth_mode === AUTH_MODE_OAUTH
              ? "not-required"
              : values.api_key,
        };

        await submitProvider<ClaudeCodeCLIFormValues>({
          t,
          analyticsSource:
            analyticsSource ??
            (isOnboarding
              ? LLMProviderConfiguredSource.CHAT_ONBOARDING
              : LLMProviderConfiguredSource.ADMIN_PAGE),
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
                  ? t("toasts.providerUpdated")
                  : t("toasts.providerEnabled")
              );
            }
          },
        });
      }}
    >
      <CLIPathField />

      <InputDivider />
      <AuthenticationFields />

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
