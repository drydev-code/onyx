"use client";

import React from "react";
import * as Yup from "yup";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { ImageGenFormWrapper } from "@/refresh-pages/admin/ImageGenerationPage/forms/ImageGenFormWrapper";
import {
  ImageGenFormBaseProps,
  ImageGenFormChildProps,
  ImageGenSubmitPayload,
} from "@/refresh-pages/admin/ImageGenerationPage/forms/types";
import { ImageGenerationCredentials } from "@/refresh-pages/admin/ImageGenerationPage/svc";
import { ImageProvider } from "@/refresh-pages/admin/ImageGenerationPage/constants";

interface ImageRouterFormValues {
  api_key: string;
  model_name: string;
}

const initialValues: ImageRouterFormValues = {
  api_key: "",
  model_name: "",
};

const validationSchema = Yup.object().shape({
  api_key: Yup.string().required("API Key is required"),
  model_name: Yup.string().required("Model name is required"),
});

function ImageRouterFormFields(
  props: ImageGenFormChildProps<ImageRouterFormValues>
) {
  const {
    apiStatus,
    showApiMessage,
    errorMessage,
    disabled,
    isLoadingCredentials,
    resetApiState,
    imageProvider,
  } = props;

  return (
    <>
      <FormikField<string>
        name="model_name"
        render={(field, helper, meta, state) => (
          <FormField name="model_name" state={state} className="w-full">
            <FormField.Label>Model Name</FormField.Label>
            <FormField.Control>
              <input
                type="text"
                className="w-full border rounded-md px-3 py-2 text-sm"
                {...field}
                onChange={(e) => {
                  field.onChange(e);
                  resetApiState();
                }}
                placeholder="e.g. flux-schnell, flux-dev, stable-diffusion-xl"
                disabled={disabled}
              />
            </FormField.Control>
            <FormField.Message
              messages={{
                idle: "Enter any model name supported by imagerouter.co",
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
            <FormField.Label>ImageRouter API Key</FormField.Label>
            <FormField.Control>
              <PasswordInputTypeIn
                {...field}
                onChange={(e) => {
                  field.onChange(e);
                  resetApiState();
                }}
                placeholder={
                  isLoadingCredentials
                    ? "Loading..."
                    : "Enter your ImageRouter API key"
                }
                showClearButton={false}
                disabled={disabled}
                error={apiStatus === "error"}
              />
            </FormField.Control>
            {showApiMessage ? (
              <FormField.APIMessage
                state={apiStatus}
                messages={{
                  loading: `Testing API key with ${imageProvider.title}...`,
                  success: "API key is valid. Configuration saved.",
                  error: errorMessage || "Invalid API key",
                }}
              />
            ) : (
              <FormField.Message
                messages={{
                  idle: "Get your API key from imagerouter.co",
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
    model_name: credentials.model_name || imageProvider.model_name || "",
  };
}

function transformValues(
  values: ImageRouterFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  // Use the user-provided model name, generating a stable provider ID from it
  const modelName = values.model_name.trim();
  const safeId = modelName.replace(/[^a-zA-Z0-9_-]/g, "_");
  return {
    modelName,
    imageProviderId: imageProvider.image_provider_id === "imagerouter_custom"
      ? `imagerouter_${safeId}`
      : imageProvider.image_provider_id,
    provider: "imagerouter",
    apiKey: values.api_key,
  };
}

export function ImageRouterForm(props: ImageGenFormBaseProps) {
  const { imageProvider, existingConfig } = props;

  return (
    <ImageGenFormWrapper<ImageRouterFormValues>
      {...props}
      title={
        existingConfig
          ? `Edit ${imageProvider.title}`
          : `Connect ${imageProvider.title}`
      }
      description={imageProvider.description}
      initialValues={initialValues}
      validationSchema={validationSchema}
      getInitialValuesFromCredentials={getInitialValuesFromCredentials}
      transformValues={(values) => transformValues(values, imageProvider)}
    >
      {(childProps) => <ImageRouterFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
