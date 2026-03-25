from typing import Literal

from pydantic import BaseModel, Field


class AdaptInOut(BaseModel):
    number: int = Field(description="what_number（負数は末尾から）")
    week: int = Field(
        ge=-1,
        le=6,
        description="order_week（0=日…6=土、-1=曜日指定なし）",
    )


class AvoidInOut(BaseModel):
    holiday: bool = False
    sun: bool = False
    mon: bool = False
    tue: bool = False
    wed: bool = False
    thu: bool = False
    fri: bool = False
    sat: bool = False


class AdjustInOut(BaseModel):
    avoid: AvoidInOut
    alt: Literal[1, -1] = Field(description="1=未来方向、-1=過去方向")


class RoutineListItem(BaseModel):
    id: int
    title: str
    activity_category_id: int
    activity_category_name: str
    adapt: AdaptInOut
    adjust: AdjustInOut | None = None


class CategoryItem(BaseModel):
    id: int
    name: str


class RoutineCreateRequest(BaseModel):
    title: str
    activity_category_id: int
    adapt: AdaptInOut
    adjust: AdjustInOut | None = None


class RoutineCreateResponse(BaseModel):
    id: int


class YearMonthBody(BaseModel):
    year: int = Field(ge=1, le=9999)
    month: int = Field(ge=1, le=12)


class ApplyResponse(BaseModel):
    inserted_count: int
    dates: list[str] = Field(description="登録した日付（YYYY-MM-DD）")
    errors: list[str] = Field(
        default_factory=list,
        description="apply-all 時など、スキップ・失敗したルーティンのメッセージ",
    )


class MessageResponse(BaseModel):
    message: str
