"""外发 LLM 脱敏 — 敏感信息出口兜底（项目安全铁律，默认强制开启，无开关）."""

import re

# 顺序敏感：身份证（18 位含 X）→ 银行卡（16-19 位）→ 手机号 → 邮箱。
# 均以数字边界环视约束，避免误伤更长数字串内部的子串。
_ID_CARD_RE = re.compile(r"(?<!\d)(\d{6})\d{8}(\d{3}[\dXx])(?![\dXx])")
_BANK_CARD_RE = re.compile(r"(?<!\d)\d{12,15}(\d{4})(?!\d)")
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def redact(text: str) -> str:
    """对文本中的手机号/身份证号/银行卡号/邮箱执行脱敏，返回新字符串（纯函数）.

    占位规则：
    - 手机号：保留前 3 后 4，如 138****1234
    - 身份证号：保留前 6 后 4，中间 8 位以 * 占位
    - 银行卡号：仅保留末 4 位，其余以 * 占位
    - 邮箱：本地部分仅保留首字符，其余以 *** 占位，域名保留
    """
    if not text:
        return text
    text = _ID_CARD_RE.sub(lambda m: f"{m.group(1)}********{m.group(2)}", text)
    text = _BANK_CARD_RE.sub(lambda m: f"{'*' * (len(m.group(0)) - 4)}{m.group(1)}", text)
    text = _PHONE_RE.sub(lambda m: f"{m.group(1)}****{m.group(2)}", text)
    text = _EMAIL_RE.sub(lambda m: f"{m.group(1)}***{m.group(2)}", text)
    return text
