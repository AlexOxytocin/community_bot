"""Minimal authenticated HTTP boundary for the Community Mini App."""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal, cast
from urllib.parse import parse_qsl, quote, urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from community_bot.application.assignments import (
    AcceptAssignmentCommand,
    AssignmentCard,
    AssignmentService,
    BeginSubmissionCommand,
    ConfirmSubmissionDraftCommand,
    DecideAssignmentCommand,
    SaveSubmissionDraftCommand,
)
from community_bot.application.cities import TaskCityError, search_task_cities
from community_bot.application.identity import ActorContext
from community_bot.application.moderation import (
    ModerationApplicationError,
    ModerationCase,
    ModerationCaseDetail,
    ModerationService,
    ResolveCaseCommand,
)
from community_bot.application.registration import ProfileSnapshot, RegistrationService
from community_bot.application.reputation import (
    KarmaDraft,
    KarmaVoteResult,
    PersonalStatistics,
    ProfileUnavailableError,
    ReputationService,
    SafeProfile,
    normalize_member_search_query,
)
from community_bot.application.reputation import (
    ReputationError as ReputationApplicationError,
)
from community_bot.application.tasks import (
    OwnedTaskCard,
    PublishedTask,
    PublishTaskCommand,
    SaveWebTaskDraftCommand,
    TaskDraft,
    TaskPreview,
    TaskService,
)
from community_bot.bootstrap.settings import Settings
from community_bot.domain.assignments import (
    AssignmentDecision,
    AssignmentError,
    AssignmentStatus,
    SubmissionDraft,
)
from community_bot.domain.catalog import TaskFormat
from community_bot.domain.moderation import ModerationError, ResolutionCode
from community_bot.domain.registration import (
    ProfileField,
    ProfileLinkAction,
    ProfileLinkCommand,
    RegistrationError,
    StaleRegistrationStepError,
    normalize_profile_link_command,
)
from community_bot.domain.reputation import ReputationError as ReputationDomainError
from community_bot.domain.tasks import (
    TASK_TIME_SIZE_SPECS,
    TaskError,
    TaskKind,
    TaskStatus,
    TaskTimeSize,
)
from community_bot.infrastructure.db.database import Database
from community_bot.infrastructure.db.health import readiness_report

_COOKIE_NAME = "__Host-community_session"
_LOCAL_COOKIE_NAME = "community_session_local"
_SESSION_LIFETIME_SECONDS = 2_592_000
_PROOF_MAX_AGE_SECONDS = 300
_PROOF_FUTURE_SKEW_SECONDS = 30
_PROOF_MAX_BYTES = 8192
_PROOF_MAX_FIELDS = 32
_MAX_TELEGRAM_USER_ID = 2**63 - 1
_TELEGRAM_USERNAME = re.compile(r"^[A-Za-z0-9_]{5,32}$")
_MAX_IDEMPOTENCY_KEY = 2**63 - 1
_SUBMISSION_BODY_MAX_BYTES = 4096
_STATIC_DIR = Path(__file__).with_name("static")
_PUBLIC_ERROR_CODES = frozenset(
    {
        "invalid_member_query",
        "invalid_idempotency_key",
        "invalid_origin",
        "invalid_request",
        "invalid_task_city",
        "karma_vote_unavailable",
        "not_found",
        "profile_unavailable",
        "assignment_unavailable",
        "task_catalog_unavailable",
        "unauthorized",
    }
)


class _Dto(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class TelegramIdentity:
    """Trusted identity extracted only from signed Telegram initData."""

    user_id: int
    username: str | None


class LevelDto(_Dto):
    number: int
    display_name: str


class ProfileStatisticsDto(_Dto):
    completed_tasks: int | None
    created_tasks: int | None


class ProfileLinkDto(_Dto):
    id: UUID
    label: str
    url: str


class MeDto(_Dto):
    member_id: UUID
    telegram_username: str | None
    display_name: str
    city: str | None
    short_bio: str | None
    skill_tags: tuple[str, ...]
    profile_links: tuple[ProfileLinkDto, ...]
    credit_balance: int
    experience_total: int
    level: LevelDto
    statistics: ProfileStatisticsDto


class ProfileUpdateRequest(_Dto):
    model_config = ConfigDict(extra="forbid")

    field: Literal["display_name", "city", "short_bio", "skill_tags", "profile_links"]
    value: str | None = None
    action: Literal["create", "update", "delete"] | None = None
    link_id: UUID | None = None
    label: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> ProfileUpdateRequest:
        """Reject mixed text/link command shapes before application mutation."""
        if self.field != "profile_links":
            if self.value is None or any(
                item is not None for item in (self.action, self.link_id, self.label, self.url)
            ):
                raise ValueError("Invalid text profile update shape.")
            return self
        command = ProfileLinkCommand(
            action=ProfileLinkAction(self.action) if self.action else ProfileLinkAction.CREATE,
            link_id=self.link_id,
            label=self.label,
            url=self.url,
        )
        if self.value is not None or self.action is None:
            raise ValueError("Invalid profile link update shape.")
        normalize_profile_link_command(command)
        return self


class KarmaDto(_Dto):
    score: int
    count: int


class ReliabilityDto(_Dto):
    accepted: int
    approved_weight: Decimal
    no_show: int
    rate: Decimal | None


class MemberDto(_Dto):
    member_id: UUID
    telegram_username: str | None
    display_name: str
    city: str | None
    short_bio: str | None
    skill_tags: tuple[str, ...]
    profile_links: tuple[ProfileLinkDto, ...]
    experience_total: int
    level_number: int
    karma: KarmaDto
    reliability: ReliabilityDto


class MemberDetailDto(MemberDto):
    can_rate_karma: bool


class KarmaActionRequest(_Dto):
    action: Literal["begin", "save_value", "save_comment", "confirm"]
    expected_revision: int | None = Field(default=None, ge=0, strict=True)
    value: int | None = Field(default=None, ge=-1, le=1, strict=True)
    comment: str | None = Field(default=None, max_length=300)


class KarmaActionDto(_Dto):
    action: Literal["begin", "save_value", "save_comment", "confirm"]
    target_id: UUID
    step: Literal["value", "comment", "preview", "confirmed"]
    revision: int
    aggregate: KarmaDto | None = None


class MembersDto(_Dto):
    items: tuple[MemberDto, ...]


class TaskDto(_Dto):
    id: UUID
    origin: str
    author_display_name: str
    category_name: str | None
    category_icon: str | None
    task_kind: str | None
    time_size: str | None
    title: str
    credit_reward_per_performer: int
    performer_slots: int
    minimum_level: int
    format: str
    city: str | None
    deadline_at: datetime.datetime
    status: str
    description: str
    completion_criteria: str
    performer_instructions: str
    materials: dict[str, str]
    public_input: dict[str, object]


class TasksDto(_Dto):
    items: tuple[TaskDto, ...]
    next_cursor: UUID | None


class TaskHomeAttentionDto(_Dto):
    action: Literal["submit_result", "review_work", "answer_cancellation"]
    count: int = Field(ge=0)
    target: Literal["taken", "created", "cancellations"]


class TaskHomeDto(_Dto):
    attention: tuple[TaskHomeAttentionDto, ...]
    available_count: int | None = Field(default=None, ge=0)
    available_has_more: bool = False
    can_create: bool | None = None
    has_draft: bool | None = None
    active_count: int | None = Field(default=None, ge=0)
    waiting_count: int | None = Field(default=None, ge=0)
    archive_count: int | None = Field(default=None, ge=0)
    new_tasks: tuple[TaskDto, ...]
    errors: tuple[Literal["catalog", "creation", "work", "owned", "reviews", "cancellations"], ...]


class OwnedTaskAssigneeDto(_Dto):
    display_name: str
    status: str


class OwnedTaskDto(_Dto):
    id: UUID
    title: str
    status: str
    performer_slots: int
    deadline_at: datetime.datetime
    assignees: tuple[OwnedTaskAssigneeDto, ...]
    cancellation_status: str | None
    cancellation_action: Literal["cancel", "request"] | None


class OwnedTaskCancellationDto(_Dto):
    status: Literal["cancelled", "pending", "closed", "declined", "obsolete"]


class OwnedTasksDto(_Dto):
    items: tuple[OwnedTaskDto, ...]


class AssignmentDto(_Dto):
    id: UUID
    task_id: UUID
    slot_number: int
    status: str
    accepted_at: datetime.datetime


class AssignmentCardDto(_Dto):
    id: UUID
    task_id: UUID
    task_title: str
    task_origin: str
    assignment_status: str
    accepted_at: datetime.datetime
    submitted_at: datetime.datetime | None
    review_deadline_at: datetime.datetime | None
    reject_dispute_deadline_at: datetime.datetime | None
    reviewed_at: datetime.datetime | None
    task_deadline_at: datetime.datetime
    result_summary: str | None
    case_status: str | None


class AssignmentsDto(_Dto):
    items: tuple[AssignmentCardDto, ...]
    next_cursor: str | None


class AssignmentReviewDto(_Dto):
    id: UUID
    task_title: str
    performer_display_name: str
    submitted_at: datetime.datetime
    review_deadline_at: datetime.datetime | None
    result: str
    available_decisions: tuple[AssignmentDecision, ...]


class AssignmentReviewsDto(_Dto):
    items: tuple[AssignmentReviewDto, ...]


class AssignmentDecisionRequest(_Dto):
    decision: AssignmentDecision


class AssignmentDisputeRequest(_Dto):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    comment: str = Field(min_length=1)


class AssignmentCancellationRequest(_Dto):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reason: str = Field(min_length=1, max_length=1000)


class ModerationCaseDto(_Dto):
    id: UUID
    assignment_id: UUID
    case_type: str
    status: Literal["open", "appealed"]
    revision: int
    current_code: str | None
    opened_at: datetime.datetime
    resolved_at: datetime.datetime | None


class ModerationCasesDto(_Dto):
    items: tuple[ModerationCaseDto, ...]


class ModerationCaseDetailDto(_Dto):
    id: UUID
    status: Literal["open"]
    revision: int
    task_title: str
    task_origin: Literal["member", "community"]
    credit_reward_per_performer: int
    assignment_status: str
    result_summary: str | None
    dispute_reason: str
    allowed_resolution_codes: tuple[ResolutionCode, ...]
    opened_at: datetime.datetime


class ModerationResolutionRequest(_Dto):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0, strict=True)
    code: ResolutionCode
    reason: str = Field(min_length=1)


class AssignmentDetailDto(AssignmentCardDto):
    category_name: str | None
    category_icon: str | None
    task_kind: str | None
    time_size: str | None
    description: str
    performer_instructions: str
    completion_criteria: str
    reward_per_performer: int
    format: str
    city: str | None
    minimum_level: int
    performer_slots: int
    submission_contract: Literal["freeform_result_v1"] | None
    can_submit: bool
    can_cancel: bool
    can_dispute: bool


class SubmissionDraftDto(_Dto):
    id: UUID
    revision: int
    result: str | None


class SaveSubmissionDraftRequest(_Dto):
    expected_revision: int = Field(ge=0, strict=True)
    payload: dict[str, object]


class ConfirmSubmissionDraftRequest(_Dto):
    expected_revision: int = Field(ge=0, strict=True)


class TaskFormRequest(_Dto):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    category_id: UUID
    task_kind: TaskKind
    time_size: TaskTimeSize
    title: str
    description: str
    completion_criteria: str
    credit_reward_per_performer: int = Field(strict=True)
    deadline_at: datetime.datetime
    format: TaskFormat
    city: str | None = None
    materials: dict[Literal["text", "url"], str]
    performer_slots: int = Field(strict=True)

    @field_validator("deadline_at")
    @classmethod
    def canonical_deadline(cls, value: datetime.datetime) -> datetime.datetime:
        """Project aware timestamps to UTC without time-dependent validation."""
        return value.astimezone(datetime.UTC) if value.tzinfo is not None else value


class TaskCreationRequest(_Dto):
    action: Literal["start", "start_new", "save", "publish"]
    draft_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=0, strict=True)
    form: TaskFormRequest | None = None


class LeaderboardItemDto(_Dto):
    rank: int
    member_id: UUID
    display_name: str
    experience: int
    unique_recipients: int
    reliability: Decimal | None
    no_show: int


class LeaderboardDto(_Dto):
    items: tuple[LeaderboardItemDto, ...]


def create_web_app(
    *,
    settings: Settings,
    database: Database,
    heartbeat_not_before: datetime.datetime | None = None,
) -> FastAPI:
    """Build the web-only application after strict config validation."""
    bot_token, origin = _web_config(settings)
    secure_cookie = origin.startswith("https://")
    cookie_name = _COOKIE_NAME if secure_cookie else _LOCAL_COOKIE_NAME
    registration = RegistrationService(database.unit_of_work)
    reputation = ReputationService(database.unit_of_work)
    tasks = TaskService(database.unit_of_work)
    assignments = AssignmentService(database.unit_of_work)
    moderation = ModerationService(database.unit_of_work)
    index_html = (
        (_STATIC_DIR / "index.html")
        .read_text(encoding="utf-8")
        .replace("__RELEASE__", quote(settings.release, safe=""))
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    started_at = heartbeat_not_before or datetime.datetime.now(datetime.UTC)

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "alive"}, headers={"Cache-Control": "no-store"})

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        report = await readiness_report(
            settings.database_url,
            process_name="community-worker",
            heartbeat_max_age=datetime.timedelta(seconds=settings.heartbeat_max_age_seconds),
            expected_release=settings.release,
            heartbeat_not_before=started_at,
        )
        return JSONResponse(
            {**report.as_dict(), "release": settings.release},
            status_code=200 if report.healthy else 503,
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _error: RequestValidationError) -> JSONResponse:
        return _error_response(422, "invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        framework_codes = {404: "not_found", 405: "method_not_allowed"}
        code = framework_codes.get(error.status_code, "request_failed")
        if isinstance(error.detail, str) and error.detail in _PUBLIC_ERROR_CODES:
            code = error.detail
        return _error_response(error.status_code, code)

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _error: Exception) -> JSONResponse:
        return _error_response(500, "internal_error")

    async def current_actor(request: Request) -> ActorContext:
        session_token = request.cookies.get(cookie_name)
        digest = _session_digest(session_token)
        if digest is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        now = datetime.datetime.now(datetime.UTC)
        resolved = await database.web_session_member_id(token_digest=digest, now=now)
        if resolved is None:
            raise HTTPException(status_code=401, detail="unauthorized")
        member_id, authenticated_at = resolved
        return ActorContext(member_id, "telegram", authenticated_at)

    async def issue_session(
        identity: TelegramIdentity, response: Response, *, proof: bytes | None = None
    ) -> Response:
        raw_token = secrets.token_bytes(32)
        digest = hashlib.sha256(raw_token).digest()
        now = datetime.datetime.now(datetime.UTC)
        proof_digest = hashlib.sha256(proof or raw_token).digest()
        try:
            member_id = await database.create_web_session(
                telegram_user_id=identity.user_id,
                telegram_username=identity.username,
                proof_digest=proof_digest,
                proof_expires_at=now + datetime.timedelta(seconds=_PROOF_MAX_AGE_SECONDS),
                token_digest=digest,
                authenticated_at=now,
                expires_at=now + datetime.timedelta(seconds=_SESSION_LIFETIME_SECONDS),
            )
        except SQLAlchemyError:
            return _error_response(503, "temporarily_unavailable")
        if member_id is None:
            return _error_response(401, "unauthorized")
        token = base64.urlsafe_b64encode(raw_token).rstrip(b"=").decode("ascii")
        response.set_cookie(
            cookie_name,
            token,
            max_age=_SESSION_LIFETIME_SECONDS,
            secure=secure_cookie,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/api/v1/auth/telegram", status_code=204)
    async def authenticate(request: Request) -> Response:
        _require_origin(request, origin)
        if request.headers.get("content-type", "").lower() != "text/plain; charset=utf-8":
            return _error_response(422, "invalid_request")
        try:
            raw = await _bounded_body(request, limit=_PROOF_MAX_BYTES)
        except ValueError:
            return _error_response(422, "invalid_request")
        except OverflowError:
            return _error_response(413, "payload_too_large")
        try:
            identity = validate_telegram_init_data(raw, bot_token=bot_token)
        except (TypeError, ValueError):
            return _error_response(401, "unauthorized")
        return await issue_session(
            identity,
            Response(status_code=204, headers={"Cache-Control": "no-store"}),
            proof=raw,
        )

    local_review_user_id = settings.local_review_telegram_user_id
    if not secure_cookie and local_review_user_id is not None:

        @app.get("/local-review", include_in_schema=False)
        async def local_review() -> Response:
            return await issue_session(
                TelegramIdentity(local_review_user_id, None),
                RedirectResponse(url="/", status_code=303),
            )

    @app.delete("/api/v1/session", status_code=204)
    async def logout(request: Request) -> Response:
        _require_origin(request, origin)
        session_token = request.cookies.get(cookie_name)
        digest = _session_digest(session_token)
        if digest is not None:
            await database.revoke_web_session(
                token_digest=digest, now=datetime.datetime.now(datetime.UTC)
            )
        response = Response(status_code=204, headers={"Cache-Control": "no-store"})
        response.set_cookie(
            cookie_name,
            "",
            max_age=0,
            expires=0,
            secure=secure_cookie,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    @app.get("/api/v1/me", response_model=MeDto)
    async def me(actor: ActorContext = Depends(current_actor)) -> JSONResponse:
        try:
            profile = await registration.own_profile(actor)
            statistics = await reputation.own_statistics(actor)
        except (PermissionError, ProfileUnavailableError) as error:
            raise HTTPException(status_code=403, detail="profile_unavailable") from error
        return _json_response(_me_dto(profile, statistics))

    @app.put("/api/v1/me/profile", response_model=MeDto)
    async def update_me(request: Request) -> JSONResponse:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        if request.headers.get("content-type", "").lower() != "application/json":
            return _error_response(422, "invalid_request")
        try:
            body = await _bounded_body(request, limit=_SUBMISSION_BODY_MAX_BYTES)
            command = ProfileUpdateRequest.model_validate_json(body)
        except (OverflowError, ValueError, ValidationError):
            return _error_response(422, "invalid_request")
        payload = command.model_dump(mode="json")
        fingerprint = _submission_fingerprint("update", payload=payload)
        update_id = _submission_update_id(
            actor.member_id,
            actor.member_id,
            "update",
            operation_key,
            namespace=b"profile-update-v1",
        )
        try:
            if command.field == "profile_links":
                await registration.update_own_profile_link(
                    update_id=update_id,
                    actor_member_id=actor.member_id,
                    command=ProfileLinkCommand(
                        ProfileLinkAction(command.action),
                        command.link_id,
                        command.label,
                        command.url,
                    ),
                    replay_fingerprint=fingerprint,
                )
            else:
                await registration.update_own_profile_field(
                    update_id=update_id,
                    actor_member_id=actor.member_id,
                    field=ProfileField(command.field),
                    raw_value=command.value or "",
                    replay_fingerprint=fingerprint,
                )
            profile = await registration.own_profile(actor)
            statistics = await reputation.own_statistics(actor)
        except StaleRegistrationStepError:
            return _error_response(409, "profile_unavailable")
        except RegistrationError:
            return _error_response(422, "invalid_request")
        except PermissionError:
            return _error_response(403, "profile_unavailable")
        return _json_response(_me_dto(profile, statistics))

    @app.get("/api/v1/members", response_model=MembersDto)
    async def members(
        actor: ActorContext = Depends(current_actor),
        query: str | None = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 30,
    ) -> JSONResponse:
        normalized = _member_query(query)
        try:
            page = await reputation.members(actor=actor, query=normalized, limit=limit)
        except ProfileUnavailableError as error:
            raise HTTPException(status_code=403, detail="profile_unavailable") from error
        return _json_response(MembersDto(items=tuple(_member_dto(item) for item in page.items)))

    @app.get("/api/v1/members/{member_id}", response_model=MemberDetailDto)
    async def member_detail(
        member_id: UUID, actor: ActorContext = Depends(current_actor)
    ) -> JSONResponse:
        try:
            profile, can_rate_karma = await reputation.profile_detail(
                actor=actor, target_id=member_id
            )
        except (PermissionError, ProfileUnavailableError) as error:
            raise HTTPException(status_code=404, detail="not_found") from error
        dto = MemberDetailDto(**_member_dto(profile).model_dump(), can_rate_karma=can_rate_karma)
        return _json_response(dto)

    @app.post(
        "/api/v1/members/{member_id}/karma-vote",
        response_model=KarmaActionDto,
    )
    async def change_karma_vote(member_id: UUID, request: Request) -> JSONResponse:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        if request.headers.get("content-type", "").lower() != "application/json":
            return _error_response(422, "invalid_request")
        try:
            body = await _bounded_body(request, limit=_SUBMISSION_BODY_MAX_BYTES)
            command = KarmaActionRequest.model_validate_json(body)
            expected = {
                "begin": {"action"},
                "save_value": {"action", "expected_revision", "value"},
                "save_comment": {"action", "expected_revision", "comment"},
                "confirm": {"action", "expected_revision"},
            }[command.action]
        except (OverflowError, ValueError, ValidationError):
            return _error_response(422, "invalid_request")
        if command.model_fields_set != expected or any(
            getattr(command, field) is None for field in expected
        ):
            return _error_response(422, "invalid_request")
        payload: dict[str, object] = {"target_id": str(member_id)}
        if command.value is not None:
            payload["value"] = command.value
        if command.comment is not None:
            payload["comment"] = command.comment
        fingerprint = _submission_fingerprint(
            command.action,
            command.expected_revision,
            payload=payload,
        )
        update_id = _submission_update_id(
            actor.member_id,
            actor.member_id,
            "karma-vote",
            operation_key,
            namespace=b"karma-vote-v1",
        )
        try:
            if command.action == "begin":
                result = await reputation.begin_vote(
                    update_id=update_id,
                    actor_member_id=actor.member_id,
                    target_id=member_id,
                    replay_fingerprint=fingerprint,
                )
                dto = _karma_draft_dto(command.action, result)
            elif command.action == "save_value":
                result = await reputation.save_value(
                    update_id=update_id,
                    actor_member_id=actor.member_id,
                    target_id=member_id,
                    replay_fingerprint=fingerprint,
                    expected_revision=cast("int", command.expected_revision),
                    value=cast("int", command.value),
                )
                dto = _karma_draft_dto(command.action, result)
            elif command.action == "save_comment":
                result = await reputation.save_comment(
                    update_id=update_id,
                    actor_member_id=actor.member_id,
                    target_id=member_id,
                    replay_fingerprint=fingerprint,
                    expected_revision=cast("int", command.expected_revision),
                    comment=cast("str", command.comment),
                )
                dto = _karma_draft_dto(command.action, result)
            else:
                confirmed = await reputation.confirm_vote(
                    update_id=update_id,
                    actor_member_id=actor.member_id,
                    target_id=member_id,
                    replay_fingerprint=fingerprint,
                    expected_revision=cast("int", command.expected_revision),
                )
                dto = _karma_confirm_dto(member_id, confirmed)
        except ReputationDomainError:
            return _error_response(422, "invalid_request")
        except (LookupError, PermissionError, ProfileUnavailableError):
            return _error_response(404, "not_found")
        except (ReputationApplicationError, ValueError):
            return _error_response(409, "karma_vote_unavailable")
        return _json_response(dto)

    @app.get("/api/v1/tasks", response_model=TasksDto)
    async def available_tasks(
        actor: ActorContext = Depends(current_actor),
        cursor: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> JSONResponse:
        try:
            page = await tasks.list_available(actor=actor, cursor_task_id=cursor, limit=limit)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail="task_catalog_unavailable") from error
        return _json_response(
            TasksDto(
                items=tuple(_task_dto(item) for item in page.items),
                next_cursor=page.next_cursor_task_id,
            )
        )

    @app.get("/api/v1/task-home", response_model=TaskHomeDto)
    async def task_home(actor: ActorContext = Depends(current_actor)) -> JSONResponse:
        errors: list[
            Literal["catalog", "creation", "work", "owned", "reviews", "cancellations"]
        ] = []
        catalog = None
        active = None
        owned = None
        reviews = None
        cancellations = None
        can_create: bool | None = None
        has_draft: bool | None = None

        try:
            catalog = await tasks.list_available(actor=actor, limit=50)
        except (PermissionError, TaskError, SQLAlchemyError):
            errors.append("catalog")
        try:
            _categories, draft, preview, _needs_edit = await tasks.web_state(actor.member_id)
            can_create = True
            has_draft = draft is not None or preview is not None
        except (PermissionError, TaskError, SQLAlchemyError):
            errors.append("creation")
        try:
            active = await assignments.active_cards(actor=actor, limit=50)
        except (AssignmentError, PermissionError, SQLAlchemyError):
            errors.append("work")
        try:
            owned = await tasks.list_owned_cards(actor=actor, creator_only=True)
        except (PermissionError, TaskError, SQLAlchemyError):
            errors.append("owned")
        try:
            reviews = await assignments.creator_review_cards(actor=actor)
        except (AssignmentError, PermissionError, SQLAlchemyError):
            errors.append("reviews")
        try:
            cancellations = await tasks.pending_cancellation_responses(actor=actor)
        except (PermissionError, TaskError, SQLAlchemyError):
            errors.append("cancellations")

        active_items = None if active is None else active.items
        attention = (
            TaskHomeAttentionDto(
                action="submit_result",
                count=0 if active_items is None else sum(card.can_submit for card in active_items),
                target="taken",
            ),
            TaskHomeAttentionDto(
                action="review_work",
                count=0 if reviews is None else len(reviews),
                target="created",
            ),
            TaskHomeAttentionDto(
                action="answer_cancellation",
                count=0 if cancellations is None else len(cancellations),
                target="cancellations",
            ),
        )
        in_progress = (
            None
            if active_items is None
            else sum(card.assignment.status is AssignmentStatus.ACCEPTED for card in active_items)
        )
        waiting = None if active_items is None else len(active_items) - cast("int", in_progress)
        archived_statuses = {
            TaskStatus.EXPIRED,
            TaskStatus.PARTIALLY_COMPLETED,
            TaskStatus.COMPLETED,
            TaskStatus.CANCELLED,
        }
        return _json_response(
            TaskHomeDto(
                attention=attention,
                available_count=None if catalog is None else len(catalog.items),
                available_has_more=catalog is not None and catalog.next_cursor_task_id is not None,
                can_create=can_create,
                has_draft=has_draft,
                active_count=in_progress,
                waiting_count=waiting,
                archive_count=None
                if owned is None
                else sum(card.task.status in archived_statuses for card in owned),
                new_tasks=()
                if catalog is None
                else tuple(_task_dto(item) for item in catalog.items[:6]),
                errors=tuple(errors),
            )
        )

    @app.get("/api/v1/task-creation")
    async def task_creation(actor: ActorContext = Depends(current_actor)) -> JSONResponse:
        try:
            categories, draft, preview, needs_edit = await tasks.web_state(actor.member_id)
        except PermissionError:
            return _error_response(403, "task_catalog_unavailable")
        return _json_response(
            {
                "categories": [
                    {"id": str(item.id), "name": item.name, "icon": item.icon}
                    for item in categories
                ],
                "time_sizes": [
                    {
                        "value": size.value,
                        "label": spec.label,
                        "reward_options": spec.reward_options,
                        "minimum_reward": spec.minimum_reward,
                    }
                    for size, spec in TASK_TIME_SIZE_SPECS.items()
                ],
                "draft": None if draft is None else _task_draft_json(draft),
                "preview": None if preview is None else _task_preview_json(preview),
                "needs_edit": needs_edit,
            }
        )

    @app.get("/api/v1/task-cities")
    async def task_cities(
        q: Annotated[str, Query(max_length=80)] = "",
        limit: Annotated[int, Query(ge=1, le=10)] = 8,
        _actor: ActorContext = Depends(current_actor),
    ) -> JSONResponse:
        return _json_response(
            {
                "items": [
                    {"value": item, "label": item} for item in search_task_cities(q, limit=limit)
                ]
            }
        )

    @app.post("/api/v1/task-creation")
    async def change_task_creation(request: Request) -> Response:
        _require_origin(request, origin)
        if request.headers.get("content-type", "").lower() != "application/json":
            return _error_response(422, "invalid_request")
        actor = await current_actor(request)
        key = _idempotency_key(request)
        try:
            raw = await _bounded_body(request, limit=_SUBMISSION_BODY_MAX_BYTES)
            parsed = json.loads(raw)
            model = TaskCreationRequest.model_validate(parsed)
            expected = {
                "start": {"action"},
                "start_new": {"action", "draft_id", "expected_revision"},
                "save": {"action", "draft_id", "expected_revision", "form"},
                "publish": {"action", "draft_id", "expected_revision"},
            }[model.action]
        except (OverflowError, ValueError, ValidationError, AttributeError):
            return _error_response(422, "invalid_request")
        if model.model_fields_set != expected or any(
            getattr(model, field) is None for field in expected
        ):
            return _error_response(422, "invalid_request")
        resource = actor.member_id if model.action == "start" else cast("UUID", model.draft_id)
        fingerprint = _submission_fingerprint(
            model.action,
            getattr(model, "expected_revision", None),
            payload=model.form.model_dump(mode="json") if model.form else None,
        )
        update_id = _submission_update_id(
            actor.member_id, resource, model.action, key, namespace=b"task-creation-v1"
        )
        try:
            if model.action in {"start", "start_new"}:
                await tasks.start(
                    update_id=update_id,
                    actor_telegram_user_id=None,
                    template_id=None,
                    actor_member_id=actor.member_id,
                    replay_fingerprint=fingerprint,
                    replace_current=(
                        (cast("UUID", model.draft_id), cast("int", model.expected_revision))
                        if model.action == "start_new"
                        else None
                    ),
                )
            elif model.action == "save":
                form = cast("TaskFormRequest", model.form)
                await tasks.save_web(
                    SaveWebTaskDraftCommand(
                        update_id=update_id,
                        actor_member_id=actor.member_id,
                        draft_id=cast("UUID", model.draft_id),
                        expected_revision=cast("int", model.expected_revision),
                        replay_fingerprint=fingerprint,
                        **form.model_dump(),
                    )
                )
            else:
                published = await tasks.publish(
                    PublishTaskCommand(
                        update_id,
                        None,
                        cast("UUID", model.draft_id),
                        cast("int", model.expected_revision),
                        actor.member_id,
                        fingerprint,
                    )
                )
                return _json_response({"task_id": str(published.id)})
        except TaskCityError:
            return _error_response(422, "invalid_task_city")
        except (TaskError, LookupError, PermissionError):
            return _error_response(409, "task_catalog_unavailable")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/owned-tasks", response_model=OwnedTasksDto)
    async def owned_tasks(actor: ActorContext = Depends(current_actor)) -> JSONResponse:
        try:
            cards = await tasks.list_owned_cards(actor=actor, creator_only=True)
        except PermissionError:
            return _error_response(403, "task_catalog_unavailable")
        return _json_response(OwnedTasksDto(items=tuple(_owned_task_dto(card) for card in cards)))

    @app.post(
        "/api/v1/owned-tasks/{task_id}/cancellation",
        response_model=OwnedTaskCancellationDto,
    )
    async def cancel_owned_task(task_id: UUID, request: Request) -> JSONResponse:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        if await request.body():
            return _error_response(422, "invalid_request")
        update_id = _submission_update_id(
            actor.member_id,
            task_id,
            "cancel",
            operation_key,
            namespace=b"owned-task-cancellation-v1",
        )
        try:
            outcome = await tasks.request_cancellation(
                update_id=update_id,
                actor=actor,
                task_id=task_id,
            )
        except (TaskError, LookupError, PermissionError):
            return _error_response(409, "task_cancellation_unavailable")
        return _json_response(OwnedTaskCancellationDto(status=outcome.status))

    @app.get("/api/v1/leaderboard", response_model=LeaderboardDto)
    async def leaderboard(
        actor: ActorContext = Depends(current_actor),
        limit: Annotated[int, Query(ge=1, le=50)] = 30,
        period: Literal["week", "month", "all"] = "all",
    ) -> JSONResponse:
        try:
            page = await reputation.leaderboard(actor=actor, limit=limit, period=period)
        except ProfileUnavailableError as error:
            raise HTTPException(status_code=403, detail="profile_unavailable") from error
        return _json_response(
            LeaderboardDto(
                items=tuple(
                    LeaderboardItemDto(
                        rank=item.rank,
                        member_id=item.member_id,
                        display_name=item.display_name,
                        experience=item.experience,
                        unique_recipients=item.unique_recipients,
                        reliability=item.reliability,
                        no_show=item.no_show,
                    )
                    for item in page.items
                )
            )
        )

    @app.get("/api/v1/assignments", response_model=AssignmentsDto)
    async def active_assignments(
        actor: ActorContext = Depends(current_actor),
        status: Literal["active"] = "active",
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
        cursor: str | None = None,
    ) -> JSONResponse:
        del status
        try:
            page = await assignments.active_cards(
                actor=actor,
                limit=limit,
                cursor=_parse_assignment_cursor(cursor),
            )
        except ValueError:
            return _error_response(422, "invalid_request")
        except PermissionError:
            return _error_response(403, "assignment_unavailable")
        return _json_response(
            AssignmentsDto(
                items=tuple(_assignment_card_dto(item) for item in page.items),
                next_cursor=None
                if page.next_cursor is None
                else _assignment_cursor(page.next_cursor),
            )
        )

    @app.get("/api/v1/assignments/{assignment_id}", response_model=AssignmentDetailDto)
    async def assignment_detail(
        assignment_id: UUID, actor: ActorContext = Depends(current_actor)
    ) -> JSONResponse:
        try:
            card = await assignments.active_card(actor=actor, assignment_id=assignment_id)
        except PermissionError:
            return _error_response(403, "assignment_unavailable")
        except LookupError:
            return _error_response(404, "not_found")
        return _json_response(_assignment_detail_dto(card))

    @app.post("/api/v1/assignments/{assignment_id}/cancellation", status_code=204)
    async def cancel_assignment(assignment_id: str, request: Request) -> Response:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        parsed_assignment_id = _canonical_uuid(assignment_id)
        if parsed_assignment_id is None:
            return _error_response(422, "invalid_request")
        payload = cast(
            "AssignmentCancellationRequest | None",
            await _submission_request(request, AssignmentCancellationRequest),
        )
        if payload is None:
            return _error_response(422, "invalid_request")
        fingerprint = _submission_fingerprint("cancel", payload={"reason": payload.reason})
        update_id = _submission_update_id(
            actor.member_id,
            parsed_assignment_id,
            "cancel",
            operation_key,
            namespace=b"assignment-cancellation-v1",
        )
        try:
            await assignments.cancel(
                update_id=update_id,
                actor_telegram_user_id=None,
                assignment_id=parsed_assignment_id,
                reason=payload.reason,
                actor_member_id=actor.member_id,
                replay_fingerprint=fingerprint,
            )
        except (AssignmentError, LookupError, PermissionError, TaskError):
            return _error_response(409, "assignment_unavailable")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/assignments/{assignment_id}/disputes", status_code=204)
    async def open_assignment_dispute(assignment_id: str, request: Request) -> Response:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        parsed_assignment_id = _canonical_uuid(assignment_id)
        if parsed_assignment_id is None:
            return _error_response(422, "invalid_request")
        payload = cast(
            "AssignmentDisputeRequest | None",
            await _submission_request(request, AssignmentDisputeRequest),
        )
        if payload is None:
            return _error_response(422, "invalid_request")
        update_id = _submission_update_id(
            actor.member_id,
            parsed_assignment_id,
            "dispute",
            operation_key,
            namespace=b"assignment-dispute-v1",
        )
        try:
            await assignments.dispute(
                update_id=update_id,
                actor_telegram_user_id=None,
                assignment_id=parsed_assignment_id,
                command_id=UUID(int=update_id),
                comment=payload.comment,
                actor_member_id=actor.member_id,
                replay_fingerprint=_submission_fingerprint(
                    "dispute", payload={"comment": payload.comment}
                ),
            )
        except (AssignmentError, LookupError, PermissionError):
            return _error_response(409, "assignment_unavailable")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/assignment-reviews", response_model=AssignmentReviewsDto)
    async def assignment_reviews(
        actor: ActorContext = Depends(current_actor),
    ) -> JSONResponse:
        try:
            cards = await assignments.creator_review_cards(actor=actor)
        except PermissionError:
            return _error_response(403, "assignment_unavailable")
        items = tuple(_assignment_review_dto(card) for card in cards)
        return _json_response(AssignmentReviewsDto(items=items))

    @app.get("/api/v1/assignment-reviews/{assignment_id}", response_model=AssignmentReviewDto)
    async def assignment_review(
        assignment_id: UUID, actor: ActorContext = Depends(current_actor)
    ) -> JSONResponse:
        try:
            cards = await assignments.creator_review_cards(actor=actor, assignment_id=assignment_id)
        except PermissionError:
            return _error_response(404, "not_found")
        if not cards:
            return _error_response(404, "not_found")
        return _json_response(_assignment_review_dto(cards[0]))

    @app.post("/api/v1/assignment-reviews/{assignment_id}/decision", status_code=204)
    async def decide_assignment(assignment_id: UUID, request: Request) -> Response:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        payload = cast(
            "AssignmentDecisionRequest | None",
            await _submission_request(request, AssignmentDecisionRequest),
        )
        if payload is None:
            return _error_response(422, "invalid_request")
        update_id = _submission_update_id(
            actor.member_id,
            assignment_id,
            "decide",
            operation_key,
            namespace=b"assignment-review-v1",
        )
        try:
            await assignments.decide(
                DecideAssignmentCommand(
                    update_id,
                    None,
                    assignment_id,
                    UUID(int=update_id),
                    payload.decision,
                    actor.member_id,
                )
            )
        except (AssignmentError, LookupError, PermissionError):
            return _error_response(409, "assignment_unavailable")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/moderation/cases", response_model=ModerationCasesDto)
    async def moderation_cases(
        actor: ActorContext = Depends(current_actor),
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> JSONResponse:
        try:
            cases = await moderation.queue(actor, limit=limit)
        except PermissionError:
            return _error_response(403, "moderation_unavailable")
        return _json_response(
            ModerationCasesDto(items=tuple(_moderation_case_dto(item) for item in cases))
        )

    @app.get("/api/v1/moderation/cases/{case_id}", response_model=ModerationCaseDetailDto)
    async def moderation_case(
        case_id: UUID, actor: ActorContext = Depends(current_actor)
    ) -> JSONResponse:
        try:
            detail = await moderation.detail(actor, case_id)
        except (LookupError, PermissionError):
            return _error_response(404, "not_found")
        return _json_response(_moderation_case_detail_dto(detail))

    @app.post("/api/v1/moderation/cases/{case_id}/resolution", status_code=204)
    async def resolve_moderation_case(case_id: UUID, request: Request) -> Response:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        payload = cast(
            "ModerationResolutionRequest | None",
            await _submission_request(request, ModerationResolutionRequest),
        )
        if payload is None:
            return _error_response(422, "invalid_request")
        update_id = _submission_update_id(
            actor.member_id,
            case_id,
            "resolve",
            operation_key,
            namespace=b"moderation-resolution-v1",
        )
        fingerprint = _submission_fingerprint(
            "moderation_resolution",
            payload.expected_revision,
            payload={"code": payload.code.value, "reason": payload.reason},
        )
        try:
            await moderation.resolve(
                ResolveCaseCommand(
                    update_id=update_id,
                    actor_telegram_user_id=None,
                    case_id=case_id,
                    command_id=UUID(int=update_id),
                    expected_revision=payload.expected_revision,
                    code=payload.code,
                    reason=payload.reason,
                    actor_member_id=actor.member_id,
                    replay_fingerprint=fingerprint,
                    initial_dispute_only=True,
                )
            )
        except (LookupError, PermissionError, ModerationError, ModerationApplicationError):
            return _error_response(409, "moderation_unavailable")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.post(
        "/api/v1/tasks/{task_id}/assignments",
        response_model=AssignmentDto,
        status_code=201,
    )
    async def accept_task(task_id: str, request: Request) -> JSONResponse:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        try:
            parsed_task_id = UUID(task_id)
        except ValueError:
            return _error_response(422, "invalid_request")
        if str(parsed_task_id) != task_id:
            return _error_response(422, "invalid_request")
        try:
            body = await _bounded_body(request, limit=0)
        except (OverflowError, ValueError):
            return _error_response(422, "invalid_request")
        if body:
            return _error_response(422, "invalid_request")
        update_id = _accept_update_id(
            actor.member_id,
            parsed_task_id,
            operation_key,
        )
        try:
            assignment, _task = await assignments.accept_with_task(
                AcceptAssignmentCommand(
                    update_id=update_id,
                    actor_telegram_user_id=None,
                    task_id=parsed_task_id,
                    actor_member_id=actor.member_id,
                )
            )
        except (AssignmentError, LookupError, PermissionError, TaskError):
            return _error_response(409, "assignment_unavailable")
        return _json_response(
            AssignmentDto(
                id=assignment.id,
                task_id=assignment.task_id,
                slot_number=assignment.slot_number,
                status=assignment.status.value,
                accepted_at=assignment.accepted_at,
            ),
            status_code=201,
        )

    @app.post("/api/v1/assignments/{assignment_id}/submission-drafts")
    async def begin_submission_draft(assignment_id: str, request: Request) -> JSONResponse:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        parsed_assignment_id = _canonical_uuid(assignment_id)
        if parsed_assignment_id is None:
            return _error_response(422, "invalid_request")
        try:
            await _bounded_body(request, limit=0)
        except (OverflowError, ValueError):
            return _error_response(422, "invalid_request")
        try:
            draft = await assignments.begin_submission(
                BeginSubmissionCommand(
                    update_id=_submission_update_id(
                        actor.member_id, parsed_assignment_id, "begin", operation_key
                    ),
                    actor_telegram_user_id=None,
                    assignment_id=parsed_assignment_id,
                    actor_member_id=actor.member_id,
                    replay_fingerprint=_submission_fingerprint("begin"),
                )
            )
        except (AssignmentError, LookupError, PermissionError):
            return _error_response(409, "assignment_unavailable")
        return _json_response(_submission_draft_dto(draft))

    @app.put("/api/v1/submission-drafts/{draft_id}")
    async def save_submission_draft(draft_id: str, request: Request) -> JSONResponse:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        parsed_draft_id = _canonical_uuid(draft_id)
        if parsed_draft_id is None:
            return _error_response(422, "invalid_request")
        payload = cast(
            "SaveSubmissionDraftRequest | None",
            await _submission_request(request, SaveSubmissionDraftRequest),
        )
        if payload is None:
            return _error_response(422, "invalid_request")
        fingerprint = _submission_fingerprint(
            "save", payload.expected_revision, payload=payload.payload
        )
        try:
            draft = await assignments.save_submission_draft(
                SaveSubmissionDraftCommand(
                    update_id=_submission_update_id(
                        actor.member_id, parsed_draft_id, "save", operation_key
                    ),
                    actor_telegram_user_id=None,
                    draft_id=parsed_draft_id,
                    expected_revision=payload.expected_revision,
                    payload=payload.payload,
                    actor_member_id=actor.member_id,
                    replay_fingerprint=fingerprint,
                )
            )
        except (AssignmentError, LookupError, PermissionError):
            return _error_response(409, "assignment_unavailable")
        return _json_response(_submission_draft_dto(draft))

    @app.post("/api/v1/submission-drafts/{draft_id}/confirm", status_code=204)
    async def confirm_submission_draft(draft_id: str, request: Request) -> Response:
        _require_origin(request, origin)
        actor = await current_actor(request)
        operation_key = _idempotency_key(request)
        parsed_draft_id = _canonical_uuid(draft_id)
        if parsed_draft_id is None:
            return _error_response(422, "invalid_request")
        payload = cast(
            "ConfirmSubmissionDraftRequest | None",
            await _submission_request(request, ConfirmSubmissionDraftRequest),
        )
        if payload is None:
            return _error_response(422, "invalid_request")
        try:
            await assignments.confirm_submission_draft(
                ConfirmSubmissionDraftCommand(
                    update_id=_submission_update_id(
                        actor.member_id, parsed_draft_id, "confirm", operation_key
                    ),
                    actor_telegram_user_id=None,
                    draft_id=parsed_draft_id,
                    expected_revision=payload.expected_revision,
                    actor_member_id=actor.member_id,
                    replay_fingerprint=_submission_fingerprint(
                        "confirm", payload.expected_revision
                    ),
                )
            )
        except (AssignmentError, LookupError, PermissionError):
            return _error_response(409, "assignment_unavailable")
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/", include_in_schema=False)
    async def mini_app() -> HTMLResponse:
        return HTMLResponse(
            index_html,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self' https://telegram.org; "
                    "style-src 'self'; font-src 'self'; img-src 'none'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors https://web.telegram.org "
                    "https://*.telegram.org"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    app.mount("/mini-assets", StaticFiles(directory=_STATIC_DIR), name="mini-assets")
    return app


def validate_telegram_init_data(
    raw: bytes,
    *,
    bot_token: str,
    now: datetime.datetime | None = None,
) -> TelegramIdentity:
    """Validate raw Telegram Mini App initData and return its trusted identity."""
    if not raw or len(raw) > _PROOF_MAX_BYTES:
        raise ValueError("Invalid Telegram proof.")
    try:
        encoded = raw.decode("utf-8", errors="strict")
        pairs = parse_qsl(
            encoded,
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_PROOF_MAX_FIELDS,
            encoding="utf-8",
            errors="strict",
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("Invalid Telegram proof.") from error
    fields = dict(pairs)
    if len(fields) != len(pairs) or not {"hash", "auth_date", "user"} <= fields.keys():
        raise ValueError("Invalid Telegram proof.")
    supplied_hash = fields.pop("hash")
    if len(supplied_hash) != 64:
        raise ValueError("Invalid Telegram proof.")
    try:
        bytes.fromhex(supplied_hash)
    except ValueError as error:
        raise ValueError("Invalid Telegram proof.") from error
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_hash.lower(), expected_hash):
        raise ValueError("Invalid Telegram proof.")
    try:
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        telegram_user_id = user["id"]
        telegram_username = user.get("username")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("Invalid Telegram proof.") from error
    if isinstance(telegram_user_id, bool) or not isinstance(telegram_user_id, int):
        raise ValueError("Invalid Telegram proof.")
    if telegram_user_id < 1 or telegram_user_id > _MAX_TELEGRAM_USER_ID:
        raise ValueError("Invalid Telegram proof.")
    if telegram_username is not None and (
        not isinstance(telegram_username, str)
        or _TELEGRAM_USERNAME.fullmatch(telegram_username) is None
    ):
        raise ValueError("Invalid Telegram proof.")
    current = now or datetime.datetime.now(datetime.UTC)
    current_timestamp = int(current.timestamp())
    if (
        auth_date > current_timestamp + _PROOF_FUTURE_SKEW_SECONDS
        or current_timestamp - auth_date > _PROOF_MAX_AGE_SECONDS
    ):
        raise ValueError("Invalid Telegram proof.")
    return TelegramIdentity(telegram_user_id, telegram_username)


async def _bounded_body(request: Request, *, limit: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as error:
            raise ValueError("Invalid Content-Length.") from error
        if declared < 0:
            raise ValueError("Invalid Content-Length.")
        if declared > limit:
            raise OverflowError
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise OverflowError
        body.extend(chunk)
    return bytes(body)


def _web_config(settings: Settings) -> tuple[str, str]:
    bot_token = None if settings.bot_token is None else settings.bot_token.get_secret_value()
    origin = settings.mini_app_origin
    if not bot_token or not origin:
        raise ValueError("Web auth configuration is incomplete.")
    parsed = urlsplit(origin)
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Mini App origin is invalid.") from error
    scheme = parsed.scheme
    hostname = parsed.hostname
    local_development = (
        settings.environment == "development"
        and scheme == "http"
        and hostname in {"localhost", "127.0.0.1"}
    )
    canonical = f"{scheme}://{hostname}{'' if port is None else f':{port}'}"
    if (
        (scheme != "https" and not local_development)
        or hostname is None
        or "*" in hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or origin != canonical
    ):
        raise ValueError("Mini App origin is invalid.")
    return bot_token, origin


def _require_origin(request: Request, expected: str) -> None:
    if request.headers.getlist("origin") != [expected]:
        raise HTTPException(status_code=403, detail="invalid_origin")


def _idempotency_key(request: Request) -> str:
    values = request.headers.getlist("idempotency-key")
    if len(values) != 1:
        raise HTTPException(status_code=422, detail="invalid_idempotency_key")
    value = values[0]
    if (
        not value.isascii()
        or not value.isdecimal()
        or value.startswith("0")
        or len(value) > 19
        or int(value) > _MAX_IDEMPOTENCY_KEY
    ):
        raise HTTPException(status_code=422, detail="invalid_idempotency_key")
    return value


def _accept_update_id(member_id: UUID, task_id: UUID, operation_key: str) -> int:
    parts = (b"accept", member_id.bytes, task_id.bytes, operation_key.encode("ascii"))
    encoded = b"".join(len(part).to_bytes(2, "big") + part for part in parts)
    resolved = int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") & _MAX_IDEMPOTENCY_KEY
    return resolved or 1


def _submission_update_id(
    member_id: UUID,
    resource_id: UUID,
    operation: str,
    operation_key: str,
    namespace: bytes = b"submission-v1",
) -> int:
    parts = (
        namespace,
        operation.encode("ascii"),
        member_id.bytes,
        resource_id.bytes,
        operation_key.encode("ascii"),
    )
    encoded = b"".join(len(part).to_bytes(2, "big") + part for part in parts)
    resolved = int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big") & _MAX_IDEMPOTENCY_KEY
    return resolved or 1


def _submission_fingerprint(
    operation: str,
    expected_revision: int | None = None,
    *,
    payload: dict[str, object] | None = None,
) -> str:
    command = {"operation": operation, "expected_revision": expected_revision, "payload": payload}
    canonical = json.dumps(command, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _task_draft_json(draft: TaskDraft) -> dict[str, object]:
    fields = (
        "task_kind",
        "time_size",
        "title",
        "description",
        "completion_criteria",
        "credit_reward_per_performer",
        "deadline_at",
        "format",
        "city",
        "materials",
        "performer_slots",
    )
    values = {field: getattr(draft, field) for field in fields}
    values["category_id"] = None if draft.category_id is None else str(draft.category_id)
    return {
        "id": str(draft.id),
        "revision": draft.revision,
        "values": values,
    }


def _task_preview_json(preview: TaskPreview) -> dict[str, object]:
    return {
        "title": preview.draft.title,
        "description": preview.draft.description,
        "completion_criteria": preview.completion_criteria,
        "reward_total": preview.reserved_credit_total,
    }


def _canonical_uuid(value: str) -> UUID | None:
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return parsed if str(parsed) == value else None


async def _submission_request(
    request: Request,
    model: type[
        SaveSubmissionDraftRequest
        | ConfirmSubmissionDraftRequest
        | AssignmentDecisionRequest
        | AssignmentDisputeRequest
        | AssignmentCancellationRequest
        | ModerationResolutionRequest
    ],
) -> (
    SaveSubmissionDraftRequest
    | ConfirmSubmissionDraftRequest
    | AssignmentDecisionRequest
    | AssignmentDisputeRequest
    | AssignmentCancellationRequest
    | ModerationResolutionRequest
    | None
):
    if request.headers.get("content-type", "").lower() != "application/json":
        return None
    try:
        body = await _bounded_body(request, limit=_SUBMISSION_BODY_MAX_BYTES)
        return model.model_validate_json(body)
    except (OverflowError, ValueError, ValidationError):
        return None


def _assignment_cursor(cursor: tuple[datetime.datetime, UUID]) -> str:
    accepted_at, assignment_id = cursor
    timestamp = accepted_at.astimezone(datetime.UTC).isoformat().replace("+00:00", "Z")
    raw = f"{timestamp}|{assignment_id}".encode("ascii")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _parse_assignment_cursor(value: str | None) -> tuple[datetime.datetime, UUID] | None:
    if value is None:
        return None
    if not value.isascii() or not value or len(value) > 128 or "=" in value:
        raise ValueError("Invalid assignment cursor.")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True
        ).decode("ascii")
        timestamp, raw_id = raw.split("|", 1)
        accepted_at = datetime.datetime.fromisoformat(timestamp)
        assignment_id = UUID(raw_id)
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ValueError("Invalid assignment cursor.") from error
    if accepted_at.utcoffset() != datetime.timedelta(0) or str(assignment_id) != raw_id:
        raise ValueError("Invalid assignment cursor.")
    parsed = (accepted_at.astimezone(datetime.UTC), assignment_id)
    if _assignment_cursor(parsed) != value:
        raise ValueError("Invalid assignment cursor.")
    return parsed


def _session_digest(token: str | None) -> bytes | None:
    if token is None or len(token) != 43:
        return None
    try:
        raw = base64.b64decode(f"{token}=", altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != token:
        return None
    return hashlib.sha256(raw).digest()


def _member_query(query: str | None) -> str | None:
    if query is None or not query.strip():
        return None
    try:
        normalized = normalize_member_search_query(query)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="invalid_member_query") from error
    if normalized is None or len(normalized) > 80:
        raise HTTPException(status_code=422, detail="invalid_member_query")
    return normalized


def _karma_draft_dto(
    action: Literal["begin", "save_value", "save_comment"], draft: KarmaDraft
) -> KarmaActionDto:
    return KarmaActionDto(
        action=action,
        target_id=draft.target_id,
        step=draft.step.value,
        revision=draft.revision,
    )


def _karma_confirm_dto(target_id: UUID, result: KarmaVoteResult) -> KarmaActionDto:
    return KarmaActionDto(
        action="confirm",
        target_id=target_id,
        step="confirmed",
        revision=result.revision,
        aggregate=KarmaDto(score=result.aggregate_score, count=result.aggregate_count),
    )


def _member_dto(profile: SafeProfile) -> MemberDto:
    public_username = (
        profile.telegram_username
        if profile.telegram_username is not None
        and _TELEGRAM_USERNAME.fullmatch(profile.telegram_username) is not None
        else None
    )
    return MemberDto(
        member_id=profile.member_id,
        telegram_username=public_username,
        display_name=profile.display_name,
        city=profile.city,
        short_bio=profile.short_bio,
        skill_tags=profile.skill_tags,
        profile_links=tuple(
            ProfileLinkDto(id=item.id, label=item.label, url=item.url)
            for item in profile.profile_links
        ),
        experience_total=profile.experience_total,
        level_number=profile.level_number,
        karma=KarmaDto(score=profile.karma.score, count=profile.karma.count),
        reliability=ReliabilityDto(
            accepted=profile.reliability.accepted,
            approved_weight=profile.reliability.approved_weight,
            no_show=profile.reliability.no_show,
            rate=profile.reliability.rate,
        ),
    )


def _me_dto(profile: ProfileSnapshot, statistics: PersonalStatistics) -> MeDto:
    return MeDto(
        member_id=profile.member_id,
        telegram_username=profile.telegram_username,
        display_name=profile.display_name,
        city=profile.city,
        short_bio=profile.short_bio,
        skill_tags=profile.skill_tags,
        profile_links=tuple(
            ProfileLinkDto(id=item.id, label=item.label, url=item.url)
            for item in profile.profile_links
        ),
        credit_balance=profile.credit_balance,
        experience_total=profile.experience_total,
        level=LevelDto(
            number=profile.level.level_number,
            display_name=profile.level.display_name,
        ),
        statistics=ProfileStatisticsDto(
            completed_tasks=statistics.completed,
            created_tasks=statistics.created,
        ),
    )


def _task_dto(task: PublishedTask) -> TaskDto:
    return TaskDto(
        id=task.id,
        origin=task.origin,
        author_display_name=task.author_display_name,
        category_name=task.category_name,
        category_icon=task.category_icon,
        task_kind=None if task.task_kind is None else task.task_kind.value,
        time_size=None if task.time_size is None else task.time_size.value,
        title=task.title,
        credit_reward_per_performer=task.credit_reward_per_performer,
        performer_slots=task.performer_slots,
        minimum_level=task.minimum_level,
        format=task.format.value,
        city=task.city,
        deadline_at=task.deadline_at,
        status=task.status.value,
        description=task.description,
        completion_criteria=task.completion_criteria,
        performer_instructions=task.performer_instructions,
        materials={
            key: value
            for key in ("text", "url")
            if isinstance((value := task.materials.get(key)), str)
        },
        public_input={
            key: task.input_payload[key]
            for key in task.public_input_keys
            if key in task.input_payload
        },
    )


def _owned_task_dto(card: OwnedTaskCard) -> OwnedTaskDto:
    return OwnedTaskDto(
        id=card.task.id,
        title=card.task.title,
        status=card.task.status.value,
        performer_slots=card.task.performer_slots,
        deadline_at=card.task.deadline_at,
        assignees=tuple(
            OwnedTaskAssigneeDto(display_name=item.display_name, status=item.status)
            for item in card.assignees
        ),
        cancellation_status=card.cancellation_status,
        cancellation_action=card.cancellation_action,
    )


def _assignment_card_dto(card: AssignmentCard) -> AssignmentCardDto:
    assignment = card.assignment
    return AssignmentCardDto(
        id=assignment.id,
        task_id=assignment.task_id,
        task_title=card.task_title,
        task_origin=card.task_origin,
        assignment_status=assignment.status.value,
        accepted_at=assignment.accepted_at,
        submitted_at=assignment.submitted_at,
        review_deadline_at=assignment.review_deadline_at,
        reject_dispute_deadline_at=assignment.reject_dispute_deadline_at,
        reviewed_at=assignment.reviewed_at,
        task_deadline_at=card.task.deadline_at,
        result_summary=card.result_summary,
        case_status=card.case_status,
    )


def _assignment_detail_dto(card: AssignmentCard) -> AssignmentDetailDto:
    common = _assignment_card_dto(card).model_dump()
    task = card.task
    return AssignmentDetailDto(
        **common,
        category_name=task.category_name,
        category_icon=task.category_icon,
        task_kind=None if task.task_kind is None else task.task_kind.value,
        time_size=None if task.time_size is None else task.time_size.value,
        description=task.description,
        performer_instructions=task.performer_instructions,
        completion_criteria=task.completion_criteria,
        reward_per_performer=task.credit_reward_per_performer,
        format=task.format.value,
        city=task.city,
        minimum_level=task.minimum_level,
        performer_slots=task.performer_slots,
        submission_contract=cast('Literal["freeform_result_v1"] | None', card.submission_contract),
        can_submit=card.can_submit,
        can_cancel=card.can_cancel,
        can_dispute=card.can_dispute,
    )


def _assignment_review_dto(card: AssignmentCard) -> AssignmentReviewDto:
    if card.assignment.submitted_at is None or card.result_summary is None:
        raise ValueError("Assignment review projection is incomplete.")
    return AssignmentReviewDto(
        id=card.assignment.id,
        task_title=card.task_title,
        performer_display_name=card.performer_display_name,
        submitted_at=card.assignment.submitted_at,
        review_deadline_at=card.assignment.review_deadline_at,
        result=card.result_summary,
        available_decisions=card.available_decisions,
    )


def _submission_draft_dto(draft: SubmissionDraft) -> SubmissionDraftDto:
    value = None if draft.payload is None else draft.payload.get("result")
    result = value if isinstance(value, str) else None
    return SubmissionDraftDto(
        id=draft.id,
        revision=draft.revision,
        result=result,
    )


def _moderation_case_dto(case: ModerationCase) -> ModerationCaseDto:
    return ModerationCaseDto(
        id=case.id,
        assignment_id=case.assignment_id,
        case_type=case.case_type,
        status=cast('Literal["open", "appealed"]', case.status),
        revision=case.revision,
        current_code=None if case.current_code is None else case.current_code.value,
        opened_at=case.opened_at,
        resolved_at=case.resolved_at,
    )


def _moderation_case_detail_dto(detail: ModerationCaseDetail) -> ModerationCaseDetailDto:
    return ModerationCaseDetailDto(
        id=detail.case.id,
        status=cast('Literal["open"]', detail.case.status),
        revision=detail.case.revision,
        task_title=detail.task_title,
        task_origin=cast('Literal["member", "community"]', detail.task_origin),
        credit_reward_per_performer=detail.credit_reward_per_performer,
        assignment_status=detail.assignment_status,
        result_summary=detail.result_summary,
        dispute_reason=detail.dispute_reason,
        allowed_resolution_codes=detail.allowed_resolution_codes,
        opened_at=detail.case.opened_at,
    )


def _json_response(model: object, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        model.model_dump(mode="json") if isinstance(model, BaseModel) else jsonable_encoder(model),
        status_code=status_code,
        headers={"Cache-Control": "no-store"},
    )


def _error_response(status_code: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"code": code}, status_code=status_code, headers={"Cache-Control": "no-store"}
    )
