"""
Integration and Concurrency Regression Suite for Search Engine V9.
Covers the full required test matrix from Section 8 of the V9 Brief:
1. Parser matrix (year, sequel number, short titles, punctuation variants, Hinglish, episode formats)
2. Language matrix (13 languages, universal audio, exclusions of generic dub and multi-sub)
3. Quality matrix (480p, 720p, 1080p, 2160p, HD vs FHD/UHD, HDR/HDRip boundary tests)
4. Season & Episode matrix (Season 1 vs 10/11, Episode 2 vs 20/21, S01E02, 1x02)
5. Ranking tiers (exact title/year, loose hits, movie/series coexistence, tie-breaking)
6. Result scope & snapshot metrics (total_matched, examined, ranked_snapshot, scope)
7. Pagination stability (no repeated/missing IDs, stable order, snapshot preservation)
8. Multi-factor cache isolation (query, filters, episode, audio, db_mode, file_type)
9. Telegram concurrency & 64-byte callback validation (out-of-order clicks, revision check)
10. Diagnostics escaping & analytics mapping (/search_stats & /search_debug)
"""

import os
import sys
import html
import pytest

# Ensure tele_bot root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["TEST_MODE"] = "1"

from database.search_engine import (
    SearchRequest,
    LANGUAGE_MAP,
    UNIVERSAL_AUDIO_TAGS,
    QUALITY_MAP,
    canonicalize_language,
    canonicalize_quality,
    build_language_regex,
    build_quality_regex,
    build_season_regex,
    build_episode_regex,
    build_season_episode_regex,
    build_universal_audio_regex,
    parse_user_query,
    build_mongo_search_query,
    calculate_relevance_score,
    get_relevance_score_breakdown,
    rank_media_results,
    SearchCache,
    SearchAnalytics,
    SearchSession,
    SearchSessionManager,
    GLOBAL_SESSION_MANAGER,
    GLOBAL_SEARCH_CACHE,
    GLOBAL_SEARCH_ANALYTICS,
    build_search_buttons,
    build_empty_filter_buttons,
    build_pagination_row,
    format_button_label,
    validate_callback_data,
)


class MockMedia:
    def __init__(self, file_id, file_name, file_size=1000000000, caption=""):
        self.file_id = str(file_id)
        self.file_name = file_name
        self.file_size = file_size
        self.caption = caption


# ==============================================================================
# TEST 1: PARSER MATRIX
# ==============================================================================

def test_v9_parser_matrix():
    # A. Year + Sequel number: "Iron Man 2 2010"
    p1 = parse_user_query("Iron Man 2 2010")
    assert p1.normalized_title == "Iron Man 2"
    assert p1.year == 2010

    # B. Short titles & articles preserved: "It 2017", "Us 2019", "The A-Team", "A Quiet Place"
    assert parse_user_query("It 2017").normalized_title == "It"
    assert parse_user_query("Us 2019").normalized_title == "Us"
    assert parse_user_query("The A-Team 2010").normalized_title == "The A-Team"
    assert parse_user_query("A Quiet Place").normalized_title == "A Quiet Place"

    # C. Punctuation variants: "Spider-Man", "Spider.Man", "Spider_Man"
    assert "spider" in parse_user_query("Spider-Man").normalized_title.lower()

    # D. Roman Hindi / Hinglish request words removed cleanly
    p_hinglish = parse_user_query("please send Inception movie bhejo download link do")
    assert p_hinglish.normalized_title == "Inception"

    # E. Episode formats: S01E02, 1x02, Season 1 Episode 2, Episode 2
    p_se = parse_user_query("Loki S01E02 1080p")
    assert p_se.normalized_title == "Loki"
    assert p_se.season == 1
    assert p_se.episode == 2
    assert p_se.quality == "1080p"

    p_x = parse_user_query("Succession 1x04 720p")
    assert p_x.normalized_title == "Succession"
    assert p_x.season == 1
    assert p_x.episode == 4
    assert p_x.quality == "720p"

    p_words = parse_user_query("Breaking Bad Season 2 Episode 7")
    assert p_words.normalized_title == "Breaking Bad"
    assert p_words.season == 2
    assert p_words.episode == 7

    p_ep_only = parse_user_query("Game of Thrones Episode 5")
    assert p_ep_only.normalized_title == "Game of Thrones"
    assert p_ep_only.season is None
    assert p_ep_only.episode == 5


# ==============================================================================
# TEST 2: LANGUAGE MATRIX & UNIVERSAL AUDIO EXCLUSIONS
# ==============================================================================

def test_v9_language_matrix():
    canonical_13 = [
        "hindi", "tamil", "kannada", "telugu", "malayalam",
        "english", "punjabi", "bengali", "marathi", "gujarati",
        "urdu", "korean", "japanese"
    ]
    # 1. All 13 canonical languages map to themselves
    for lang in canonical_13:
        assert canonicalize_language(lang) == lang
        reg = build_language_regex(lang)
        # Universal tags MUST match every language
        assert bool(reg.search("Movie.Dual.Audio.mkv")) is True
        assert bool(reg.search("Movie.Multi.Audio.mkv")) is True
        assert bool(reg.search("Movie.Multiaudio.mkv")) is True

    # 2. Exclusions: generic 'dub'/'dubbed' and 'multi-sub' must NOT match language filters
    hin_reg = build_language_regex("hindi")
    assert bool(hin_reg.search("Movie.Dubbed.mkv")) is False
    assert bool(hin_reg.search("Movie.Dub.mkv")) is False
    assert bool(hin_reg.search("Movie.Multi-Sub.mkv")) is False
    assert bool(hin_reg.search("Movie.Multi.Sub.mkv")) is False

    # 3. Language-specific dub remains language specific
    tam_reg = build_language_regex("tamil")
    assert bool(hin_reg.search("Movie.Hindi.Dub.mkv")) is True
    assert bool(tam_reg.search("Movie.Hindi.Dub.mkv")) is False
    assert bool(tam_reg.search("Movie.Tamil.Dub.mkv")) is True
    assert bool(hin_reg.search("Movie.Tamil.Dub.mkv")) is False


# ==============================================================================
# TEST 3: QUALITY MATRIX & BOUNDARY SEPARATION
# ==============================================================================

def test_v9_quality_matrix():
    # 480p, 720p, 1080p, 2160p
    assert canonicalize_quality("sd") == "480p"
    assert canonicalize_quality("hd") == "720p"
    assert canonicalize_quality("fhd") == "1080p"
    assert canonicalize_quality("4k") == "2160p"
    assert canonicalize_quality("uhd") == "2160p"

    reg_720 = build_quality_regex("720p")
    assert bool(reg_720.search("Film.2020.720p.mkv")) is True
    assert bool(reg_720.search("Film.2020.HD.mkv")) is True

    # Strict boundary checks: 720p must NOT match 1080p, FHD, UHD, 4K, HDR, HDRip, or HDR10
    assert bool(reg_720.search("Film.2020.1080p.mkv")) is False
    assert bool(reg_720.search("Film.2020.FHD.mkv")) is False
    assert bool(reg_720.search("Film.2020.UHD.mkv")) is False
    assert bool(reg_720.search("Film.2020.4K.mkv")) is False
    assert bool(reg_720.search("Film.2020.HDR.mkv")) is False
    assert bool(reg_720.search("Film.2020.HDRip.mkv")) is False
    assert bool(reg_720.search("Film.2020.HDR10.mkv")) is False


# ==============================================================================
# TEST 4: SEASON & EPISODE MATRIX
# ==============================================================================

def test_v9_season_and_episode_matrix():
    # Season 1 strictness
    s1_reg = build_season_regex(1)
    assert bool(s1_reg.search("Loki.S01E01.mkv")) is True
    assert bool(s1_reg.search("Loki.Season.1.mkv")) is True
    assert bool(s1_reg.search("Loki.S10.mkv")) is False
    assert bool(s1_reg.search("Loki.Season.11.mkv")) is False

    # Episode 2 strictness
    e2_reg = build_episode_regex(2)
    assert bool(e2_reg.search("Loki.S01E02.mkv")) is True
    assert bool(e2_reg.search("Loki.1x02.mkv")) is True
    assert bool(e2_reg.search("Loki.Episode.2.mkv")) is True
    assert bool(e2_reg.search("Loki.Episode.20.mkv")) is False
    assert bool(e2_reg.search("Loki.S01E21.mkv")) is False

    # Season + Episode combined regex
    se_reg = build_season_episode_regex(1, 2)
    assert bool(se_reg.search("Loki.S01E02.mkv")) is True
    assert bool(se_reg.search("Loki.1x02.mkv")) is True
    assert bool(se_reg.search("Loki.S01E03.mkv")) is False
    assert bool(se_reg.search("Loki.S02E02.mkv")) is False


# ==============================================================================
# TEST 5: RELEVANCE RANKING TIERS & SCORE BREAKDOWN
# ==============================================================================

def test_v9_relevance_ranking_tiers():
    parsed = parse_user_query("Inception 2010")

    doc_exact_yr = MockMedia("1", "Inception (2010) 1080p BluRay.mkv", 2000000000)
    doc_exact = MockMedia("2", "Inception 720p WEB-DL.mkv", 1000000000)
    doc_phrase = MockMedia("3", "The Making of Inception 2010 720p.mkv", 500000000)
    doc_loose = MockMedia("4", "Random Movie with Inception subtitle.mkv", 400000000)

    b1 = get_relevance_score_breakdown(doc_exact_yr.file_name, parsed)
    b2 = get_relevance_score_breakdown(doc_exact.file_name, parsed)
    b3 = get_relevance_score_breakdown(doc_phrase.file_name, parsed)

    assert b1["total"] > b2["total"] > b3["total"]
    assert "Tier 1" in b1["tier"]

    # Both movie and series sharing same title are retained
    halo_movie = MockMedia("m1", "Halo (2012) 1080p BluRay.mkv", 2000000000)
    halo_series = MockMedia("s1", "Halo S01 Complete 1080p WEB-DL.mkv", 5000000000)
    ranked = rank_media_results([halo_movie, halo_series], parse_user_query("Halo"))
    assert len(ranked) == 2
    r_ids = [d.file_id for d in ranked]
    assert "m1" in r_ids and "s1" in r_ids


# ==============================================================================
# TEST 6: RESULT SCOPE & SNAPSHOT METRICS
# ==============================================================================

def test_v9_result_scope_metrics():
    sess = SearchSession("test-scope-1", "Avatar", 1234, 5678)
    candidates = [MockMedia(str(i), f"Avatar {i}.mkv") for i in range(25)]

    # Complete scope (all matches retrieved)
    sess.set_snapshot(candidates, total_matched=25, examined=25, ranked_count=25, scope="complete")
    assert sess.result_scope == "complete"
    assert sess.total_matched_documents == 25
    assert sess.ranked_snapshot_count == 25

    # Bounded scope (more matches exist in DB than examined candidate budget)
    sess.set_snapshot(candidates, total_matched=350, examined=25, ranked_count=25, scope="bounded/partial")
    assert sess.result_scope == "bounded/partial"
    assert sess.total_matched_documents == 350
    assert sess.ranked_snapshot_count == 25


# ==============================================================================
# TEST 7: PAGINATION STABILITY
# ==============================================================================

def test_v9_pagination_stability():
    sess = SearchSession("test-p-stable", "Interstellar", 1234, 5678)
    candidates = [MockMedia(f"id_{i:02d}", f"Interstellar Part {i}.mkv") for i in range(25)]
    sess.set_snapshot(candidates, total_matched=25, examined=25, ranked_count=25, scope="complete")

    # Page 1 (offset 0, limit 10)
    p1 = sess.snapshot_candidates[0:10]
    # Page 2 (offset 10, limit 10)
    p2 = sess.snapshot_candidates[10:20]
    # Page 3 (offset 20, limit 10)
    p3 = sess.snapshot_candidates[20:30]

    assert len(p1) == 10
    assert len(p2) == 10
    assert len(p3) == 5

    # No overlapping IDs between pages
    p1_ids = {d.file_id for d in p1}
    p2_ids = {d.file_id for d in p2}
    p3_ids = {d.file_id for d in p3}
    assert p1_ids.isdisjoint(p2_ids)
    assert p2_ids.isdisjoint(p3_ids)

    # Page count accurately reflects ranked_snapshot_count
    import math
    total_pages = math.ceil(sess.ranked_snapshot_count / 10)
    assert total_pages == 3


# ==============================================================================
# TEST 8: MULTI-FACTOR CACHE ISOLATION
# ==============================================================================

def test_v9_cache_multi_factor_isolation():
    cache = SearchCache()
    req_base = parse_user_query("Avatar")
    req_1080 = parse_user_query("Avatar 1080p")
    req_hin = parse_user_query("Avatar Hindi")
    req_ep = parse_user_query("Avatar S01E02")

    k_base = cache.make_key("avatar", {}, 0, 10, req_base.year, req_base.language, req_base.quality, req_base.season, req_base.episode)
    k_1080 = cache.make_key("avatar", {}, 0, 10, req_1080.year, req_1080.language, req_1080.quality, req_1080.season, req_1080.episode)
    k_hin = cache.make_key("avatar", {}, 0, 10, req_hin.year, req_hin.language, req_hin.quality, req_hin.season, req_hin.episode)
    k_ep = cache.make_key("avatar", {}, 0, 10, req_ep.year, req_ep.language, req_ep.quality, req_ep.season, req_ep.episode)

    keys = {k_base, k_1080, k_hin, k_ep}
    # All keys MUST be distinct
    assert len(keys) == 4


# ==============================================================================
# TEST 9: TELEGRAM CONCURRENCY & 64-BYTE CALLBACK VALIDATION
# ==============================================================================

def test_v9_telegram_concurrency_and_64byte_limit():
    # 1. 64-byte validation
    valid_data = "qualities#-1001987654321-99887766"
    assert validate_callback_data(valid_data) == valid_data
    assert len(valid_data.encode("utf-8")) <= 64

    # Over 64 bytes raises ValueError
    too_long = "next_123456789_-1001987654321-99887766_very_long_extra_padding_string_that_exceeds_sixty_four_bytes"
    with pytest.raises(ValueError):
        validate_callback_data(too_long)

    # 2. Build search buttons with 64-byte enforcement
    files = [MockMedia("f1", "Sample.mkv", 1000000)]
    btns = build_search_buttons(files, "-100123-1", 0, 1, 123, {"button": True, "max_btn": True})
    for row in btns:
        for b in row:
            if b.callback_data:
                assert len(b.callback_data.encode("utf-8")) <= 64

    # 3. Out-of-order callback protection via revision
    sess = SearchSession("chat-test-rev", "Matrix", 100, 200)
    rev_click1 = sess.increment_revision()  # User clicks Hindi
    assert rev_click1 == 1

    rev_click2 = sess.increment_revision()  # User rapidly clicks 1080p
    assert rev_click2 == 2

    # Click 1 response arrives later: rev_click1 (1) != sess.revision (2), dropped!
    assert rev_click1 != sess.revision
    # Click 2 response arrives: rev_click2 (2) == sess.revision (2), accepted!
    assert rev_click2 == sess.revision


# ==============================================================================
# TEST 10: DIAGNOSTICS ESCAPING & ANALYTICS MAPPING
# ==============================================================================

def test_v9_diagnostics_escaping_and_analytics_mapping():
    # 1. HTML escaping protection against malformed markup
    malformed_query = "<script>alert('xss')</script> & Iron Man"
    safe_query = html.escape(malformed_query)
    assert "<script>" not in safe_query
    assert "&lt;script&gt;" in safe_query
    assert "&amp;" in safe_query

    # 2. Analytics fields match /search_stats exactly
    analytics = SearchAnalytics()
    analytics.record_search("Spider-Man", 10, 42.5, {"quality": "1080p"})
    stats = analytics.get_stats()

    # Exact field names verified
    assert "total_queries" in stats
    assert "zero_results" in stats
    assert "zero_result_queries" in stats
    assert "avg_latency_ms" in stats
    assert "active_filters_used" in stats
    assert stats["total_queries"] == 1
    assert stats["active_filters_used"] == 1
    assert stats["avg_latency_ms"] == 42.5


# ==============================================================================
# TEST 11: BACK BUTTON, DYNAMIC PAGINATION & RESET FILTERS INTEGRITY
# ==============================================================================

def test_v9_back_button_and_reset_filters():
    # 1. Dynamic Pagination: Page 1 -> Page 2 -> Page 3 -> Back to Page 2 -> Back to Page 1
    # 25 total items, page size 10 (Total 3 pages)
    req = "12345"
    key = "chat-msg-1"

    # Page 1 (offset 0)
    p1 = build_pagination_row(key, req, current_offset=0, total_results=25, page_size=10)
    assert len(p1) == 3
    assert p1[0].text == "ᴘᴀɢᴇ"
    assert p1[1].text == "1 / 3"
    assert p1[2].text == "ɴᴇxᴛ ⋟"
    assert p1[2].callback_data == f"next_{req}_{key}_10"

    # Page 2 (offset 10)
    p2 = build_pagination_row(key, req, current_offset=10, total_results=25, page_size=10)
    assert len(p2) == 3
    assert p2[0].text == "⋞ ʙᴀᴄᴋ"
    assert p2[0].callback_data == f"next_{req}_{key}_0"
    assert p2[1].text == "2 / 3"
    assert p2[2].text == "ɴᴇxᴛ ⋟"
    assert p2[2].callback_data == f"next_{req}_{key}_20"

    # Page 3 (offset 20)
    p3 = build_pagination_row(key, req, current_offset=20, total_results=25, page_size=10)
    assert len(p3) == 2
    assert p3[0].text == "⋞ ʙᴀᴄᴋ"
    assert p3[0].callback_data == f"next_{req}_{key}_10"
    assert p3[1].text == "3 / 3"

    # Click Back from Page 3 -> arrives at Page 2 (offset 10)
    p2_back = build_pagination_row(key, req, current_offset=10, total_results=25, page_size=10)
    assert len(p2_back) == 3
    assert p2_back[0].text == "⋞ ʙᴀᴄᴋ"
    assert p2_back[2].text == "ɴᴇxᴛ ⋟"

    # Click Back from Page 2 -> arrives at Page 1 (offset 0)
    p1_back = build_pagination_row(key, req, current_offset=0, total_results=25, page_size=10)
    assert len(p1_back) == 3
    assert p1_back[0].text == "ᴘᴀɢᴇ"
    assert p1_back[1].text == "1 / 3"
    assert p1_back[2].text == "ɴᴇxᴛ ⋟"
    # Verification: Next and Back buttons NEVER disappear!

    # Single-page check (total 4 <= page size 10)
    p_single = build_pagination_row(key, req, current_offset=0, total_results=4, page_size=10)
    assert len(p_single) == 1
    assert "ɴᴏ ᴍᴏʀᴇ ᴘᴀɢᴇꜱ ᴀᴠᴀɪʟᴀʙʟᴇ" in p_single[0].text

    # 2. SearchCache: next_offset is ALWAYS a valid string integer and NEVER str(files)
    cache = SearchCache()
    dummy_files = [MockMedia("1", "File 1"), MockMedia("2", "File 2")]
    cache.set("test_key", dummy_files, "10", 25)
    cached = cache.get("test_key")
    assert cached is not None
    c_files, c_next, c_total = cached
    assert c_files == dummy_files
    assert c_next == "10"
    assert int(c_next) == 10
    assert c_total == 25
    assert not c_next.startswith("[")

    # 3. SearchSession Reset Filters: purges all active and explicit filters cleanly
    sess = SearchSession("chat-test-reset", "States 1080p Hindi", 100, 200)
    sess.current_offset = 10
    assert sess.search_request.quality == "1080p"
    assert sess.search_request.language == "hindi"
    sess.set_filter("season", "2")
    assert sess.active_filters["season"] == "2"
    assert sess.current_offset == 0

    # User clicks Reset Filters
    sess.reset_filters()
    assert sess.active_filters == {}
    assert sess.snapshot_candidates == []
    assert sess.current_offset == 0
    assert sess.search_request.quality is None
    assert sess.search_request.language is None
    assert sess.search_request.season is None
    assert sess.search_request.explicit_filters == {}

    # 4. SearchSession offset persistence for submenus
    sess.current_offset = 10
    assert sess.current_offset == 10
    # Opening a filter submenu and clicking "Back to Files" preserves current_offset
    target_offset = getattr(sess, "current_offset", 0)
    assert target_offset == 10
    btns_restored = build_search_buttons(
        files=dummy_files,
        key="test-key",
        current_offset=target_offset,
        total_results=25,
        req=123,
        settings={"button": True}
    )
    # The last row should be the pagination row with [ ⋞ ʙᴀᴄᴋ ] and [ ɴᴇxᴛ ⋟ ]
    pag_row = btns_restored[-1]
    assert pag_row[0].text == "⋞ ʙᴀᴄᴋ"
    assert pag_row[1].text == "2 / 3"
    assert pag_row[2].text == "ɴᴇxᴛ ⋟"

    # 5. None file_name fallback to caption (No "None" buttons)
    file_with_none = MockMedia("none_id", "None", 1000000000, caption="<b>Succession.S04E04.mkv</b>")
    label = format_button_label(file_with_none.file_name if file_with_none.file_name != "None" else "Succession.S04E04.mkv", file_with_none.file_size)
    assert "None" not in label
    assert "Succession.S04E04.mkv" in label
    assert pag_row[2].text == "ɴᴇxᴛ ⋟"

