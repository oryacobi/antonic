import re
from typing import Any, Callable, Type

CollectionNamingStrategy = Callable[[Type[Any]], str]


def snake_case(name: str) -> str:
    first_pass = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub("([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


def simple_plural(word: str) -> str:
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def default_collection_name(entity_type: Type[Any]) -> str:
    return simple_plural(snake_case(entity_type.__name__))
