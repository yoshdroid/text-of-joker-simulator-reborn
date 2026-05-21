from __future__ import annotations


def get_effect_handlers():
    from tojs_reborn.engine import actions

    return {
        "change_cp": actions._handle_change_cp,
        "consume_action": actions._handle_consume_action,
        "consume_action_units": actions._handle_consume_action_units,
        "deal_damage_to_unit": actions._handle_deal_damage_to_unit,
        "deal_damage_to_units": actions._handle_deal_damage_to_units,
        "deal_life_damage": actions._handle_deal_life_damage,
        "discard_all_from_hand": actions._handle_discard_all_from_hand,
        "discard_from_hand": actions._handle_discard_from_hand,
        "destroy_trigger_zone_card": actions._handle_destroy_trigger_zone_card,
        "destroy_unit": actions._handle_destroy_unit,
        "destroy_units": actions._handle_destroy_units,
        "destroy_all_other_units": actions._handle_destroy_all_other_units,
        "draw_card_by_category": actions._handle_draw_card_by_category,
        "draw_card_by_race": actions._handle_draw_card_by_race,
        "draw_cards": actions._handle_draw_cards,
        "grant_keyword": actions._handle_grant_keyword,
        "grant_keyword_units": actions._handle_grant_keyword_units,
        "modify_base_bp": actions._handle_modify_base_bp,
        "modify_base_bp_units": actions._handle_modify_base_bp_units,
        "modify_bp": actions._handle_modify_bp,
        "modify_bp_units": actions._handle_modify_bp_units,
        "move_discard_to_hand": actions._handle_move_discard_to_hand,
        "move_random_discard_to_hand": actions._handle_move_random_discard_to_hand,
        "recover_action": actions._handle_recover_action,
        "recover_action_units": actions._handle_recover_action_units,
        "return_unit_to_hand": actions._handle_return_unit_to_hand,
        "set_unit_level": actions._handle_set_unit_level,
        "suppress_effects_for_battle": actions._handle_suppress_effects_for_battle,
    }
