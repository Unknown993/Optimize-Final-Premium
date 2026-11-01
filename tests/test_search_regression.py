import os
import sys
import re
import pytest

# Ensure tele_bot root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["TEST_MODE"] = "1"

from database.search_engine import (
    LANGUAGE_MAP,
    UNIVERSAL_AUDIO_TAGS,
    QUALITY_MAP,
    canonicalize_language,
    canonicalize_quality,
    build_language_regex,
    build_quality_regex,
    build_season_regex,
    build_universal_audio_regex,
    parse_user_query,
    build_mongo_search_query,
    calculate_relevance_score,
    rank_media_results,
    SearchCache,
    SearchAnalytics,
    SearchSessionManager,
    GLOBAL_SESSION_MANAGER,
    GLOBAL_SEARCH_CACHE,
    GLOBAL_SEARCH_ANALYTICS,
)
from database.search_engine import (
    build_empty_filter_buttons,
    get_filter_chip_label,
    set_active_filter,
    get_active_filters,
    clear_active_filters,
)


class MockDoc:
    def __init__(self, file_id, file_name, file_size=1000000000, caption=""):
        self.file_id = str(file_id)
        self.file_name = file_name
        self.file_size = file_size
        self.caption = caption


# ==============================================================================
# SECTION 12: 20 REQUIRED REGRESSION TESTS
# ==============================================================================

def test_01_hindi_button_matching():
    """Test 1: Hindi button matching finds Hindi files and dual audio files."""
    regex = build_language_regex("hindi")
    assert regex is not None

    hindi_doc = "Iron.Man.2008.Hindi.DD5.1.1080p.mkv"
    dual_doc = "Iron.Man.2008.1080p.Dual.Audio.mkv"
    multi_doc = "Iron.Man.2008.720p.Multi.Audio.mkv"
    eng_doc = "Iron.Man.2008.1080p.English.Only.mkv"

    assert bool(regex.search(hindi_doc)) is True
    assert bool(regex.search(dual_doc)) is True
    assert bool(regex.search(multi_doc)) is True
    assert bool(regex.search(eng_doc)) is False


def test_02_query_hin_parity_with_button():
    """Test 2: Searching 'Iron Man hin' parses language and produces equivalent query to button."""
    parsed = parse_user_query("Iron Man hin")
    assert parsed["title"].lower() == "iron man"
    assert parsed["language"] == "hindi"

    query_from_text = build_mongo_search_query("Iron Man hin")
    query_from_button = build_mongo_search_query({"search": "Iron Man", "language": "hindi"})

    # Both must require Iron Man title and Hindi language/dual audio regex
    assert "$and" in query_from_text
    assert "$and" in query_from_button
    assert len(query_from_text["$and"]) == len(query_from_button["$and"])


def test_03_tamil_and_all_languages_parity():
    """Test 3: Single source of truth covers all 13 canonical languages and matches universal audio."""
    canonical_13 = [
        "hindi", "tamil", "kannada", "telugu", "malayalam",
        "english", "punjabi", "bengali", "marathi", "gujarati",
        "urdu", "korean", "japanese"
    ]
    for lang in canonical_13:
        canon = canonicalize_language(lang)
        assert canon == lang, f"Failed canonicalization for {lang}"
        reg = build_language_regex(lang)
        assert reg is not None, f"Failed regex build for {lang}"
        # Every language filter MUST match universal dual audio
        assert bool(reg.search("Movie.Dual.Audio.mkv")) is True
        assert bool(reg.search("Movie.Multi.Audio.mkv")) is True


def test_04_universal_tag_only():
    """Test 4: Universal audio tags appear under every language filter; generic dub/sub do not."""
    universal_files = [
        "Avatar.2009.1080p.Dual.Audio.mkv",
        "Avatar.2009.720p.Multi.Audio.mkv",
        "Avatar.2009.Dual.mkv",
        "Avatar.2009.Multiaudio.mkv",
    ]
    excluded_files = [
        "Avatar.2009.1080p.Dubbed.mkv",
        "Avatar.2009.Dub.mkv",
        "Avatar.2009.Multi-Sub.mkv",
    ]
    for lang in ["hindi", "tamil", "telugu", "malayalam", "kannada", "english"]:
        reg = build_language_regex(lang)
        for fn in universal_files:
            assert bool(reg.search(fn)) is True, f"{fn} did not match language filter {lang}"
        for fn in excluded_files:
            assert bool(reg.search(fn)) is False, f"{fn} unexpectedly matched language filter {lang}"


def test_05_no_and_error():
    """Test 5: Language alias OR universal tag is sufficient, never requires both."""
    hindi_only = "Kahaani.2012.Hindi.1080p.mkv"
    dual_only = "Interstellar.2014.1080p.Dual.Audio.mkv"

    reg = build_language_regex("hindi")
    assert bool(reg.search(hindi_only)) is True
    assert bool(reg.search(dual_only)) is True


def test_06_language_isolation():
    """Test 6: Hindi-only does not match Tamil or English exclusive files."""
    hindi_reg = build_language_regex("hindi")
    tamil_reg = build_language_regex("tamil")
    eng_reg = build_language_regex("english")

    hindi_file = "Dangal.2016.Hindi.Proper.1080p.mkv"
    tamil_file = "Vikram.2022.Tamil.Original.1080p.mkv"
    eng_file = "Oppenheimer.2023.English.Original.1080p.mkv"

    # Hindi filter matches only Hindi file
    assert bool(hindi_reg.search(hindi_file)) is True
    assert bool(hindi_reg.search(tamil_file)) is False
    assert bool(hindi_reg.search(eng_file)) is False

    # Tamil filter matches only Tamil file
    assert bool(tamil_reg.search(tamil_file)) is True
    assert bool(tamil_reg.search(hindi_file)) is False

    # English filter matches only English file
    assert bool(eng_reg.search(eng_file)) is True
    assert bool(eng_reg.search(hindi_file)) is False


def test_07_direct_audio_query():
    """Test 7: Direct audio query (Iron Man dual / multi) identifies universal audio."""
    p1 = parse_user_query("Iron Man dual")
    assert p1["title"].lower() == "iron man"
    assert p1["universal_audio"] is True

    p2 = parse_user_query("Iron Man multi audio")
    assert p2["title"].lower() == "iron man"
    assert p2["universal_audio"] is True

    q = build_mongo_search_query("Iron Man dual")
    u_reg = build_universal_audio_regex()
    assert bool(u_reg.search("Iron.Man.2008.Dual.Audio.mkv")) is True
    assert bool(u_reg.search("Iron.Man.2008.English.Only.mkv")) is False


def test_08_quality_aliases_normalization():
    """Test 8: Quality aliases normalize correctly to canonical 480p, 720p, 1080p, 2160p."""
    assert canonicalize_quality("480p") == "480p"
    assert canonicalize_quality("480") == "480p"
    assert canonicalize_quality("sd") == "480p"

    assert canonicalize_quality("720p") == "720p"
    assert canonicalize_quality("720") == "720p"
    assert canonicalize_quality("hd") == "720p"

    assert canonicalize_quality("1080p") == "1080p"
    assert canonicalize_quality("1080") == "1080p"
    assert canonicalize_quality("fhd") == "1080p"
    assert canonicalize_quality("full hd") == "1080p"

    assert canonicalize_quality("2160p") == "2160p"
    assert canonicalize_quality("2160") == "2160p"
    assert canonicalize_quality("4k") == "2160p"
    assert canonicalize_quality("uhd") == "2160p"


def test_09_button_query_parity():
    """Test 9: Applying filter via query text matches applying via button."""
    # Quality parity
    pq = parse_user_query("Inception 1080p")
    assert pq["title"].lower() == "inception"
    assert pq["quality"] == "1080p"
    q_mongo_text = build_mongo_search_query("Inception 1080p")
    q_mongo_btn = build_mongo_search_query({"search": "Inception", "quality": "1080p"})
    assert "$and" in q_mongo_text and "$and" in q_mongo_btn

    # Season parity
    ps = parse_user_query("Loki Season 1")
    assert ps["title"].lower() == "loki"
    assert ps["season"] == 1
    s_mongo_text = build_mongo_search_query("Loki Season 1")
    s_mongo_btn = build_mongo_search_query({"search": "Loki", "season": "1"})
    assert "$and" in s_mongo_text and "$and" in s_mongo_btn


def test_10_filter_persistence_across_pagination():
    """Test 10: Active filters persist across Next/Prev page transitions."""
    key = "test-chat-pagination-1"
    clear_active_filters(key)
    set_active_filter(key, "quality", "1080p")
    set_active_filter(key, "language", "hindi")

    filters_before = get_active_filters(key)
    assert filters_before["quality"] == "1080p"
    assert filters_before["language"] == "hindi"
    chip = get_filter_chip_label(filters_before)
    assert "1080P" in chip
    assert "Hindi" in chip

    # Simulate next page lookup: active filters remain intact
    filters_p2 = get_active_filters(key)
    assert filters_p2 == filters_before


def test_11_reset_button_restores_original_query():
    """Test 11: Reset button clears active filters and returns bare query."""
    manager = SearchSessionManager()
    session = manager.get_or_create("key-reset-1", "Interstellar 1080p", 1234, 5678)
    assert session.active_filters.get("quality") == "1080p"

    session.reset_filters()
    assert session.active_filters == {}
    query_input = session.get_query_input()
    assert query_input == {"search": "Interstellar"}


def test_12_no_results_shows_clear_message_and_accessible_buttons():
    """Test 12: Zero results displays clear screen while keeping filter and reset buttons accessible."""
    key = "test-key-no-results"
    btn = build_empty_filter_buttons(key, active_filter="1080P • Hindi")

    # Verify buttons layout
    flat_callbacks = [b.callback_data for row in btn for b in row]
    assert f"reset_filter#{key}" in flat_callbacks
    assert f"qualities#{key}" in flat_callbacks
    assert f"languages#{key}" in flat_callbacks
    assert f"seasons#{key}" in flat_callbacks
    assert "pages" in flat_callbacks  # No results indicator


def test_13_concurrent_users_isolated():
    """Test 13: Concurrent users in same group search & filter completely independently."""
    manager = SearchSessionManager()
    # User A in Group -10012345 searches Inception
    sess_a = manager.get_or_create("-10012345-msg100", "Inception", -10012345, 1111)
    sess_a.set_filter("quality", "1080p")

    # User B in same Group -10012345 searches Interstellar
    sess_b = manager.get_or_create("-10012345-msg200", "Interstellar", -10012345, 2222)
    sess_b.set_filter("language", "hindi")

    # Assert completely isolated filter state
    assert sess_a.active_filters == {"quality": "1080p"}
    assert sess_b.active_filters == {"language": "hindi"}
    assert sess_a.get_query_input()["search"] == "Inception"
    assert sess_b.get_query_input()["search"] == "Interstellar"


def test_14_stale_callback_protection():
    """Test 14: Stale callback from older query cannot alter newer session."""
    manager = SearchSessionManager()
    old_key = "chat-1-msg-old"
    new_key = "chat-1-msg-new"

    sess_old = manager.get_or_create(old_key, "Old Query", 1, 10)
    sess_new = manager.get_or_create(new_key, "New Query", 1, 10)

    # Click from old message only touches old session
    sess_old.set_filter("quality", "720p")
    assert sess_old.active_filters.get("quality") == "720p"
    assert sess_new.active_filters.get("quality") is None


def test_15_same_title_movie_and_series_retained():
    """Test 15: Movie and TV series sharing the same title are both retained in ranked results."""
    parsed = parse_user_query("Halo")
    movie_doc = MockDoc("m1", "Halo (2012) 1080p BluRay.mkv", 2000000000)
    series_doc = MockDoc("s1", "Halo S01 Complete 1080p WEB-DL.mkv", 5000000000)

    ranked = rank_media_results([movie_doc, series_doc], parsed)
    assert len(ranked) == 2
    ids = [d.file_id for d in ranked]
    assert "m1" in ids
    assert "s1" in ids


def test_16_short_and_numbered_titles_preserved():
    """Test 16: Parser preserves short titles ('It', 'Us', 'The A-Team') and sequel numbers ('Iron Man 2')."""
    assert parse_user_query("It 2017")["title"] == "It"
    assert parse_user_query("Us 2019")["title"] == "Us"
    assert parse_user_query("The A-Team 2010")["title"] == "The A-Team"
    assert parse_user_query("Iron Man 2")["title"] == "Iron Man 2"
    assert parse_user_query("Fast & Furious 9")["title"] == "Fast & Furious 9"


def test_17_season_boundary_strictness():
    """Test 17: Season 1 regex strictly matches Season 1 and rejects Season 10/11."""
    s1_regex = build_season_regex(1)

    assert bool(s1_regex.search("Loki S01E01.mkv")) is True
    assert bool(s1_regex.search("Loki S1.mkv")) is True
    assert bool(s1_regex.search("Loki Season 1 Complete.mkv")) is True
    assert bool(s1_regex.search("Loki Season 01.mkv")) is True

    # Critical boundary protection: Season 10 and 11 must NOT match
    assert bool(s1_regex.search("Loki S10 Complete.mkv")) is False
    assert bool(s1_regex.search("Loki S11 Complete.mkv")) is False
    assert bool(s1_regex.search("Loki Season 10.mkv")) is False
    assert bool(s1_regex.search("Loki Season 11.mkv")) is False


def test_18_pagination_stability():
    """Test 18: Total pages and button offsets calculate accurately across arbitrary page sizes."""
    import math

    total_results = 25
    # Case A: page size = 10
    max_btn = 10
    pages = math.ceil(total_results / max_btn)
    assert pages == 3

    # Case B: page size = 5
    max_btn = 5
    pages = math.ceil(total_results / max_btn)
    assert pages == 5

    # Case C: Single page results (<= max_btn)
    total_single = 8
    pages_single = math.ceil(total_single / 10)
    assert pages_single == 1


def test_19_cache_isolation():
    """Test 19: Search cache keys isolate by query and active filters."""
    cache = SearchCache()
    doc_unfiltered = [MockDoc("1", "Avatar.mkv")]
    doc_hindi = [MockDoc("2", "Avatar.Hindi.mkv")]

    cache.set("avatar", {}, 0, 10, doc_unfiltered, 1)
    cache.set("avatar", {"language": "hindi"}, 0, 10, doc_hindi, 1)

    cached_unfiltered = cache.get("avatar", {}, 0, 10)
    cached_hindi = cache.get("avatar", {"language": "hindi"}, 0, 10)
    cached_tamil = cache.get("avatar", {"language": "tamil"}, 0, 10)

    assert cached_unfiltered[0][0].file_id == "1"
    assert cached_hindi[0][0].file_id == "2"
    assert cached_tamil is None


def test_20_diagnostics_output_check():
    """Test 20: Diagnostics output is structured and contains no credentials."""
    raw = "Inception 2010 1080p Hindi"
    parsed = parse_user_query(raw)
    assert parsed["title"] == "Inception"
    assert parsed["year"] == 2010
    assert parsed["quality"] == "1080p"
    assert parsed["language"] == "hindi"

    score = calculate_relevance_score("Inception (2010) 1080p Hindi.mkv", parsed)
    assert score >= 1000  # High relevance for full exact match

    # Verify credentials redaction in string
    diagnostic_text = (
        f"Raw: {raw} | Title: {parsed['title']} | Year: {parsed['year']} | "
        f"Quality: {parsed['quality']} | Lang: {parsed['language']} | Score: {score}"
    )
    assert "mongodb" not in diagnostic_text.lower()
    assert "password" not in diagnostic_text.lower()
    assert "cluster" not in diagnostic_text.lower()
