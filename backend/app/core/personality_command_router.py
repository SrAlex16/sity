import re
import unicodedata
from dataclasses import dataclass
from typing import Optional


PARAMETER_ALIASES = {
    "sarcasmo": "sarcasm_level",
    "mala leche": "rudeness_level",
    "borde": "rudeness_level",
    "borderia": "rudeness_level",
    "bordería": "rudeness_level",
    "calidez": "warmth_level",
    "amabilidad": "warmth_level",
    "honestidad": "honesty_level",
    "sinceridad": "honesty_level",
    "iniciativa": "initiative_level",
    "humor seco": "dry_humor_level",
    "tsundere": "tsundere_level",
    "contradiccion": "contrarian_level",
    "contradicción": "contrarian_level",
    "contraria": "contrarian_level",
    "paciencia": "patience_level",
    "negacion": "refusal_chance",
    "negación": "refusal_chance",
    "negarte": "refusal_chance",
    "negativa": "refusal_chance",
    "ayuda": "helpfulness_level",
    "utilidad": "helpfulness_level",
    "verbosidad": "verbosity_level",
    "longitud": "verbosity_level",
}


DISPLAY_NAMES = {
    "sarcasm_level": "sarcasmo",
    "rudeness_level": "mala leche",
    "warmth_level": "calidez",
    "honesty_level": "honestidad",
    "initiative_level": "iniciativa",
    "dry_humor_level": "humor seco",
    "tsundere_level": "modo tsundere",
    "contrarian_level": "contradicción",
    "patience_level": "paciencia",
    "refusal_chance": "probabilidad de negarse",
    "helpfulness_level": "nivel de ayuda",
    "verbosity_level": "verbosidad",
}


@dataclass
class PersonalityUpdate:
    parameter: str
    operation: str
    amount: float


@dataclass
class PersonalityCommand:
    updates: list[PersonalityUpdate]
    matched_text: str
    kind: str


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value)
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def normalize_text(value: str) -> str:
    return strip_accents(value.lower().strip())


def parse_personality_command(message: str) -> Optional[PersonalityCommand]:
    normalized = normalize_text(message)

    preset = parse_preset(normalized)
    if preset:
        return preset

    single = parse_single_update(normalized)
    if single:
        return single

    return None


def parse_preset(normalized: str) -> Optional[PersonalityCommand]:
    all_params_match = re.search(
        r"(?:mant[eé]n|pon|ajusta|establece|setea|deja)\s+(?:todos|todo|todos los parametros|todos los parámetros|la personalidad|los parametros|los parámetros)\s+(?:al|a|en)\s+(?P<value>\d{1,3})\s*%?",
        normalized,
    )

    if all_params_match:
        raw_value = int(all_params_match.group("value"))
        if raw_value < 0 or raw_value > 100:
            return None

        value = raw_value / 100

        return PersonalityCommand(
            kind="preset_all_parameters",
            matched_text=normalized,
            updates=[
                PersonalityUpdate("sarcasm_level", "set_absolute", value),
                PersonalityUpdate("rudeness_level", "set_absolute", value),
                PersonalityUpdate("warmth_level", "set_absolute", value),
                PersonalityUpdate("honesty_level", "set_absolute", value),
                PersonalityUpdate("initiative_level", "set_absolute", value),
                PersonalityUpdate("dry_humor_level", "set_absolute", value),
                PersonalityUpdate("tsundere_level", "set_absolute", value),
                PersonalityUpdate("contrarian_level", "set_absolute", value),
                PersonalityUpdate("patience_level", "set_absolute", value),
                PersonalityUpdate("refusal_chance", "set_absolute", value),
                PersonalityUpdate("helpfulness_level", "set_absolute", value),
                PersonalityUpdate("verbosity_level", "set_absolute", value),
            ],
        )

    if any(phrase in normalized for phrase in ["equilibra tu personalidad", "personalidad equilibrada", "modo equilibrado", "resetea la personalidad"]):
        return PersonalityCommand(
            kind="preset_balanced",
            matched_text=normalized,
            updates=[
                PersonalityUpdate("sarcasm_level", "set_absolute", 0.50),
                PersonalityUpdate("rudeness_level", "set_absolute", 0.50),
                PersonalityUpdate("warmth_level", "set_absolute", 0.50),
                PersonalityUpdate("honesty_level", "set_absolute", 0.50),
                PersonalityUpdate("initiative_level", "set_absolute", 0.50),
                PersonalityUpdate("dry_humor_level", "set_absolute", 0.50),
                PersonalityUpdate("tsundere_level", "set_absolute", 0.50),
                PersonalityUpdate("contrarian_level", "set_absolute", 0.50),
                PersonalityUpdate("patience_level", "set_absolute", 0.50),
                PersonalityUpdate("refusal_chance", "set_absolute", 0.50),
                PersonalityUpdate("helpfulness_level", "set_absolute", 0.50),
                PersonalityUpdate("verbosity_level", "set_absolute", 0.50),
            ],
        )

    # "Hazte más insoportable", "modifica todo para ser más borde", etc.
    if any(word in normalized for word in ["insoportable", "mas borde", "más borde", "cabrona", "cabron", "insufrible"]):
        return PersonalityCommand(
            kind="preset_insoportable",
            matched_text=normalized,
            updates=[
                PersonalityUpdate("sarcasm_level", "set_absolute", 0.95),
                PersonalityUpdate("rudeness_level", "set_absolute", 0.85),
                PersonalityUpdate("warmth_level", "set_absolute", 0.10),
                PersonalityUpdate("dry_humor_level", "set_absolute", 0.90),
                PersonalityUpdate("tsundere_level", "set_absolute", 0.85),
                PersonalityUpdate("contrarian_level", "set_absolute", 0.90),
                PersonalityUpdate("patience_level", "set_absolute", 0.15),
                PersonalityUpdate("helpfulness_level", "set_absolute", 0.55),
                PersonalityUpdate("verbosity_level", "set_absolute", 0.25),
            ],
        )

    if any(word in normalized for word in ["mas amable", "más amable", "mas suave", "más suave", "menos borde"]):
        return PersonalityCommand(
            kind="preset_amable",
            matched_text=normalized,
            updates=[
                PersonalityUpdate("sarcasm_level", "set_absolute", 0.25),
                PersonalityUpdate("rudeness_level", "set_absolute", 0.10),
                PersonalityUpdate("warmth_level", "set_absolute", 0.85),
                PersonalityUpdate("dry_humor_level", "set_absolute", 0.20),
                PersonalityUpdate("contrarian_level", "set_absolute", 0.25),
                PersonalityUpdate("patience_level", "set_absolute", 0.80),
                PersonalityUpdate("helpfulness_level", "set_absolute", 0.90),
            ],
        )

    return None


def parse_single_update(normalized: str) -> Optional[PersonalityCommand]:
    # Absoluto:
    # "pon sarcasmo al 70"
    # "cambia la calidez a 20%"
    absolute_patterns = [
        r"(?:pon|ponme|cambia|ajusta|establece|setea)\s+(?:el|la|los|las|mi|tu)?\s*(?P<name>[a-zñ ]+?)\s+(?:al|a|en)\s+(?P<value>\d{1,3})\s*%?",
        r"(?P<name>[a-zñ ]+?)\s+(?:al|a|en)\s+(?P<value>\d{1,3})\s*%?",
    ]

    for pattern in absolute_patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue

        parameter = find_parameter(match.group("name"))
        if not parameter:
            continue

        raw_value = int(match.group("value"))
        if raw_value < 0 or raw_value > 100:
            return None

        return PersonalityCommand(
            kind="single_absolute",
            matched_text=match.group(0),
            updates=[
                PersonalityUpdate(parameter, "set_absolute", raw_value / 100),
            ],
        )

    # Relativo absoluto:
    # "baja la calidez un 30%" => -0.30
    # "sube el sarcasmo un 20%" => +0.20
    relative_pattern = r"(?P<verb>sube|aumenta|baja|reduce)\s+(?:el|la|los|las|mi|tu)?\s*(?P<name>[a-zñ ]+?)\s+(?:un|una|en)\s+(?P<value>\d{1,3})\s*%?"

    match = re.search(relative_pattern, normalized)
    if match:
        parameter = find_parameter(match.group("name"))
        if not parameter:
            return None

        raw_value = int(match.group("value"))
        if raw_value < 0 or raw_value > 100:
            return None

        verb = match.group("verb")
        operation = "increase_absolute" if verb in {"sube", "aumenta"} else "decrease_absolute"

        return PersonalityCommand(
            kind="single_relative",
            matched_text=match.group(0),
            updates=[
                PersonalityUpdate(parameter, operation, raw_value / 100),
            ],
        )

    return None


def find_parameter(raw_name: str) -> Optional[str]:
    raw_name = raw_name.strip()

    for alias, parameter in sorted(PARAMETER_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if normalize_text(alias) in raw_name:
            return parameter

    return None


def personality_update_message(updates: list[PersonalityUpdate]) -> str:
    if len(updates) == 1:
        update = updates[0]
        display_name = DISPLAY_NAMES.get(update.parameter, update.parameter)
        pct = round(update.amount * 100)
        return f"{display_name.capitalize()} actualizado. El cambio se ha aplicado de verdad."

    names = [DISPLAY_NAMES.get(update.parameter, update.parameter) for update in updates]
    joined = ", ".join(names)
    return f"He actualizado varios parámetros: {joined}. Sí, esta vez el sistema lo ha hecho de verdad."
