import uuid

from pydantic import BaseModel, Field


class OtpRequestIn(BaseModel):
    phone: str = Field(min_length=10, max_length=20)


class OtpRequestOut(BaseModel):
    phone: str
    expires_in_seconds: int


class OtpVerifyIn(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(pattern=r"^\d{4,8}$")


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None
    preferred_language: str
    roles: list[str]


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
