from copy import deepcopy


class ShareError(ValueError):
    pass


def distribute(offers):
    """Keep pinned integer percentages; spread the remainder deterministically."""
    result = deepcopy(offers)
    active = [offer for offer in result if not offer.get("removed", False)]
    if not active:
        raise ShareError("Нельзя удалить последний активный оффер потока.")
    pinned = [offer for offer in active if offer.get("pinned", False)]
    free = [offer for offer in active if not offer.get("pinned", False)]
    for offer in active:
        if isinstance(offer["share"], bool) or not isinstance(offer["share"], int) or not 0 <= offer["share"] <= 100:
            raise ShareError("Доля должна быть целым числом от 0 до 100.")
    remaining = 100 - sum(offer["share"] for offer in pinned)
    if remaining < 0:
        raise ShareError("Сумма закреплённых долей превышает 100%.")
    if not free and remaining:
        raise ShareError("Все доли закреплены, но их сумма не равна 100%. Освободите одну долю.")
    if free and remaining < len(free):
        raise ShareError("Для каждого незакреплённого оффера нужен хотя бы 1%. Освободите часть закреплённых долей.")
    if free:
        share, extra = divmod(remaining, len(free))
        for index, offer in enumerate(free):
            offer["share"] = share + (index < extra)
    for offer in result:
        if offer.get("removed", False):
            offer["share"] = 0
            offer["pinned"] = False
    return result
