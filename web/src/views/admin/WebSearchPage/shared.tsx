"use client";

import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import InputSelectField from "@/refresh-components/form/InputSelectField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";

interface ApiKeyFieldProps {
  providerLabel: string;
  apiKeyUrl?: string;
}

export function ApiKeyField({ providerLabel, apiKeyUrl }: ApiKeyFieldProps) {
  const t = useTranslations("admin.webSearch");

  return (
    <InputVertical
      title={t("apiKeyField.title")}
      withLabel="api_key"
      subDescription={markdown(
        apiKeyUrl
          ? t("apiKeyField.withLink.description", {
              url: apiKeyUrl,
              provider: providerLabel,
            })
          : t("apiKeyField.noLink.description", { provider: providerLabel })
      )}
    >
      <PasswordInputTypeInField
        name="api_key"
        placeholder={t("apiKeyField.placeholder")}
      />
    </InputVertical>
  );
}

interface ConfigTextFieldProps {
  title: string;
  placeholder: string;
  subDescription?: string | RichStr;
  options?: ReadonlyArray<{
    value: string;
    label: string;
    description?: string;
  }>;
}

export function ConfigTextField({
  title,
  placeholder,
  subDescription,
  options,
}: ConfigTextFieldProps) {
  return (
    <InputVertical
      title={title}
      withLabel="config"
      subDescription={subDescription}
    >
      {options ? (
        <InputSelectField name="config">
          <InputSelect.Trigger placeholder={placeholder} />
          <InputSelect.Content>
            {options.map((option) => (
              <InputSelect.Item
                key={option.value}
                value={option.value}
                description={option.description}
              >
                {option.label}
              </InputSelect.Item>
            ))}
          </InputSelect.Content>
        </InputSelectField>
      ) : (
        <InputTypeInField name="config" placeholder={placeholder} />
      )}
    </InputVertical>
  );
}
