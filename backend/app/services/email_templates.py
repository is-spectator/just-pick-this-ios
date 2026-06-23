from __future__ import annotations


def login_code_subject() -> str:
    return "你的就选这个登录验证码"


def login_code_text(code: str) -> str:
    return f"验证码：{code}\n10 分钟内有效。\n如果不是你操作，请忽略。"
