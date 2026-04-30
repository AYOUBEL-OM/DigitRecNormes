"""
Schémas Pydantic : reset mot de passe (entreprise).
"""

from pydantic import BaseModel, EmailStr, Field


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=5000)
    new_password: str = Field(..., min_length=8, max_length=72)
