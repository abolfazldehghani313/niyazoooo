from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class OTPRequest(BaseModel):
    phone: str = Field(min_length=10, max_length=20, examples=["09123456789"])

class OTPVerify(BaseModel):
    phone: str = Field(min_length=10, max_length=20)
    code: str = Field(min_length=6, max_length=6)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    phone: str

class AdCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(default="", max_length=10000)
    price: int | None = Field(default=None, ge=0)
    city: str = Field(default="", max_length=80)
    category: str = Field(default="عمومی", max_length=80)

class AdOut(BaseModel):
    id: int
    title: str
    description: str
    price: int | None
    city: str
    category: str
    owner_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
