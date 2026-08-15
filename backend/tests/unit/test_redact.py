"""外发 LLM 脱敏测试 — redact() 纯函数覆盖手机号/身份证/银行卡/邮箱."""

from app.core.redact import redact


class TestRedactPhone:
    """手机号（1[3-9]\\d{9}）脱敏：保留前 3 后 4."""

    def test_phone_masked(self) -> None:
        out = redact("联系人电话：13812341234，请提前联系。")
        assert "13812341234" not in out, "脱敏后不得包含完整手机号"
        assert "138****1234" in out, "手机号应保留前3后4，中间以 **** 占位"

    def test_phone_multiple(self) -> None:
        out = redact("甲 13912345678 / 乙 15087654321")
        assert "13912345678" not in out
        assert "15087654321" not in out
        assert "139****5678" in out
        assert "150****4321" in out

    def test_phone_inside_longer_digit_run_not_masked(self) -> None:
        """更长数字串（超出银行卡 16-19 位）内部的 11 位子串不应被当作手机号误伤."""
        text = "订单流水号 20261381234123400019 请核对"
        assert redact(text) == text


class TestRedactIdCard:
    """身份证号（18 位，末位可为 X/x，校验位宽松匹配）脱敏."""

    def test_id_card_masked(self) -> None:
        out = redact("项目经理身份证：11010119900307123X。")
        assert "11010119900307123X" not in out, "脱敏后不得包含完整身份证号"
        assert "110101" in out, "身份证应保留前 6 位地区码"
        assert "123X" in out, "身份证应保留末 4 位"
        assert "*" in out

    def test_id_card_digit_tail(self) -> None:
        out = redact("身份证号 110101199003071234 已登记")
        assert "110101199003071234" not in out
        assert "110101" in out and "1234" in out


class TestRedactBankCard:
    """银行卡号（16-19 位数字）脱敏：保留末 4 位."""

    def test_bank_19_digits(self) -> None:
        out = redact("对公账号卡号 6222021234561234567 用于收款。")
        assert "6222021234561234567" not in out, "脱敏后不得包含完整银行卡号"
        assert "4567" in out, "银行卡号应保留末 4 位"
        assert "*" in out

    def test_bank_16_digits(self) -> None:
        out = redact("卡号：6228480000000000，请核验。")
        assert "6228480000000000" not in out
        assert "0000" in out and "*" in out


class TestRedactEmail:
    """邮箱脱敏：隐藏本地部分."""

    def test_email_masked(self) -> None:
        out = redact("联系人邮箱 zhangsan@example.com 抄送即可。")
        assert "zhangsan@example.com" not in out, "脱敏后不得包含完整邮箱"
        assert "zhangsan" not in out, "邮箱本地部分不得完整保留"
        assert "@example.com" in out, "域名可保留"
        assert "*" in out


class TestRedactSafety:
    """普通文本不被误伤；纯函数无副作用."""

    def test_plain_chinese_untouched(self) -> None:
        text = "本方案采用微服务架构，支持高并发与弹性伸缩，满足招标文件全部技术要求。"
        assert redact(text) == text

    def test_short_numbers_untouched(self) -> None:
        text = "项目工期 365 天，预算 1234567 元，评分 60 分。"
        assert redact(text) == text

    def test_empty_string(self) -> None:
        assert redact("") == ""

    def test_pure_function_no_side_effect(self) -> None:
        text = "电话 13812341234"
        r1 = redact(text)
        r2 = redact(text)
        assert r1 == r2
        assert text == "电话 13812341234", "redact 不得修改入参语义"
