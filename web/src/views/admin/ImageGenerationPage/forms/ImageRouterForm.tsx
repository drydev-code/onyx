"use client";

import React, { useMemo } from "react";
import { useTranslations } from "next-intl";
import { InputTypeIn, PasswordInputTypeIn } from "@opal/components";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { ImageGenFormWrapper } from "@/views/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/views/admin/ImageGenerationPage/forms/types";
import { ImageGenerationCredentials } from "@/views/admin/ImageGenerationPage/svc";
import { ImageProvider } from "@/views/admin/ImageGenerationPage/constants";

interface ImageRouterFormValues {
  api_key: string;
  model_name: string;
}

const initialValues: ImageRouterFormValues = {
  api_key: "",
  model_name: "",
};

function ImageRouterFormFields(
  props: ImageGenFormChildProps<ImageRouterFormValues>
) {
  const t = useTranslations("admin.imageGeneration");
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
    disabled,
    isLoadingCredentials,
    apiKeyOptions,
    resetApiState,
    imageProvider,
  } = props;

  return (
    <>
      <FormikField<string>
        name="model_name"
        render={(field, helper, meta, state) => (
          <FormField name="model_name" state={state} className="w-full">
            <FormField.Label>{t("form.modelName.label")}</FormField.Label>
            <FormField.Control>
              <InputTypeIn
                {...field}
                onChange={(event) => {
                  helper.setValue(event.target.value);
                  resetApiState();
                }}
                placeholder={t("form.modelName.placeholder")}
                variant={disabled ? "disabled" : undefined}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: t("form.modelName.idle"),
                error: meta.error,
              }}
            />
          </FormField>
        )}
      />
      <FormikField<string>
        name="api_key"
        render={(field, helper, meta, state) => (
          <FormField
            name="api_key"
            state={apiStatus === "error" ? "error" : state}
            className="w-full"
          >
            <FormField.Label>{t("form.apiKey.label")}</FormField.Label>
            <FormField.Control>
              {apiKeyOptions.length > 0 ? (
                <InputComboBox
                  value={field.value}
                  onChange={(event) => {
                    helper.setValue(event.target.value);
                    resetApiState();
                  }}
                  onValueChange={(value) => {
                    helper.setValue(value);
                    resetApiState();
                  }}
                  onBlur={field.onBlur}
                  options={apiKeyOptions}
                  placeholder={
                    isLoadingCredentials
                      ? t("form.loading.placeholder")
                      : t("form.apiKey.comboPlaceholder")
                  }
                  disabled={disabled}
                  isError={apiStatus === "error"}
                />
              ) : (
                <PasswordInputTypeIn
                  {...field}
                  onChange={(event) => {
                    field.onChange(event);
                    resetApiState();
                  }}
                  placeholder={
                    isLoadingCredentials
                      ? t("form.loading.placeholder")
                      : t("form.apiKey.placeholder")
                  }
                  disabled={disabled}
                  error={apiStatus === "error"}
                />
              )}
            </FormField.Control>
            {showApiMessage ? (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: t("form.apiKeyTest.loading", {
                    title: imageProvider.title,
                  }),
                  success: t("form.apiKeyTest.success"),
                  error: errorMessage || t("form.apiKeyTest.error"),
                }}
              />
            ) : (
              <FormField.Message
                messages={{
                  idle: t("form.apiKey.idle"),
                  error: meta.error,
                }}
              />
            )}
          </FormField>
        )}
      />
    </>
  );
}

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  imageProvider: ImageProvider
): Partial<ImageRouterFormValues> {
  return {
    api_key: credentials.api_key || "",
    model_name: imageProvider.model_name || "",
  };
}

function transformValues(
  values: ImageRouterFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  const modelName = values.model_name.trim();
  const safeId = modelName.replace(/[^a-zA-Z0-9_-]/g, "_");
  return {
    modelName,
    imageProviderId:
      imageProvider.image_provider_id === "imagerouter_custom"
        ? `imagerouter_${safeId}`
        : imageProvider.image_provider_id,
    provider: "imagerouter",
    apiKey: values.api_key,
  };
}

export function ImageRouterForm(props: ImageGenFormBaseProps) {
  const t = useTranslations("admin.imageGeneration");
  const { imageProvider, existingConfig } = props;

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        api_key: Yup.string().required(t("form.apiKey.required")),
        model_name: Yup.string().trim().required(t("form.modelName.required")),
      }),
    [t]
  );

  return (
    <ImageGenFormWrapper<ImageRouterFormValues>
      {...props}
      title={
        existingConfig
          ? t("form.editHeader.title", { title: imageProvider.title })
          : t("form.connectHeader.title", { title: imageProvider.title })
      }
      description={t(imageProvider.descriptionKey)}
      initialValues={initialValues}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={(values) => transformValues(values, imageProvider)}
    >
      {(childProps) => <ImageRouterFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
