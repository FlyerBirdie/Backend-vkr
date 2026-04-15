"""
Pydantic-схемы для API: заказы, запрос/ответ планирования (явный плановый период UTC).
"""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Аутентификация (роль planner) ---
class LoginRequest(BaseModel):
    username: str = Field(description="Имя пользователя планировщика.")
    password: str = Field(description="Пароль (в продакшене сверяется с bcrypt-хэшем).")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "planner"


class OrderResponse(BaseModel):
    """Схема ответа с заказом."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    profit: Decimal
    planned_start: datetime
    planned_end: datetime
    tech_process_id: int


class OrderUpdate(BaseModel):
    """Частичное обновление заказа (все поля опциональны)."""

    name: str | None = None
    profit: Decimal | None = None
    planned_start: datetime | None = None
    planned_end: datetime | None = None
    tech_process_id: int | None = None

    @model_validator(mode="after")
    def planned_window(self) -> "OrderUpdate":
        if self.planned_start is not None and self.planned_end is not None:
            if self.planned_end <= self.planned_start:
                raise ValueError("planned_end должен быть позже planned_start.")
        return self


# --- Worker ---
class WorkerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    profession: str = Field(min_length=1, max_length=100)


class WorkerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    profession: str | None = Field(default=None, min_length=1, max_length=100)


class WorkerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    profession: str


# --- Equipment ---
class EquipmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=100, description="Модель для сопоставления с Task.equipment_model.")


class EquipmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    model: str | None = Field(default=None, min_length=1, max_length=100)


class EquipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    model: str


# --- TechProcess / Task ---
class TechProcessCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class TechProcessUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class TaskCreate(BaseModel):
    sequence_number: int = Field(ge=1)
    duration_minutes: int = Field(ge=1)
    profession: str = Field(min_length=1, max_length=100)
    equipment_model: str = Field(min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=255)


class TaskUpdate(BaseModel):
    sequence_number: int | None = Field(default=None, ge=1)
    duration_minutes: int | None = Field(default=None, ge=1)
    profession: str | None = Field(default=None, min_length=1, max_length=100)
    equipment_model: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, max_length=255)


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tech_process_id: int
    sequence_number: int
    duration_minutes: int
    profession: str
    equipment_model: str
    name: str | None


class TechProcessListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TechProcessDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    tasks: list[TaskResponse]


# --- Order: расширенная валидация для POST ---
class OrderCreate(BaseModel):
    """Схема создания заказа."""

    name: str = Field(min_length=1, max_length=255)
    profit: Decimal
    planned_start: datetime
    planned_end: datetime
    tech_process_id: int

    @model_validator(mode="after")
    def planned_window(self) -> "OrderCreate":
        if self.planned_end <= self.planned_start:
            raise ValueError("planned_end должен быть позже planned_start.")
        return self


class ScheduleRequest(BaseModel):
    """
    Параметры расчёта расписания. Моменты периода — абсолютное время в ISO-8601 с явным offset
    (например `...+04:00` для Самары или `Z` для UTC); наивные datetime не принимаются проверкой 422.

    Если оба поля периода не заданы, используется период по умолчанию (см. описание POST /api/schedule).
    """

    period_start: datetime | None = Field(
        default=None,
        description="Начало планового периода (timezone-aware ISO-8601). Вместе с period_end или оба пустые.",
    )
    period_end: datetime | None = Field(
        default=None,
        description="Конец планового периода (timezone-aware). Операции не выходят за min(period_end, planned_end заказа).",
    )

    @model_validator(mode="after")
    def period_both_or_neither(self) -> "ScheduleRequest":
        if (self.period_start is None) ^ (self.period_end is None):
            raise ValueError(
                "Укажите оба поля period_start и period_end или оставьте оба незаполненными "
                "(будет использован период по умолчанию)."
            )
        if self.period_start is not None and self.period_end is not None:
            if self.period_end <= self.period_start:
                raise ValueError("period_end должен быть позже period_start.")
        return self


class IncludedOrderItem(BaseModel):
    """Заказ, полностью вошедший в расписание (принцип «всё или ничё»)."""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Идентификатор заказа.")
    name: str
    profit: Decimal


class ScheduleIssueItem(BaseModel):
    """Запись для отчёта и клиентов: код, уровень, сообщение, привязка к сущностям."""

    level: Literal["error", "warning"] = Field(description="error — блокирует расчёт (только в ответе 422); warning — предупреждение или исключение заказа при 200.")
    code: str = Field(
        description=(
            "Стабильный код, например TASK_NO_MATCHING_WORKER или "
            "SCHEDULE_EXCLUDED_OUTSIDE_PERIOD / SCHEDULE_EXCLUDED_NO_PAIR / SCHEDULE_EXCLUDED_TIME_CONFLICT."
        ),
    )
    message: str
    tech_process_id: int | None = None
    tech_process_name: str | None = None
    task_id: int | None = None
    order_id: int | None = None
    order_name: str | None = None


class ExcludedOrderItem(BaseModel):
    """Заказ, исключённый из расписания, с пояснением."""
    order_id: int
    order_name: str
    code: str = Field(description="Машиночитаемый код причины (совпадает с issue.code для этого заказа).")
    reason: str = Field(description="Причина исключения (ресурсы, окно, пересечение с периодом и т.д.).")


class ScheduledOperationItem(BaseModel):
    """Один элемент расписания — запланированная операция."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    order_name: str
    task_id: int
    task_name: str | None
    sequence_number: int
    worker_id: int
    worker_name: str
    worker_profession: str
    equipment_id: int
    equipment_name: str
    equipment_model: str
    start_time: datetime = Field(description="Начало операции, UTC (ISO-8601 в JSON).")
    end_time: datetime = Field(description="Окончание операции, UTC (ISO-8601 в JSON).")


class ResourceUtilizationRow(BaseModel):
    """Загрузка одного ресурса в плановом периоде (см. backend/schedule_metrics.py)."""

    id: int
    name: str
    detail: str = Field(description="Профессия (worker) или модель (equipment).")
    busy_minutes: float = Field(description="Сумма длительностей операций на ресурсе, мин.")
    available_minutes: int = Field(
        description="T_avail — сумма минут рабочих окон календаря участка внутри периода (одинакова для всех в MVP)."
    )
    utilization_percent: float = Field(ge=0, le=100, description="T_busy / T_avail · 100%, не выше 100.")
    idle_percent: float = Field(ge=0, le=100, description="100 − загрузка.")


class AggregateUtilizationMetrics(BaseModel):
    """Сводные показатели по справочнику Worker / Equipment."""

    workers_mean_utilization_percent: float = Field(description="Среднее U по всем рабочим (вкл. 0% без операций).")
    equipment_mean_utilization_percent: float = Field(description="Среднее U по всем единицам оборудования.")
    total_busy_minutes_sum_workers: float = Field(
        description="Сумма минут занятости по всем рабочим (может быть > T_avail при параллельной работе)."
    )
    total_busy_minutes_sum_equipment: float
    pool_worker_load_percent: float = Field(
        description="Агрегат «ванна»: Σ busy по рабочим / (N_рабочих · T_avail) · 100%."
    )
    pool_equipment_load_percent: float = Field(
        description="Агрегат: Σ busy по оборудованию / (N_ед · T_avail) · 100%."
    )


class BottleneckItem(BaseModel):
    """Узкое место MVP: экстремум по загрузке среди worker ∪ equipment."""

    resource_kind: Literal["worker", "equipment"]
    id: int
    name: str
    utilization_percent: float
    role: Literal["high_load", "high_idle"]


class ScheduleReportMetrics(BaseModel):
    """
    Метрики демо/ВКР для одного прогона планирования.
    Времена периода — timezone-aware, в JSON сериализуются как ISO-8601.
    """

    period_start: datetime = Field(description="Начало планового периода (UTC).")
    period_end: datetime = Field(description="Конец планового периода (UTC).")
    available_minutes_per_resource: int = Field(
        description="T_avail в минутах на каждый ресурс (календарь участка внутри периода)."
    )
    workers: list[ResourceUtilizationRow]
    equipment: list[ResourceUtilizationRow]
    aggregate: AggregateUtilizationMetrics
    bottlenecks_highest_load: list[BottleneckItem] = Field(
        description="До 3 ресурсов с наибольшей загрузкой.",
    )
    bottlenecks_highest_idle: list[BottleneckItem] = Field(
        description="До 3 ресурсов с наименьшей загрузкой (наибольший простой).",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Текстовые заглушки для отчёта (без ИИ на бэкенде).",
    )


class ScheduleResponse(BaseModel):
    """
    Результат планирования: расписание, заказы, прибыль, метрики загрузки, узкие места, заглушки рекомендаций.
    Даты/время в JSON — ISO-8601 (timezone-aware UTC).
    """

    period_start: datetime = Field(description="Фактически использованное начало планового периода (UTC).")
    period_end: datetime = Field(description="Фактически использованный конец планового периода (UTC).")
    included_orders: list[IncludedOrderItem] = Field(
        description="Заказы, для которых размещены все операции ТП в допустимом окне.",
    )
    excluded_orders: list[ExcludedOrderItem] = Field(
        default_factory=list,
        description="Заказы, не вошедшие в расписание целиком, с причиной.",
    )
    total_profit: Decimal = Field(description="Сумма profit по включённым заказам.")
    operations: list[ScheduledOperationItem] = Field(
        description="Запланированные операции (все внутри period и окна заказа).",
    )
    issues: list[ScheduleIssueItem] = Field(
        default_factory=list,
        description="Предупреждения проверки данных и записи по исключённым заказам (код + контекст).",
    )
    report_summary: str = Field(
        default="",
        description="Краткий человекочитаемый отчёт для агента или оператора.",
    )
    metrics: ScheduleReportMetrics = Field(
        description="Загрузка персонала и оборудования, агрегаты, узкие места, рекомендации-заглушки.",
    )


class PlanningValidationErrorContent(BaseModel):
    """Тело поля `detail` при HTTP 422 (ошибки проверки данных перед планированием)."""

    error: Literal["planning_validation_failed"] = "planning_validation_failed"
    errors: list[ScheduleIssueItem] = Field(description="Блокирующие ошибки (уровень error).")
    warnings: list[ScheduleIssueItem] = Field(
        default_factory=list,
        description="Предупреждения (не блокируют при успешной схеме ответа; здесь — до исправления ошибок).",
    )
    report_summary: str = Field(description="Сводка для отчёта.")
