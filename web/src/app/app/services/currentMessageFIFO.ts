import {
  PacketType,
  sendMessage,
  SendMessageParams,
  resumeChatStream,
} from "./lib";
import { handleSSEStream } from "@/lib/search/streamingUtils";

export class CurrentMessageFIFO {
  private stack: PacketType[] = [];
  isComplete: boolean = false;
  error: string | null = null;

  push(packetBunch: PacketType) {
    this.stack.push(packetBunch);
  }

  nextPacket(): PacketType | undefined {
    return this.stack.shift();
  }

  isEmpty(): boolean {
    return this.stack.length === 0;
  }
}

export async function updateCurrentMessageFIFO(
  stack: CurrentMessageFIFO,
  params: SendMessageParams
) {
  try {
    for await (const packet of sendMessage(params)) {
      if (params.signal?.aborted) {
        throw new Error("AbortError");
      }
      stack.push(packet);
    }
  } catch (error: unknown) {
    if (error instanceof Error) {
      if (error.name === "AbortError") {
        console.debug("Stream aborted");
      } else {
        stack.error = error.message;
      }
    } else {
      stack.error = String(error);
    }
  } finally {
    stack.isComplete = true;
  }
}

/**
 * Attempt to resume a background inference stream for the given chat session.
 * Pushes packets into the FIFO just like ``updateCurrentMessageFIFO``.
 *
 * Returns ``true`` if a running inference was found and the stream was
 * consumed, ``false`` if no active inference exists (caller should just
 * show the persisted message from the DB).
 */
export async function resumeCurrentMessageFIFO(
  stack: CurrentMessageFIFO,
  chatSessionId: string,
  signal?: AbortSignal
): Promise<boolean> {
  try {
    const response = await resumeChatStream(chatSessionId, signal);
    if (!response) {
      // 204 — no active inference; answer is already in the DB.
      stack.isComplete = true;
      return false;
    }

    for await (const packet of handleSSEStream<PacketType>(response, signal)) {
      if (signal?.aborted) {
        throw new Error("AbortError");
      }
      stack.push(packet);
    }
    return true;
  } catch (error: unknown) {
    if (error instanceof Error) {
      if (error.name === "AbortError") {
        console.debug("Resume stream aborted");
      } else {
        stack.error = error.message;
      }
    } else {
      stack.error = String(error);
    }
    return false;
  } finally {
    stack.isComplete = true;
  }
}
