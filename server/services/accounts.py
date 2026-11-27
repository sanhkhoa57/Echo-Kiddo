"""Account registration shared by the web form and JSON API."""
from io import BytesIO
import re
from typing import BinaryIO

from PIL import Image, ImageOps
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.auth.security import get_password_hash
from server.models.account_profile import AccountProfile
from server.models.user import User

AVATAR_COLORS = {"forest": "Xanh rêu", "blue": "Xanh lam", "plum": "Tím mận", "brick": "Đỏ gạch"}
MAX_AVATAR_BYTES = 3 * 1024 * 1024


class EmailInUse(ValueError):
    pass


def valid_profile_phone(phone: str) -> bool:
    return not phone or (
        len(phone) <= 32
        and re.fullmatch(r"\+?[0-9 ().-]+", phone) is not None
        and 7 <= sum(char.isdigit() for char in phone) <= 15
    )


def prepare_avatar(file: BinaryIO) -> bytes | None:
    data = file.read(MAX_AVATAR_BYTES + 1)
    if not data:
        return None
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError("Ảnh đại diện tối đa 3 MB.")
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as image:
            if image.width * image.height > 16_000_000:
                raise ValueError("Ảnh đại diện quá lớn. Hãy chọn ảnh nhỏ hơn.")
            square = ImageOps.fit(ImageOps.exif_transpose(image).convert("RGBA"), (256, 256))
            background = Image.new("RGB", square.size, "#eef3f0")
            background.paste(square, mask=square.getchannel("A"))
            output = BytesIO()
            background.save(output, "JPEG", quality=88, optimize=True)
            return output.getvalue()
    except (OSError, Image.DecompressionBombError, SyntaxError):
        raise ValueError("Hãy chọn ảnh JPG, PNG hoặc WebP hợp lệ.") from None


def find_account(db: Session, email: str) -> User | None:
    email = email.strip().lower()
    exact = db.scalar(select(User).where(User.email == email))
    if exact is not None:
        return exact
    # Keep login working for accounts registered before email normalization.
    return db.scalar(select(User).where(func.lower(User.email) == email))


def create_parent_account(db: Session, email: str, password: str, display_name: str = "") -> User:
    if find_account(db, email):
        raise EmailInUse
    user = User(email=email.strip().lower(), password_hash=get_password_hash(password), role="parent")
    if display_name:
        user.profile = AccountProfile(display_name=display_name)
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if find_account(db, email):
            raise EmailInUse from None
        raise
    return user
