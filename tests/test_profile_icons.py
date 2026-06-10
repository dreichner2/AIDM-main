from __future__ import annotations

from aidm_server.profile_icons import profile_icon_race_for_character, profile_icon_src_for_character


def test_profile_icon_race_matching_maps_common_descriptions():
    assert profile_icon_race_for_character('demon') == 'tiefling'
    assert profile_icon_race_for_character('Half Demon/ Half Human') == 'tiefling'
    assert profile_icon_race_for_character('half elf') == 'elf'
    assert profile_icon_race_for_character('bunny person') == 'harengon'
    assert profile_icon_race_for_character('robot warrior') == 'warforged'
    assert profile_icon_race_for_character('African American') == 'afro-diasporic-human'


def test_profile_icon_defaults_to_male_when_sex_is_missing():
    assert profile_icon_src_for_character('demon', None) == '/profile-icons/tiefling_male.png'
    assert profile_icon_src_for_character('unknown', '') == '/profile-icons/human_male.png'


def test_profile_icon_uses_explicit_female_when_set():
    assert profile_icon_src_for_character('half elf', 'female') == '/profile-icons/elf_female.png'
    assert (
        profile_icon_src_for_character('Afro-Diasporic Human', 'female')
        == '/profile-icons/afro_diasporic_human_female.jpeg'
    )
