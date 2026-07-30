from typing import Optional
from pydantic import BaseModel


class RegisterRequest(BaseModel):
    email: str
    password: str
    captcha_token: Optional[str] = None  # TODO: validate via hCaptcha/reCAPTCHA once Alex adds site key


class LoginRequest(BaseModel):
    email: str
    password: str
    captcha_token: Optional[str] = None  # TODO: validate via hCaptcha/reCAPTCHA once Alex adds site key


class MeResponse(BaseModel):
    role: str              # "guest" | "user" | "admin"
    id: Optional[int] = None
    email: Optional[str] = None
    display_name: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
