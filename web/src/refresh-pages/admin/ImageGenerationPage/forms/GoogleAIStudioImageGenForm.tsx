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

interface GoogleAIStudioFormValues {
  api_key: string;
}

const initialValues: GoogleAIStudioFormValues = {
  api_key: "",
};

const validationSchema = Yup.object().shape({
  api_key: Yup.string().required("API Key is required"),
});

function GoogleAIStudioFormFields(
  props: ImageGenFormChildProps<GoogleAIStudioFormValues>
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
    <FormikField<string>
      name="api_key"
      render={(field, helper, meta, state) => (
        <FormField
          name="api_key"
          state={apiStatus === "error" ? "error" : state}
          className="w-full"
        >
          <FormField.Label>Google AI Studio API Key</FormField.Label>
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
                  : "Enter your Google AI Studio API key"
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
                idle: "Get your API key from aistudio.google.com",
                error: meta.error,
              }}
            />
          )}
        </FormField>
      )}
    />
  );
}

function getInitialValuesFromCredentials(
  credentials: ImageGenerationCredentials,
  _imageProvider: ImageProvider
): Partial<GoogleAIStudioFormValues> {
  return {
    api_key: credentials.api_key || "",
  };
}

function transformValues(
  values: GoogleAIStudioFormValues,
  imageProvider: ImageProvider
): ImageGenSubmitPayload {
  return {
    modelName: imageProvider.model_name,
    imageProviderId: imageProvider.image_provider_id,
    provider: "google_ai_studio",
    apiKey: values.api_key,
  };
}

export function GoogleAIStudioImageGenForm(props: ImageGenFormBaseProps) {
  const { imageProvider, existingConfig } = props;

  return (
    <ImageGenFormWrapper<GoogleAIStudioFormValues>
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
      {(childProps) => <GoogleAIStudioFormFields {...childProps} />}
    </ImageGenFormWrapper>
  );
}
