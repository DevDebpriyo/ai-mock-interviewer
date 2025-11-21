"use client";

import "@livekit/components-styles";
import {
  LiveKitRoom,
  RoomAudioRenderer,
  ControlBar,
} from "@livekit/components-react";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";

interface LiveKitAgentProps {
  userId: string;
  userName: string;
  mode: "create" | "conduct";
  roomName: string;
  interviewId?: string;
}

const Agent = ({
  userId,
  userName,
  mode,
  roomName,
  interviewId,
}: LiveKitAgentProps) => {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "connecting" | "connected">(
    "idle"
  );
  const [error, setError] = useState<string | null>(null);
  const livekitUrl =
    process.env.NEXT_PUBLIC_LIVEKIT_WS_URL ??
    process.env.NEXT_PUBLIC_LIVEKIT_URL ??
    process.env.LIVEKIT_URL;

  useEffect(() => {
    setError(null);
  }, [mode, interviewId, roomName]);

  const handleDisconnected = useCallback(() => {
    setToken(null);
    setStatus("idle");
    router.push("/");
  }, [router]);

  const startConversation = async () => {
    setStatus("connecting");
    try {
      const response = await fetch("/api/livekit/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roomName, userId, mode, interviewId }),
      });

      if (!response.ok) {
        const body = await response.json();
        throw new Error(body.error || "Unable to get LiveKit token");
      }

      const { token } = await response.json();
      setToken(token);
      setStatus("connected");
    } catch (err) {
      console.error(err);
      setError(err instanceof Error ? err.message : "Unable to start session");
      setStatus("idle");
    }
  };

  if (!livekitUrl) {
    return (
      <p className="text-destructive">
        Missing LiveKit websocket URL. Set NEXT_PUBLIC_LIVEKIT_WS_URL (or
        NEXT_PUBLIC_LIVEKIT_URL) in your environment variables.
      </p>
    );
  }

  return (
    <div className="card-border w-full">
      <div className="card flex flex-col gap-6 p-6">
        <div className="flex flex-col gap-1">
          <h3 className="text-xl font-semibold">
            {userName}, you&apos;re live with Prepwise
          </h3>
          <p className="text-light-100">
            Mode: <span className="font-semibold capitalize">{mode}</span>
          </p>
        </div>

        {!token && (
          <div className="flex flex-col gap-3">
            <Button
              className="btn-primary"
              onClick={startConversation}
              disabled={status === "connecting"}
            >
              {status === "connecting" ? "Connecting..." : "Start Session"}
            </Button>
            {error && <p className="text-destructive text-sm">{error}</p>}
          </div>
        )}

        {token && (
          <LiveKitRoom
            audio
            video={false}
            serverUrl={livekitUrl}
            token={token}
            connect
            onDisconnected={handleDisconnected}
            data-lk-theme="default"
            className="w-full"
          >
            <RoomAudioRenderer />
            <ControlBar controls={{ leave: true }} />
          </LiveKitRoom>
        )}
      </div>
    </div>
  );
};

export default Agent;
