import { AccessToken } from "livekit-server-sdk";

interface TokenRequest {
  roomName: string;
  userId: string;
  mode?: "create" | "conduct";
  interviewId?: string;
}

function ensureEnv(name: string) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not configured`);
  }
  return value;
}

export async function POST(request: Request) {
  const apiKey = ensureEnv("LIVEKIT_API_KEY");
  const apiSecret = ensureEnv("LIVEKIT_API_SECRET");
  const body = (await request.json()) as TokenRequest;

  if (!body.roomName || !body.userId) {
    return Response.json(
      { error: "roomName and userId are required" },
      { status: 400 }
    );
  }

  const token = new AccessToken(apiKey, apiSecret, {
    identity: body.userId,
    ttl: 60 * 30, // 30 minutes
  });

  token.addGrant({
    roomJoin: true,
    room: body.roomName,
    canPublish: true,
    canSubscribe: true,
  });

  token.metadata = JSON.stringify({
    userId: body.userId,
    mode: body.mode ?? "create",
    interviewId: body.interviewId,
  });

  return Response.json({ token: await token.toJwt() });
}
