"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Card,
  InputTypeIn,
  SelectCard,
  Switch,
  Text,
} from "@opal/components";
import {
  ConfirmationModalLayout,
  Content,
  ContentAction,
  InputHorizontal,
  toast,
} from "@opal/layouts";
import { SvgEdit, SvgPlus, SvgSettings, SvgTrash } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { refreshLlmProviderCaches } from "@/lib/languageModels/cache";
import {
  deleteVirtualModelProfile,
  saveVirtualModelProfile,
  setDefaultLlmModel,
  setVirtualModelProfilesEnabled,
} from "@/lib/languageModels/svc";
import type {
  LLMProviderView,
  ReasoningEffortOverride,
  VirtualModelProfile,
  VirtualModelProfilesResponse,
} from "@/lib/languageModels/types";
import ModelSelector from "@/sections/model-selector/ModelSelector";
import {
  ModelSettingsPopover,
  type ModelSettingsPatch,
} from "@/sections/modals/languageModels/ModelSettingsPopover";

interface ProfileFormModalProps {
  profile: VirtualModelProfile | null;
  providers: LLMProviderView[];
  onClose: () => void;
}

function ProfileFormModal({
  profile,
  providers,
  onClose,
}: ProfileFormModalProps) {
  const t = useTranslations("admin.languageModels.virtualProfiles");
  const tModelSelector = useTranslations("chat.modelSelector");
  const { mutate } = useSWRConfig();
  const [name, setName] = useState(profile?.name ?? "");
  const [targetId, setTargetId] = useState<number | null>(
    profile?.target_model_configuration_id ?? null
  );
  const [maxInputTokens, setMaxInputTokens] = useState(
    profile?.max_input_tokens?.toString() ?? ""
  );
  const [reasoningEffortMax, setReasoningEffortMax] =
    useState<ReasoningEffortOverride | null>(
      profile?.reasoning_effort_max ?? null
    );
  const [reasoningEffortDefault, setReasoningEffortDefault] =
    useState<ReasoningEffortOverride | null>(
      profile?.reasoning_effort_default ?? null
    );
  const [temperatureDefault, setTemperatureDefault] = useState<number | null>(
    profile?.temperature_default ?? null
  );
  const [saving, setSaving] = useState(false);
  const targetModel = providers
    .flatMap((provider) => provider.model_configurations)
    .find((model) => model.id === targetId);
  const contextOverride = maxInputTokens ? Number(maxInputTokens) : null;
  const contextIsValid =
    contextOverride === null ||
    (Number.isInteger(contextOverride) &&
      contextOverride > 0 &&
      (targetModel?.max_input_tokens === null ||
        targetModel?.max_input_tokens === undefined ||
        contextOverride <= targetModel.max_input_tokens));
  const settingsModel = targetModel
    ? {
        ...targetModel,
        max_input_tokens: contextOverride ?? targetModel.max_input_tokens,
        reasoning_effort_max:
          reasoningEffortMax ?? targetModel.reasoning_effort_max,
        reasoning_effort_default:
          reasoningEffortDefault ?? targetModel.reasoning_effort_default,
        temperature_default:
          temperatureDefault ?? targetModel.temperature_default,
      }
    : null;

  function updateSettings(patch: ModelSettingsPatch) {
    if (patch.reasoning_effort_max !== undefined) {
      setReasoningEffortMax(patch.reasoning_effort_max);
    }
    if (patch.reasoning_effort_default !== undefined) {
      setReasoningEffortDefault(patch.reasoning_effort_default);
    }
    if (patch.temperature_default !== undefined) {
      setTemperatureDefault(patch.temperature_default);
    }
  }

  function selectTarget(nextTargetId: number | null) {
    if (nextTargetId !== targetId) {
      setMaxInputTokens("");
      setReasoningEffortMax(null);
      setReasoningEffortDefault(null);
      setTemperatureDefault(null);
    }
    setTargetId(nextTargetId);
  }

  async function save() {
    if (!name.trim() || targetId === null || !contextIsValid) return;
    setSaving(true);
    try {
      await saveVirtualModelProfile(
        {
          name: name.trim(),
          target_model_configuration_id: targetId,
          max_input_tokens: contextOverride,
          reasoning_effort_max: reasoningEffortMax,
          reasoning_effort_default: reasoningEffortDefault,
          temperature_default: temperatureDefault,
        },
        profile?.model_configuration_id
      );
      await Promise.all([
        mutate(SWR_KEYS.virtualModelProfiles),
        refreshLlmProviderCaches(mutate),
      ]);
      toast.success(t("toasts.saved"));
      onClose();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.saveFailed")
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgSettings}
      title={profile ? t("form.editTitle") : t("form.createTitle")}
      onClose={saving ? undefined : onClose}
      submit={
        <Button
          disabled={
            saving || !name.trim() || targetId === null || !contextIsValid
          }
          onClick={() => void save()}
        >
          {t("form.saveButton")}
        </Button>
      }
    >
      <Section alignItems="stretch" gap={3}>
        <div className="flex flex-col gap-1">
          <Text font="secondary-action" color="text-03">
            {t("form.nameLabel")}
          </Text>
          <InputTypeIn
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("form.namePlaceholder")}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Text font="secondary-action" color="text-03">
            {t("form.targetLabel")}
          </Text>
          <div className="flex items-center gap-1">
            <div className="min-w-0 flex-1">
              <ModelSelector
                value={targetId}
                providerOptions={providers}
                includeHiddenModels={false}
                side="bottom"
                onChange={(option) =>
                  selectTarget(option.modelConfigurationId ?? null)
                }
              />
            </div>
            {settingsModel && (
              <ModelSettingsPopover
                model={settingsModel}
                onChange={updateSettings}
              />
            )}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <Text font="secondary-action" color="text-03">
            {tModelSelector("contextWindow.row.title")}
          </Text>
          <InputTypeIn
            value={maxInputTokens}
            onChange={(event) => setMaxInputTokens(event.target.value)}
            placeholder={targetModel?.max_input_tokens?.toString() ?? ""}
            type="number"
            min={1}
            max={targetModel?.max_input_tokens ?? undefined}
          />
          <Text font="secondary-body" color="text-02">
            {tModelSelector("contextWindow.row.caption")}
          </Text>
        </div>
      </Section>
    </ConfirmationModalLayout>
  );
}

interface VirtualModelProfilesPanelProps {
  providers: LLMProviderView[];
  settings: VirtualModelProfilesResponse;
}

export default function VirtualModelProfilesPanel({
  providers,
  settings,
}: VirtualModelProfilesPanelProps) {
  const t = useTranslations("admin.languageModels.virtualProfiles");
  const { mutate } = useSWRConfig();
  const [editingProfile, setEditingProfile] =
    useState<VirtualModelProfile | null>();
  const [deleteProfile, setDeleteProfile] =
    useState<VirtualModelProfile | null>(null);
  const [saving, setSaving] = useState(false);

  async function refresh() {
    await Promise.all([
      mutate(SWR_KEYS.virtualModelProfiles),
      mutate(SWR_KEYS.settings),
      refreshLlmProviderCaches(mutate),
    ]);
  }

  async function toggle(enabled: boolean) {
    setSaving(true);
    try {
      await setVirtualModelProfilesEnabled(enabled);
      await refresh();
      toast.success(enabled ? t("toasts.enabled") : t("toasts.disabled"));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.toggleFailed")
      );
    } finally {
      setSaving(false);
    }
  }

  async function makeDefault(profile: VirtualModelProfile) {
    setSaving(true);
    try {
      await setDefaultLlmModel(profile.provider_id, profile.model_name);
      await refresh();
      toast.success(t("toasts.defaultUpdated"));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.defaultFailed")
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!deleteProfile) return;
    setSaving(true);
    try {
      await deleteVirtualModelProfile(deleteProfile.model_configuration_id);
      await refresh();
      setDeleteProfile(null);
      toast.success(t("toasts.deleted"));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.deleteFailed")
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {editingProfile !== undefined && (
        <ProfileFormModal
          profile={editingProfile}
          providers={providers}
          onClose={() => setEditingProfile(undefined)}
        />
      )}
      {deleteProfile && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title={t("deleteModal.title", { name: deleteProfile.name })}
          onClose={saving ? undefined : () => setDeleteProfile(null)}
          submit={
            <Button
              variant="danger"
              disabled={saving}
              onClick={() => void remove()}
            >
              {t("deleteModal.submit")}
            </Button>
          }
        >
          <Text font="main-ui-body" color="text-03">
            {t("deleteModal.description")}
          </Text>
        </ConfirmationModalLayout>
      )}

      <Card border="solid" rounding={4}>
        <Section alignItems="stretch" gap={3}>
          <InputHorizontal
            title={t("title")}
            description={
              settings.enabled
                ? t("enabledDescription")
                : t("disabledDescription")
            }
            center
            withLabel
          >
            <Switch
              checked={settings.enabled}
              disabled={saving || settings.profiles.length === 0}
              onCheckedChange={(checked) => void toggle(checked)}
            />
          </InputHorizontal>

          <div className="flex items-center justify-between gap-3">
            <Content
              title={t("listTitle")}
              description={
                settings.profiles.length === 0
                  ? t("emptyDescription")
                  : undefined
              }
              sizePreset="main-ui"
              variant="section"
            />
            <Button
              icon={SvgPlus}
              disabled={providers.length === 0}
              onClick={() => setEditingProfile(null)}
            >
              {t("addButton")}
            </Button>
          </div>

          {settings.profiles.map((profile) => {
            const isDefault =
              profile.model_configuration_id ===
              settings.default_model_configuration_id;
            return (
              <SelectCard
                key={profile.model_configuration_id}
                state="filled"
                padding={2}
                rounding={4}
                onClick={() => setEditingProfile(profile)}
              >
                <ContentAction
                  icon={SvgSettings}
                  title={profile.name}
                  description={t("routesTo", {
                    provider: profile.target_provider_name,
                    model: profile.target_model_display_name,
                  })}
                  sizePreset="main-ui"
                  variant="section"
                  padding={2}
                  tag={
                    isDefault
                      ? { title: t("defaultTag"), color: "blue" }
                      : undefined
                  }
                  rightChildren={
                    <div className="flex items-center gap-1">
                      {settings.enabled && !isDefault && (
                        <Button
                          prominence="tertiary"
                          disabled={saving}
                          onClick={(event) => {
                            event.stopPropagation();
                            void makeDefault(profile);
                          }}
                        >
                          {t("setDefaultButton")}
                        </Button>
                      )}
                      <Button
                        icon={SvgEdit}
                        prominence="tertiary"
                        aria-label={t("editAria", { name: profile.name })}
                        onClick={(event) => {
                          event.stopPropagation();
                          setEditingProfile(profile);
                        }}
                      />
                      <Button
                        icon={SvgTrash}
                        prominence="tertiary"
                        disabled={isDefault}
                        aria-label={t("deleteAria", { name: profile.name })}
                        onClick={(event) => {
                          event.stopPropagation();
                          setDeleteProfile(profile);
                        }}
                      />
                    </div>
                  }
                />
              </SelectCard>
            );
          })}
        </Section>
      </Card>
    </>
  );
}
