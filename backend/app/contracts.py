"""Typed API contracts. Teammates: this file is the integration surface - read this, not the Live code."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Modality = Literal["speech", "image", "video", "text", "system"]
EventType = Literal["transcript_segment", "observation_proposal", "visual_observation", "perception", "correction",
                    "reconciliation"]
ReviewAction = Literal["accept", "dispute", "correct", "reject"]


class ErrorBody(BaseModel):
    error: str = Field(description="Stable machine-readable code, e.g. recording_inactive")
    message: str
    detail: Optional[dict[str, Any]] = None


# ---- experiments ----
class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class Experiment(BaseModel):
    id: str
    name: str
    created_at: str
    status: str


# ---- recording ----
class RecordingStart(BaseModel):
    experiment_id: str


class RecordingStop(BaseModel):
    reason: str = Field(default="user_stopped", max_length=64)


class RecordingSession(BaseModel):
    id: str
    experiment_id: str
    started_at: str
    stopped_at: Optional[str]
    status: Literal["active", "stopped", "expired"]
    stop_reason: Optional[str] = None
    last_heartbeat_at: str
    event_count: int = 0


# ---- events / observations ----
class EventIn(BaseModel):
    session_id: str
    experiment_id: str
    source_modality: Modality
    event_type: EventType
    payload: dict[str, Any]
    model_name: Optional[str] = None
    idempotency_key: str = Field(min_length=8, max_length=128)
    source_event_id: Optional[str] = None


class Review(BaseModel):
    id: str
    observation_id: str
    action: ReviewAction
    correction: Optional[dict[str, Any]] = None
    reviewer: Optional[str] = None
    timestamp: str


class ObservationEvent(BaseModel):
    id: str
    session_id: Optional[str]
    experiment_id: str
    sequence_number: int
    timestamp: str
    source_modality: Modality
    event_type: EventType
    payload: dict[str, Any]
    model_name: Optional[str]
    status: str
    idempotency_key: str
    source_event_id: Optional[str]
    review_status: str = "pending"  # derived from the latest review; the original row is never modified
    reviews: list[Review] = []


class EventAck(BaseModel):
    ok: bool
    saved: bool
    duplicate: bool = False
    event: Optional[ObservationEvent] = None
    error: Optional[str] = None
    message: Optional[str] = None


class ReviewIn(BaseModel):
    action: ReviewAction
    correction: Optional[dict[str, Any]] = None
    reviewer: Optional[str] = Field(default=None, max_length=100)


class ReviewResult(BaseModel):
    review: Review
    correction_event: Optional[ObservationEvent] = None


class EventPage(BaseModel):
    experiment_id: str
    events: list[ObservationEvent]
    last_sequence: int
    recording: Optional[RecordingSession] = None


# ---- vision ----
class VisionRequest(BaseModel):
    image_base64: str = Field(description="JPEG/PNG/WEBP bytes, base64 (no data: prefix)")
    question: str = Field(default="Describe what is visible.", max_length=1000)
    experiment_id: Optional[str] = None
    # Persistence requires BOTH an active backend recording session and save=true.
    save: bool = False
    session_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    step_id: Optional[str] = Field(default=None, description="protocol step (default: live session state)")
    channel_id: Optional[str] = Field(default=None, description="channel, e.g. CH01 (default: live session state)")


class VisionResult(BaseModel):
    provider: str
    model: str
    description: str
    structured: dict[str, Any]
    image_sha256: str
    saved: bool = False
    save_error: Optional[str] = None
    event: Optional[ObservationEvent] = None


# ---- protocols ----
class ProtocolStep(BaseModel):
    id: str = Field(min_length=1, max_length=20)
    action: str = Field(max_length=100)
    description: str = Field(max_length=1000)
    reagent: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    tolerance: Optional[str] = None
    expected_observation: Optional[str] = None
    perception_actions: list[str] = Field(default=[], description="perception action labels that evidence this step")


class ProtocolContent(BaseModel):
    """Science teammates: author protocols in this shape (see backend/steering/protocols/*.json)."""
    title: str
    summary: Optional[str] = None
    materials: list[str] = []
    safety: list[str] = []
    steps: list[ProtocolStep] = Field(min_length=1, max_length=100)
    version: Optional[int] = None  # ignored on write; the server assigns versions


class ProtocolDocument(BaseModel):
    id: str
    experiment_id: str
    version: int
    content: ProtocolContent
    created_at: str


# ---- UI actions ----
UiActionName = Literal[
    # user-initiated (reported by the app)
    "live_feed_start", "live_feed_stop", "camera_open", "camera_close", "camera_flip", "mic_on", "mic_off",
    "gemini_connect", "gemini_disconnect", "recording_start", "recording_stop", "frames_share_on", "frames_share_off",
    "snapshot_capture", "snapshot_analyse", "image_upload", "log_query_typed", "review_action", "tab_change",
    "protocol_step_select",
    # model-requested (via request_ui_action, executed client-side after backend approval)
    "show_tab", "show_protocol_step", "capture_snapshot", "flip_camera",
]
MODEL_UI_ACTIONS = ("show_tab", "show_protocol_step", "capture_snapshot", "flip_camera")


class UiActionIn(BaseModel):
    action: UiActionName
    source: Literal["user", "model"] = "user"
    detail: dict[str, Any] = Field(default={}, description="small, content-free details (ids, tab names)")
    client_timestamp: Optional[str] = None


class UiActionBatch(BaseModel):
    experiment_id: str
    recording_session_id: Optional[str] = None
    actions: list[UiActionIn] = Field(max_length=100)


# ---- continuous perception (live feed) ----
class PerceptionWindowIn(BaseModel):
    """A short window of consecutive camera frames (oldest first) from the live feed."""
    frames_base64: list[str] = Field(min_length=1, max_length=8)
    frame_interval_s: float = Field(default=1.0, gt=0, le=10)
    window_start: str = Field(description="ISO-8601 timestamp of the first frame")
    window_end: str = Field(description="ISO-8601 timestamp of the last frame")
    experiment_id: str
    session_id: Optional[str] = None  # persistence requires an active recording session
    idempotency_key: str = Field(min_length=8, max_length=128)
    hint: Optional[str] = Field(default=None, max_length=300, description="Optional focus, e.g. 'count drops'")


class PerceptionObject(BaseModel):
    label: str
    count: Optional[int] = None
    certainty: Literal["certain", "likely", "uncertain"]
    box_2d: Optional[list[int]] = Field(default=None, description="[ymin, xmin, ymax, xmax] normalised 0-1000, last frame")
    tracked: bool = Field(default=False, description="matches a target the researcher asked to track")


class PerceptionAction(BaseModel):
    action: str = Field(description="verb phrase, e.g. 'dispense drop'")
    object: Optional[str] = Field(default=None, description="what the action was applied to/with")
    count: int = Field(ge=0, description="occurrences within this window")
    certainty: Literal["certain", "likely", "uncertain"]
    first_frame: Optional[int] = None
    protocol_step: Optional[str] = Field(default=None, description="matched protocol step id, if any")


class PerceptionPayload(BaseModel):
    """The perception contract stored in observation_events.payload_json (event_type='perception')."""
    window_start: str
    window_end: str
    frame_count: int
    scene_summary: str
    objects: list[PerceptionObject]
    actions: list[PerceptionAction]
    limitations: list[str] = []
    provider: str
    model: str
    specialist: Optional[dict[str, Any]] = Field(
        default=None, description="chained specialist sub-model output (SPECIALIST_PROVIDER), if configured")
    tracking: list[str] = Field(default=[], description="labels the researcher asked to track this session")
    active_step_id: Optional[str] = None
    active_channel_id: Optional[str] = None
    frame_ids: list[str] = Field(default=[], description="retained session frames (purged at session end)")


class PerceptionResult(BaseModel):
    perception: PerceptionPayload
    saved: bool
    skipped_reason: Optional[str] = None  # recording_inactive | no_change
    event: Optional[ObservationEvent] = None
    reconciliation: Optional[dict[str, Any]] = None  # deterministic protocol check (specialist measurements only)


class LogQueryIn(BaseModel):
    experiment_id: str
    question: str = Field(min_length=1, max_length=1000)
    lookback_seconds: int = Field(default=1800, ge=10, le=86400)


class LogQueryResult(BaseModel):
    answer: str
    confidence: Literal["high", "medium", "low"]
    evidence_event_ids: list[str]
    caveats: list[str] = []
    events_considered: int
    model: str
    asked_at: str


# ---- live / tools ----
class LiveTokenResponse(BaseModel):
    token: str
    model: str
    websocket_url: str
    expires_at: str
    new_session_expires_at: str


class ToolCallIn(BaseModel):
    name: str
    args: dict[str, Any] = {}
    experiment_id: str
    session_id: Optional[str] = None  # current recording session as known to the client; backend re-verifies
    call_id: Optional[str] = None  # Gemini functionCall id; used for idempotency
    image_base64: Optional[str] = None  # for request_visual_analysis: the client-held snapshot bytes


class Capabilities(BaseModel):
    gemini_configured: bool
    live_model: str
    vision_model: str
    vision_provider: str
    specialist_vision: dict[str, Any]
    modal_enabled: bool
    database: str
    raw_media_storage: bool
    heartbeat_timeout_s: int
    tools: list[str]
    routing: dict[str, str] = {}
    steering_docs: list[dict[str, Any]] = []
    telemetry_enabled: bool = True


class TelemetrySummary(BaseModel):
    window_minutes: int
    spans: int
    by_name: list[dict[str, Any]]  # name, n, errors, p50_ms, p95_ms, input_tokens, output_tokens


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database_ok: bool
    database: str
    last_db_write: Optional[str]
    time: str
