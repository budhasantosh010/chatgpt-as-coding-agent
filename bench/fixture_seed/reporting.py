def parse_currency(value: str) -> float:
    return float(value.strip().lstrip("$"))


def report_total(values: list[str]) -> float:
    return sum(parse_currency(value) for value in values)
