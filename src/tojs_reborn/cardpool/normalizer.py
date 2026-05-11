from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .excel_loader import load_cardpool_from_xlsx
from .schema import ExcelAbility, ExcelCard, NormalizationIssue


KNOWN_TIMINGS = {
    "SELF_CIP",
    "YOUR_CIP",
    "RIVAL_CIP",
    "SELF_PIG",
    "YOUR_PIG",
    "RIVAL_PIG",
    "SELF_OC",
    "SELF_ATK",
    "YOUR_ATK",
    "RIVAL_ATK",
    "SELF_BLOCK",
    "SELF_TURN_END",
    "TRIGGER_ANY",
    "INTERCEPT_ANY",
    "INTERCEPT_ATTACK",
}

KNOWN_TIMING_PREFIXES = (
    "TRIGGER_",
    "INTERCEPT_",
)

KNOWN_EFFECTS = {
    "change_cp",
    "deal_damage_to_unit",
    "deal_life_damage",
    "discard_from_hand",
    "destroy_trigger_zone_card",
    "draw_card_by_category",
    "draw_cards",
    "modify_bp",
    "move_card",
    "recover_action",
}

ENGINE_SUPPORTED_EFFECTS = {
    "change_cp",
    "deal_damage_to_unit",
    "deal_life_damage",
    "discard_from_hand",
    "destroy_trigger_zone_card",
    "draw_card_by_category",
    "draw_cards",
    "modify_bp",
    "recover_action",
}


def load_ability_mapping(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("ability mapping root must be an object")
    if not isinstance(data.get("cards"), dict):
        raise ValueError("ability mapping must contain a cards object")
    return data


def normalize_cardpool(
    excel_path: str | Path,
    mapping_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    excel_path = Path(excel_path)
    mapping_path = Path(mapping_path)
    cards = load_cardpool_from_xlsx(excel_path)
    mapping = load_ability_mapping(mapping_path)
    issues: list[NormalizationIssue] = []

    card_by_no = {card.card_no: card for card in cards}
    normalized_cards: list[dict[str, Any]] = []

    for mapped_card_no in mapping["cards"]:
        if mapped_card_no not in card_by_no:
            issues.append(
                NormalizationIssue(
                    severity="error",
                    code="mapping_card_not_in_excel",
                    message=f"mapping card {mapped_card_no} does not exist in Excel",
                    card_no=mapped_card_no,
                )
            )

    for card in cards:
        card_mapping = mapping["cards"].get(card.card_no)
        normalized_cards.append(_normalize_card(card, card_mapping, issues))

    report = _build_report(excel_path, mapping_path, normalized_cards, issues)
    normalized = {
        "schema_version": 1,
        "source": {
            "excel_path": str(excel_path).replace("\\", "/"),
            "excel_sha256": _sha256_file(excel_path),
            "ability_mapping_path": str(mapping_path).replace("\\", "/"),
            "ability_mapping_sha256": _sha256_file(mapping_path),
        },
        "cards": normalized_cards,
    }
    return normalized, report


def write_normalized_outputs(
    excel_path: str | Path,
    mapping_path: str | Path,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized, report = normalize_cardpool(excel_path, mapping_path)
    cards_path = output_dir / "cards.normalized.json"
    report_path = output_dir / "cardpool_report.json"
    _write_json(cards_path, normalized)
    _write_json(report_path, report)
    return cards_path, report_path


def _normalize_card(
    card: ExcelCard,
    card_mapping: dict[str, Any] | None,
    issues: list[NormalizationIssue],
) -> dict[str, Any]:
    mapped_abilities = card_mapping.get("abilities", []) if isinstance(card_mapping, dict) else []
    if card_mapping is not None and card_mapping.get("card_name") != card.name:
        issues.append(
            NormalizationIssue(
                severity="error",
                code="card_name_mismatch",
                message=f"mapping card_name {card_mapping.get('card_name')} does not match Excel name {card.name}",
                card_no=card.card_no,
            )
        )

    excel_abilities_by_name = _abilities_by_name(card.abilities)
    normalized_abilities: list[dict[str, Any]] = []
    for ability in mapped_abilities:
        if not isinstance(ability, dict):
            continue
        ability_key = str(ability.get("ability_key", ""))
        ability_name = str(ability.get("ability_name", ""))
        excel_ability = excel_abilities_by_name.get(ability_name)
        if excel_ability is None:
            issues.append(
                NormalizationIssue(
                    severity="error",
                    code="ability_name_not_in_excel",
                    message=f"ability {ability_name} does not exist in Excel card abilities",
                    card_no=card.card_no,
                    ability_key=ability_key,
                )
            )
        else:
            _validate_source_text(card.card_no, ability_key, ability, excel_ability, issues)
        _validate_supported_ability(card.card_no, ability, issues)
        normalized_abilities.append(dict(ability))

    return {
        "card_no": card.card_no,
        "category": card.category,
        "rarity": card.rarity,
        "color": card.color,
        "name": card.name,
        "race": card.race,
        "cp": card.cp,
        "bp_by_level": list(card.bp_by_level),
        "abilities": normalized_abilities,
    }


def _abilities_by_name(abilities: tuple[ExcelAbility, ...]) -> dict[str, ExcelAbility]:
    result: dict[str, ExcelAbility] = {}
    for ability in abilities:
        result.setdefault(ability.name, ability)
    return result


def _validate_source_text(
    card_no: str,
    ability_key: str,
    ability: dict[str, Any],
    excel_ability: ExcelAbility,
    issues: list[NormalizationIssue],
) -> None:
    if ability.get("source_text", "") != excel_ability.text:
        issues.append(
            NormalizationIssue(
                severity="warning",
                code="source_text_mismatch",
                message="mapping source_text does not exactly match Excel ability text",
                card_no=card_no,
                ability_key=ability_key,
            )
        )


def _validate_supported_ability(
    card_no: str,
    ability: dict[str, Any],
    issues: list[NormalizationIssue],
) -> None:
    ability_key = str(ability.get("ability_key", ""))
    status = ability.get("status")
    if status not in {"supported", "unsupported", "deferred"}:
        issues.append(
            NormalizationIssue(
                severity="error",
                code="unknown_status",
                message=f"unknown ability status: {status}",
                card_no=card_no,
                ability_key=ability_key,
            )
        )
        return
    if status != "supported":
        return
    if not ability.get("source_text") and not ability.get("notes"):
        issues.append(
            NormalizationIssue(
                severity="warning",
                code="missing_source_reference",
                message="supported abilities should include source_text or notes",
                card_no=card_no,
                ability_key=ability_key,
            )
        )
    timing = ability.get("timing")
    if not _is_known_timing(timing):
        issues.append(
            NormalizationIssue(
                severity="error",
                code="unknown_timing",
                message=f"unknown timing: {timing}",
                card_no=card_no,
                ability_key=ability_key,
            )
        )
    effect_steps = ability.get("effect_steps")
    if not isinstance(effect_steps, list) or not effect_steps:
        issues.append(
            NormalizationIssue(
                severity="error",
                code="supported_without_effect_steps",
                message="supported abilities must have effect_steps",
                card_no=card_no,
                ability_key=ability_key,
            )
        )
        return
    selector_id = None
    selector = ability.get("selector")
    if isinstance(selector, dict):
        selector_id = selector.get("id")
    for step in effect_steps:
        if not isinstance(step, dict):
            continue
        effect = step.get("effect")
        if effect not in KNOWN_EFFECTS:
            issues.append(
                NormalizationIssue(
                    severity="error",
                    code="unknown_effect",
                    message=f"unknown effect: {effect}",
                    card_no=card_no,
                    ability_key=ability_key,
                )
            )
        elif effect not in ENGINE_SUPPORTED_EFFECTS:
            issues.append(
                NormalizationIssue(
                    severity="warning",
                    code="unsupported_engine_effect",
                    message=f"effect is known in schema but not implemented by engine: {effect}",
                    card_no=card_no,
                    ability_key=ability_key,
                )
            )
        target = step.get("target")
        if isinstance(target, str) and target not in {"source"} and selector_id is not None and target != selector_id:
            issues.append(
                NormalizationIssue(
                    severity="error",
                    code="unknown_selector_reference",
                    message=f"effect target {target} does not match selector id {selector_id}",
                    card_no=card_no,
                    ability_key=ability_key,
                )
            )


def _is_known_timing(timing: Any) -> bool:
    if not isinstance(timing, str):
        return False
    if timing in KNOWN_TIMINGS:
        return True
    return any(timing.startswith(prefix) and timing != prefix for prefix in KNOWN_TIMING_PREFIXES)


def _build_report(
    excel_path: Path,
    mapping_path: Path,
    normalized_cards: list[dict[str, Any]],
    issues: list[NormalizationIssue],
) -> dict[str, Any]:
    supported: list[dict[str, str]] = []
    unsupported: list[dict[str, str]] = []
    deferred: list[dict[str, str]] = []
    status_counts: dict[str, int] = {}
    timing_counts: dict[str, int] = {}
    effect_counts: dict[str, int] = {}
    for card in normalized_cards:
        for ability in card["abilities"]:
            item = {
                "card_no": card["card_no"],
                "card_name": card["name"],
                "ability_key": ability.get("ability_key", ""),
                "ability_name": ability.get("ability_name", ""),
            }
            status = str(ability.get("status"))
            status_counts[status] = status_counts.get(status, 0) + 1
            timing = ability.get("timing")
            if isinstance(timing, str) and timing:
                timing_counts[timing] = timing_counts.get(timing, 0) + 1
            for step in ability.get("effect_steps", []):
                if isinstance(step, dict) and isinstance(step.get("effect"), str):
                    effect = step["effect"]
                    effect_counts[effect] = effect_counts.get(effect, 0) + 1
            if ability.get("status") == "supported":
                supported.append(item)
            elif ability.get("status") == "unsupported":
                unsupported.append(item)
            elif ability.get("status") == "deferred":
                deferred.append(item)
    return {
        "schema_version": 1,
        "source_excel": str(excel_path).replace("\\", "/"),
        "ability_mapping": str(mapping_path).replace("\\", "/"),
        "card_count": len(normalized_cards),
        "supported_ability_count": len(supported),
        "status_counts": dict(sorted(status_counts.items())),
        "timing_counts": dict(sorted(timing_counts.items())),
        "effect_counts": dict(sorted(effect_counts.items())),
        "supported_abilities": supported,
        "unsupported_abilities": unsupported,
        "deferred_abilities": deferred,
        "errors": [_issue_to_dict(issue) for issue in issues if issue.severity == "error"],
        "warnings": [_issue_to_dict(issue) for issue in issues if issue.severity == "warning"],
    }


def _issue_to_dict(issue: NormalizationIssue) -> dict[str, Any]:
    return {
        "severity": issue.severity,
        "code": issue.code,
        "message": issue.message,
        "card_no": issue.card_no,
        "ability_key": issue.ability_key,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
