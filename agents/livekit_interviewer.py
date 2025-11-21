"""LiveKit-powered voice agent for Prepwise mock interviews."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore, initialize_app
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RunContext,
    cli,
    metrics,
    room_io,
)
from livekit.agents.llm import function_tool
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

# Uncomment to enable Krisp noise cancellation
# from livekit.plugins import noise_cancellation

# Load environment variables from .env.local first (Next.js convention), then fall back to .env
load_dotenv(dotenv_path=os.path.abspath(".env.local"), override=True)
load_dotenv()
logger = logging.getLogger("prepwise-livekit-agent")
logging.basicConfig(level=logging.INFO)

LIVEKIT_AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "Prepwise Coach")


@dataclass
class SessionState:
    """Mutable state scoped to a single LiveKit session."""

    mode: str = "create"  # "create" | "conduct"
    interview_id: Optional[str] = None
    user_id: Optional[str] = None
    metadata_complete: bool = False
    questions_generated: bool = False
    current_question_index: int = 0
    question_list: List[str] = field(default_factory=list)


def _init_firestore() -> firestore.Client:
    creds_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

    cred = None

    if creds_json:
        cred = credentials.Certificate(json.loads(creds_json))
    elif creds_path:
        cred = credentials.Certificate(creds_path)
    else:
        project_id = os.getenv("FIREBASE_PROJECT_ID")
        client_email = os.getenv("FIREBASE_CLIENT_EMAIL")
        private_key = os.getenv("FIREBASE_PRIVATE_KEY")
        private_key_id = os.getenv("FIREBASE_PRIVATE_KEY_ID")
        client_id = os.getenv("FIREBASE_CLIENT_ID")
        client_cert_url = os.getenv("FIREBASE_CLIENT_CERT_URL")

        if project_id and client_email and private_key:
            cred = credentials.Certificate(
                {
                    "type": "service_account",
                    "project_id": project_id,
                    "client_email": client_email,
                    "private_key": private_key.replace("\\n", "\n"),
                    "private_key_id": private_key_id or "placeholder",
                    "client_id": client_id or "placeholder",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_x509_cert_url": client_cert_url
                    or f"https://www.googleapis.com/robot/v1/metadata/x509/{client_email}",
                }
            )

    if cred is None:
        raise RuntimeError(
            "Provide FIREBASE_CREDENTIALS_JSON, GOOGLE_APPLICATION_CREDENTIALS, or FIREBASE_PROJECT_ID/CLIENT_EMAIL/PRIVATE_KEY"
        )

    if not firebase_admin._apps:
        initialize_app(cred)

    return firestore.client()


firestore_client = _init_firestore()


class InterviewAgent(Agent):
    """Voice interviewer that can both create and conduct interviews."""

    def __init__(self, session_state: SessionState, room_metadata: Dict[str, Any]):
        self.state = session_state
        self.room_metadata = room_metadata

        instructions = (
            "You are an AI mock interviewer named Prepwise Coach. "
            "Speak with brevity, warmth, and clarity. "
            "Two modes exist: interview creation (collect role, seniority, tech stack, interview type, question count) "
            "and interview conduction (ask stored questions sequentially, listen, and log summaries). "
            "Use the provided function tools to persist information in Firestore. "
            "After storing metadata, immediately trigger request_question_generation with the same details so the Next.js API can build the interview. "
            "Always confirm what you captured before moving on. "
            "Never expose raw tool outputs to the user. "
            "When conducting, ask questions one at a time, wait for answers, summarize key takeaways, and save them. "
            "Once the interview request is submitted, announce 'Great! I have generated your interview. You will now be redirected to begin.' and end the call. "
            "Conclude with actionable next steps and thank the candidate."
        )

        super().__init__(instructions=instructions)
        self.name = LIVEKIT_AGENT_NAME

    async def on_enter(self):
        metadata = self.room_metadata or {}
        self.state.user_id = metadata.get("userId")
        self.state.interview_id = metadata.get("interviewId")
        self.state.mode = metadata.get("mode", self.state.mode)

        if self.state.mode == "conduct" and not self.state.interview_id:
            logger.error("Missing interview id in room metadata; ending session")
            return

        await self.session.generate_reply()

    # ---------------------------------------------------------------------
    # Function tools exposed to the LLM
    # ---------------------------------------------------------------------

    @function_tool
    async def store_user_details(
        self,
        context: RunContext,
        role: str,
        level: str,
        tech_stack: str,
        interview_type: str,
        question_count: int,
    ) -> Dict[str, Any]:
        """Persist the interview setup provided by the candidate."""

        if not self.state.user_id:
            raise ValueError("Missing user identity in room metadata")

        doc_ref = (
            firestore_client.collection("interviews").document(self.state.interview_id)
            if self.state.interview_id
            else firestore_client.collection("interviews").document()
        )

        tech_values = [item.strip() for item in tech_stack.split(",") if item.strip()]

        payload = {
            "role": role,
            "level": level,
            "type": interview_type,
            "techstack": tech_values,
            "questionCount": question_count,
            "userId": self.state.user_id,
            "finalized": False,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }

        doc_ref.set(payload, merge=True)

        self.state.interview_id = doc_ref.id
        self.state.metadata_complete = True

        logger.info("Stored interview metadata %s", doc_ref.id)
        return {"interviewId": doc_ref.id}

    @function_tool
    async def request_question_generation(
        self,
        context: RunContext,
        type: str,
        role: str,
        level: str,
        techstack: str,
        amount: int,
        userid: str,
    ) -> Dict[str, Any]:
        """Call the Next.js API to generate interview questions externally."""

        base_url = (
            os.getenv("NEXT_PUBLIC_BASE_URL")
            or os.getenv("APP_BASE_URL")
            or os.getenv("BASE_URL")
            or "http://localhost:3000"
        )

        endpoint = f"{base_url.rstrip('/')}/api/agent/generate"
        payload = {
            "type": type,
            "role": role,
            "level": level,
            "techstack": techstack,
            "amount": amount,
            "userid": userid or (self.state.user_id or ""),
        }

        logger.info("Triggering interview generation via %s", endpoint)
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as http_session:
                async with http_session.post(endpoint, json=payload) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise RuntimeError(
                            f"Interview generation failed ({response.status}): {body}"
                        )
                    try:
                        response_payload = json.loads(body) if body else {"success": True}
                    except json.JSONDecodeError:
                        response_payload = {"raw": body}
        except aiohttp.ClientError as exc:
            raise RuntimeError("Failed to call /api/agent/generate") from exc

        self.state.questions_generated = True
        self.state.question_list = []

        final_message = "Great! I have generated your interview. You will now be redirected to begin."
        await self.session.say(final_message)
        await self.session.aclose()

        logger.info("Interview generation triggered for user %s", payload["userid"])
        return {"status": "triggered", "response": response_payload}

    @function_tool
    async def save_answer(
        self,
        context: RunContext,
        question: str,
        answer: str,
        sequence: int,
    ) -> Dict[str, Any]:
        """Save the candidate's answer transcript for later feedback."""

        if not self.state.interview_id:
            raise ValueError("Interview ID missing; nothing to save")

        doc_ref = (
            firestore_client.collection("interviews")
            .document(self.state.interview_id)
            .collection("answers")
            .document(str(sequence))
        )

        payload = {
            "question": question,
            "answer": answer,
            "sequence": sequence,
            "createdAt": firestore.SERVER_TIMESTAMP,
        }
        doc_ref.set(payload)

        logger.info(
            "Saved answer %s for interview %s", sequence, self.state.interview_id
        )
        return {"status": "stored"}


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


def _session_metadata(room: room_io.Room) -> Dict[str, Any]:
    sources: List[str] = []

    if getattr(room, "metadata", None):
        sources.append(room.metadata)

    participants = getattr(room, "participants", []) or []
    for participant in participants:
        meta = getattr(participant, "metadata", None)
        if meta:
            sources.append(meta)

    for raw in sources:
        try:
            data = json.loads(raw or "{}")
            if isinstance(data, dict) and data:
                return data
        except json.JSONDecodeError:
            continue

    return {}


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext):
    ctx.log_context_fields = {"room": ctx.room.name}

    session = AgentSession(
        stt="deepgram/nova-3",
        llm="openai/gpt-4.1-mini",
        tts="cartesia/sonic-2:9626c31c-bec5-4cca-baa8-f8ba9e84c8bc",
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        resume_false_interruption=True,
        false_interruption_timeout=1.0,
    )

    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        logger.info("Usage summary: %s", usage_collector.get_summary())

    ctx.add_shutdown_callback(log_usage)

    metadata = _session_metadata(ctx.room)
    session_state = SessionState(mode=metadata.get("mode", "create"))

    await session.start(
        agent=InterviewAgent(session_state=session_state, room_metadata=metadata),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                # noise_cancellation=noise_cancellation.BVC()
            )
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)
