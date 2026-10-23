import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPPORTED_CURRENCIES = ("BRL", "CLP", "USD", "EUR")
CURRENCY_NAMES = {
    "BRL": "Real brasileiro",
    "CLP": "Peso chileno",
    "USD": "Dólar americano",
    "EUR": "Euro",
}


class ExchangeRateError(Exception):
    pass


def get_historical_rate(currency, requested_date):
    currency = (currency or "").strip().upper()
    if currency not in SUPPORTED_CURRENCIES or currency == "BRL":
        raise ExchangeRateError("Moeda sem cotação externa disponível.")

    if isinstance(requested_date, datetime):
        requested_date = requested_date.date()
    elif isinstance(requested_date, str):
        try:
            requested_date = datetime.strptime(requested_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ExchangeRateError("A data da cotação é inválida.") from exc
    if not isinstance(requested_date, date):
        raise ExchangeRateError("A data da cotação é inválida.")

    url = (
        f"https://api.frankfurter.dev/v2/rate/{currency.lower()}/brl"
        f"?date={requested_date.isoformat()}"
    )
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "ControleViagem/1.0"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            raise ExchangeRateError(
                f"Não há cotação de {currency} para {requested_date.strftime('%d/%m/%Y')} na fonte consultada."
            ) from exc
        raise ExchangeRateError("A fonte de cotações está indisponível no momento.") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise ExchangeRateError("Não foi possível consultar a fonte de cotações.") from exc

    try:
        rate = Decimal(str(payload["rate"]))
        effective_date = datetime.strptime(payload["date"], "%Y-%m-%d").date()
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ExchangeRateError("A fonte retornou uma cotação inválida.") from exc
    if not rate.is_finite() or rate <= 0 or payload.get("base", "").upper() != currency:
        raise ExchangeRateError("A fonte retornou uma cotação inválida.")

    return {
        "currency": currency,
        "base": currency,
        "quote": "BRL",
        "rate": rate,
        "date": effective_date.isoformat(),
    }