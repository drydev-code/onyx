import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { SvgUsers } from "@opal/icons";

import {
  CollaborationEvent,
  CollaborationPacket,
  PacketType,
} from "@/app/app/services/streamingModels";
import {
  FullChatState,
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";

interface AgentView {
  key: string;
  prompt: string;
  status: string;
  message: string | null;
}

function isComplete(status: string): boolean {
  return status.toLowerCase() === "completed";
}

function buildAgentViews(packets: CollaborationPacket[]): AgentView[] {
  const events = packets
    .filter((packet) => packet.obj.type === PacketType.COLLABORATION_EVENT)
    .map((packet) => packet.obj as CollaborationEvent);
  const promptsByItem = new Map<string, string>();
  const receiverIdsByItem = new Map<string, string[]>();
  const promptByReceiverId = new Map<string, string>();
  const agents = new Map<string, AgentView>();

  for (const event of events) {
    if (event.prompt) promptsByItem.set(event.item_id, event.prompt);
    if (event.receiver_thread_ids.length > 0) {
      receiverIdsByItem.set(event.item_id, event.receiver_thread_ids);
    }

    const prompt = promptsByItem.get(event.item_id) ?? "";
    for (const receiverId of event.receiver_thread_ids) {
      if (prompt) promptByReceiverId.set(receiverId, prompt);
      const current = agents.get(receiverId);
      agents.set(receiverId, {
        key: receiverId,
        prompt: current?.prompt || prompt,
        status: current?.status || event.status,
        message: current?.message ?? null,
      });
    }

    for (const [receiverId, state] of Object.entries(event.agents_states)) {
      const current = agents.get(receiverId);
      agents.set(receiverId, {
        key: receiverId,
        prompt: current?.prompt || promptByReceiverId.get(receiverId) || prompt,
        status: state.status,
        message: state.message ?? current?.message ?? null,
      });
    }
  }

  for (const event of events) {
    if (
      event.tool === "spawn_agent" &&
      event.prompt &&
      !(receiverIdsByItem.get(event.item_id)?.length ?? 0)
    ) {
      const key = `pending:${event.item_id}`;
      agents.set(key, {
        key,
        prompt: event.prompt,
        status: event.status,
        message: null,
      });
    }
  }

  return Array.from(agents.values());
}

export const CollaborationRenderer: MessageRenderer<
  CollaborationPacket,
  FullChatState
> = ({ packets, renderType, children }) => {
  const t = useTranslations("chat.messages.timeline");
  const agents = useMemo(() => buildAgentViews(packets), [packets]);
  const completedCount = agents.filter((agent) =>
    isComplete(agent.status)
  ).length;
  const isCompact =
    renderType === RenderType.COMPACT || renderType === RenderType.HIGHLIGHT;
  const header = t("collaboration.header", {
    completed: completedCount,
    total: agents.length,
  });

  const content = isCompact ? (
    <div className="ps-[var(--timeline-common-text-padding)]">
      <Text as="p" font="main-ui-muted" color="text-03">
        {completedCount === agents.length && agents.length > 0
          ? t("collaboration.completeHint")
          : t("collaboration.working")}
      </Text>
    </div>
  ) : (
    <div className="flex flex-col gap-3 ps-[var(--timeline-common-text-padding)]">
      {agents.map((agent, index) => (
        <div
          key={agent.key}
          className="flex flex-col gap-3 rounded-lg border border-border-02 bg-background-neutral-01 p-3"
        >
          <div className="flex items-center justify-between gap-3">
            <Text as="p" font="main-ui-action" color="text-02">
              {t("collaboration.agent", { index: index + 1 })}
            </Text>
            <Text as="p" font="secondary-body" color="text-04">
              {agent.status.replaceAll("_", " ")}
            </Text>
          </div>

          {agent.prompt && (
            <div className="flex flex-col gap-1">
              <Text as="p" font="secondary-action" color="text-04">
                {t("collaboration.task")}
              </Text>
              <Text as="p" font="main-ui-body" color="text-02">
                {agent.prompt}
              </Text>
            </div>
          )}

          <div className="flex flex-col gap-1">
            <Text as="p" font="secondary-action" color="text-04">
              {t("collaboration.output")}
            </Text>
            {agent.message ? (
              <MinimalMarkdown
                content={agent.message}
                className="text-text-02"
              />
            ) : (
              <Text as="p" font="main-ui-muted" color="text-03">
                {t("collaboration.waiting")}
              </Text>
            )}
          </div>
        </div>
      ))}
    </div>
  );

  return children([
    {
      icon: SvgUsers,
      status: header,
      content,
      supportsCollapsible: true,
      alwaysCollapsible: true,
      noPaddingRight: true,
    },
  ]);
};
