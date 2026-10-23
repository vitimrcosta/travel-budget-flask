import re


_COUNTRY_CODE_PATTERN = re.compile(r"^[A-Za-z]{2}$")
_LEGACY_FLAG_PATTERN = re.compile(r"^[\U0001F1E6-\U0001F1FF]{2}$")


def normalize_country_code(value, strict=True):
    if value is None:
        return ""
    if not isinstance(value, str):
        if strict:
            raise ValueError("Selecione um país da lista.")
        return ""

    value = value.strip()
    if not value:
        return ""
    if _COUNTRY_CODE_PATTERN.fullmatch(value):
        return value.upper()
    if _LEGACY_FLAG_PATTERN.fullmatch(value):
        return "".join(chr(ord(character) - 0x1F1E6 + ord("A")) for character in value)
    if strict:
        raise ValueError("Selecione um país da lista.")
    return ""
