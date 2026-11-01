"""
Search Engine & Relevance Matching Subsystem for Telegram Movie Bot (V9).

Implements:
- Canonical SearchRequest contract and unified query parsing
- Single Source of Truth Language Matching Table (13 canonical languages + universal audio tags)
- Quality Alias Table (480p, 720p, 1080p, 2160p) with strict boundary isolation
- Season & Episode exact matching (S01E02, 1x02, Season 1 Episode 2, Episode 2)
- Multi-tier Relevance and Ranking engine (Movie/Series overlap preserved)
- Selective MongoDB query generator
- Stable ranked snapshot caching & pagination metrics
- In-memory bounded Search Cache with TTL
- Search Analytics & Diagnostic tools (/search_debug, /search_stats)
- Isolated Search Session Manager with revision coordination preventing concurrent/stale callback collisions
- Telegram callback_data length validation (<= 64 UTF-8 bytes)
"""

import re
import time
import math
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. CANONICAL SEARCH REQUEST CONTRACT (Section 2)
# ==============================================================================

@dataclass
class SearchRequest:
    raw_query: str
    normalized_title: str
    year: Optional[int] = None
    language: Optional[str] = None
    quality: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    universal_audio: bool = False
    file_type: Optional[str] = None
    explicit_filters: Dict[str, Any] = field(default_factory=dict)
    page_size: int = 10
    sort_version: str = "v9"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_query": self.raw_query,
            "title": self.normalized_title,
            "year": self.year,
            "language": self.language,
            "quality": self.quality,
            "season": self.season,
            "episode": self.episode,
            "universal_audio": self.universal_audio,
            "file_type": self.file_type,
            "explicit_filters": dict(self.explicit_filters),
            "page_size": self.page_size,
            "sort_version": self.sort_version,
        }

    # Dict-like compatibility for legacy callers
    def get(self, key: str, default: Any = None) -> Any:
        if key == "title":
            return self.normalized_title
        if hasattr(self, key):
            val = getattr(self, key)
            return val if val is not None else default
        return self.explicit_filters.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key == "title":
            return self.normalized_title
        if hasattr(self, key):
            return getattr(self, key)
        return self.explicit_filters[key]

    def __setitem__(self, key: str, value: Any):
        if key == "title":
            self.normalized_title = str(value)
        elif hasattr(self, key):
            setattr(self, key, value)
        else:
            self.explicit_filters[key] = value

    def __contains__(self, key: str) -> bool:
        if key == "title":
            return True
        return hasattr(self, key) or key in self.explicit_filters


# ==============================================================================
# 2. SINGLE SOURCE OF TRUTH: LANGUAGE MATCHING TABLE (Section 4)
# ==============================================================================

# Universal audio tags per Section 4:
# Include: dual, dual audio, dual-audio, multi, multi audio, multi-audio, multiaudio
# Exclude: generic 'dub', 'dubbed', and 'multi-sub'
UNIVERSAL_AUDIO_TAGS: List[str] = [
    "dual",
    "dual audio",
    "dual-audio",
    "multi",
    "multi audio",
    "multi-audio",
    "multiaudio",
]

# Exact 13 canonical language options and aliases from Section 4
LANGUAGE_MAP: Dict[str, List[str]] = {
    "hindi": ["hin", "hindi", "hindi dub", "hin dub"],
    "tamil": ["tam", "tamil", "tamil dub", "tam dub"],
    "kannada": ["kan", "kannada", "kan dub", "kannada dub"],
    "telugu": ["tel", "telugu", "tel dub", "telugu dub"],
    "malayalam": ["mal", "malayalam", "mal dub", "malayalam dub"],
    "english": ["eng", "english", "eng dub", "english dub"],
    "punjabi": ["pun", "punjabi", "pun dub", "punjabi dub"],
    "bengali": ["ben", "bengali", "ben dub", "bengali dub"],
    "marathi": ["mar", "marathi", "mar dub", "marathi dub"],
    "gujarati": ["guj", "gujarati", "guj dub", "gujarati dub"],
    "urdu": ["urd", "urdu", "urd dub", "urdu dub"],
    "korean": ["kor", "korean", "kor dub", "korean dub"],
    "japanese": ["jpn", "japanese", "jpn dub", "japanese dub"],
}

# Reverse lookup for mapping any query code/alias to canonical language name
ALIAS_TO_LANG: Dict[str, str] = {}
for lang_name, aliases in LANGUAGE_MAP.items():
    ALIAS_TO_LANG[lang_name] = lang_name
    for alias in aliases:
        ALIAS_TO_LANG[alias.lower()] = lang_name
# Include common short abbreviations
ALIAS_TO_LANG["punj"] = "punjabi"
ALIAS_TO_LANG["pb"] = "punjabi"


def canonicalize_language(val: Optional[str]) -> Optional[str]:
    """Map any input language alias/code to its canonical name."""
    if not val:
        return None
    cleaned = str(val).strip().lower()
    return ALIAS_TO_LANG.get(cleaned, cleaned if cleaned in LANGUAGE_MAP else None)


def _escape_regex_term(term: str) -> str:
    escaped = re.escape(term.strip())
    # Allow flexible separators (. - _ space) for whitespace and dashes
    return re.sub(r"\\[\s\-_]", lambda _: r"[\s\-_.]+", escaped)


def build_universal_audio_regex() -> re.Pattern:
    """
    Construct regex matching universal audio tags alone.
    Uses negative lookahead on 'multi' to prevent matching 'multi-sub' or 'multisub'.
    """
    patterns = []
    for term in UNIVERSAL_AUDIO_TAGS:
        if term == "multi":
            patterns.append(r"\bmulti(?![\s\-_.]*sub)\b")
        elif term == "dual":
            patterns.append(r"\bdual\b")
        else:
            pat = _escape_regex_term(term)
            patterns.append(rf"\b{pat}\b")
    return re.compile("(" + "|".join(patterns) + ")", re.IGNORECASE)


def build_language_regex(lang_code: str) -> Optional[re.Pattern]:
    """
    Construct a regex matching any alias of the selected language OR any universal audio tag.
    Never requires both. Uses token boundaries so short codes do not match inside unrelated words.
    Generic 'dub' or 'dubbed' is NOT universal; language-specific dub remains language-specific.
    """
    canonical = canonicalize_language(lang_code)
    if not canonical or canonical not in LANGUAGE_MAP:
        return None
    aliases = LANGUAGE_MAP[canonical]
    patterns = []
    # 1. Language aliases
    for term in aliases:
        pat = _escape_regex_term(term)
        patterns.append(rf"\b{pat}\b")
    # 2. Universal audio tags (with multi-sub protection)
    for term in UNIVERSAL_AUDIO_TAGS:
        if term == "multi":
            patterns.append(r"\bmulti(?![\s\-_.]*sub)\b")
        elif term == "dual":
            patterns.append(r"\bdual\b")
        else:
            pat = _escape_regex_term(term)
            patterns.append(rf"\b{pat}\b")

    regex_str = "(" + "|".join(patterns) + ")"
    return re.compile(regex_str, re.IGNORECASE)


def matches_language(text: str, lang_code: str) -> bool:
    """Test whether a text string contains the language or universal audio tags."""
    if not text:
        return False
    reg = build_language_regex(lang_code)
    return bool(reg.search(text)) if reg else False


# ==============================================================================
# 3. QUALITY ALIAS TABLE & BOUNDARIES (Section 4)
# ==============================================================================

QUALITY_MAP: Dict[str, List[str]] = {
    "480p": ["480", "480p", "480 p", "sd"],
    "720p": ["720", "720p", "720 p", "hd", "web-dl 720p"],
    "1080p": ["1080", "1080p", "1080 p", "fhd", "full hd", "fullhd", "1080p fhd"],
    "2160p": ["2160", "2160p", "2160 p", "4k", "uhd", "4k uhd", "2160p 4k"],
}

ALIAS_TO_QUALITY: Dict[str, str] = {}
for q_name, aliases in QUALITY_MAP.items():
    ALIAS_TO_QUALITY[q_name] = q_name
    for alias in aliases:
        ALIAS_TO_QUALITY[alias.lower()] = q_name


def canonicalize_quality(val: Optional[str]) -> Optional[str]:
    """Map any input quality alias to its canonical resolution."""
    if not val:
        return None
    cleaned = str(val).strip().lower()
    return ALIAS_TO_QUALITY.get(cleaned, cleaned if cleaned in QUALITY_MAP else None)


def build_quality_regex(quality_val: str) -> Optional[re.Pattern]:
    """
    Construct regex that strictly matches the canonical quality aliases without
    accidentally confusing 720p with FHD (1080p) or UHD (2160p).
    Explicitly prevents HD from matching HDR, HDR10, or HDRip.
    """
    canonical = canonicalize_quality(quality_val)
    if not canonical or canonical not in QUALITY_MAP:
        return None
    aliases = QUALITY_MAP[canonical]
    patterns = []
    for a in aliases:
        if a == "hd":
            # For 720p 'hd', do not match when preceded by 'f' (FHD) or 'u' (UHD),
            # or followed by 'r' (HDR, HDRip, HDR10)
            patterns.append(r"(?<![a-zA-Z0-9])hd(?![a-zA-Z0-9]|r|rip)")
        elif a == "full hd":
            patterns.append(r"\bfull[\s\-_.]+hd\b")
        else:
            patterns.append(rf"\b{re.escape(a)}\b")
    regex_str = "(" + "|".join(patterns) + ")"
    return re.compile(regex_str, re.IGNORECASE)


def matches_quality(text: str, quality_val: str) -> bool:
    """Test whether a text string contains the given quality."""
    if not text:
        return False
    reg = build_quality_regex(quality_val)
    return bool(reg.search(text)) if reg else False


# ==============================================================================
# 4. SEASON AND EPISODE MATCHING (Sections 2 & 4)
# ==============================================================================

def build_season_regex(season_num: int) -> re.Pattern:
    """
    Construct regex matching Season S01/S1/Season 1.
    Strictly ensures Season 1 does NOT match Season 10 or 11.
    """
    s = int(season_num)
    patterns = [
        rf"\bs0*{s}(?!\d)",
        rf"\bseason[\s\-_.]*0*{s}(?!\d)",
    ]
    return re.compile("(" + "|".join(patterns) + ")", re.IGNORECASE)


def build_episode_regex(episode_num: int) -> re.Pattern:
    """
    Construct regex matching Episode E02/Ep02/Episode 2/1x02/S01E02.
    Strictly prevents Episode 2 from matching Episode 20 or 21.
    """
    e = int(episode_num)
    patterns = [
        rf"(?:\b|[sS]\d+)e0*{e}(?!\d)",
        rf"\bep0*{e}(?!\d)",
        rf"\bepisode[\s\-_.]*0*{e}(?!\d)",
        rf"\b\d+x0*{e}(?!\d)",
    ]
    return re.compile("(" + "|".join(patterns) + ")", re.IGNORECASE)


def build_season_episode_regex(season_num: int, episode_num: int) -> re.Pattern:
    """
    Construct regex strictly matching a combination of Season and Episode:
    S01E02, 1x02, Season 1 Episode 2.
    """
    s, e = int(season_num), int(episode_num)
    patterns = [
        rf"\bs0*{s}[\s\-_.]*e0*{e}(?!\d)",
        rf"\b0*{s}x0*{e}(?!\d)",
        rf"\bseason[\s\-_.]*0*{s}[\s\-_.]*episode[\s\-_.]*0*{e}(?!\d)",
    ]
    return re.compile("(" + "|".join(patterns) + ")", re.IGNORECASE)


def matches_season(text: str, season_num: int) -> bool:
    if not text:
        return False
    return bool(build_season_regex(season_num).search(text))


def matches_episode(text: str, episode_num: int) -> bool:
    if not text:
        return False
    return bool(build_episode_regex(episode_num).search(text))


# ==============================================================================
# 5. UNIFIED QUERY PARSER (Section 2)
# ==============================================================================

# Common Hinglish and Roman request phrases to remove cleanly without destroying titles
REQUEST_PHRASES = [
    r"\bplease\s+send\b",
    r"\bplz\s+send\b",
    r"\bpls\s+send\b",
    r"\bsend\s+me\b",
    r"\bgive\s+me\b",
    r"\blink\s+do\b",
    r"\bmovie\s+bhejo\b",
    r"\bchahiye\b",
    r"\bdownload\b",
    r"\bfull\s+movie\b",
    r"\bnew\s+movie\b",
    r"\blatest\s+movie\b",
    r"\bbhejo\b",
    r"\bvenum\b",
    r"\biruka\b",
    r"\bpannunga\b",
    r"\banuppunga\b",
    r"\btharu\b",
    r"\bkittumo\b",
    r"\bkittum\b",
]


def parse_user_query(raw_query: str) -> SearchRequest:
    """
    Parse user query into canonical SearchRequest contract without damaging film/series titles.
    Preserves meaningful short words and sequel numbers ('It', 'Us', 'The A-Team', 'Iron Man 2').
    Extracts Year, Quality, Language, Season, Episode, and Universal Audio.
    """
    orig = str(raw_query or "").strip()
    text = orig

    # 1. Clean clear request phrases / Hinglish boilerplate
    for pat in REQUEST_PHRASES:
        text = re.sub(pat, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()

    req_data = {
        "raw_query": orig,
        "normalized_title": "",
        "year": None,
        "language": None,
        "quality": None,
        "season": None,
        "episode": None,
        "universal_audio": False,
    }

    # 2. Extract Quality (sort aliases by length desc)
    all_q_aliases = []
    for q_canonical, aliases in QUALITY_MAP.items():
        for a in aliases:
            all_q_aliases.append((a, q_canonical))
    all_q_aliases.sort(key=lambda x: len(x[0]), reverse=True)

    for alias, canonical_q in all_q_aliases:
        if alias == "hd":
            pat = r"(?<![a-zA-Z0-9])hd(?![a-zA-Z0-9]|r|rip)"
        elif alias == "full hd":
            pat = r"\bfull[\s\-_.]+hd\b"
        else:
            pat = rf"\b{re.escape(alias)}\b"
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            if not req_data["quality"]:
                req_data["quality"] = canonical_q
            text = text[:match.start()] + " " + text[match.end():]

    # 3. Extract Season & Episode in standard and varied formats
    # Format A: S01E02, S1E2, Season 1 Episode 2
    se_match = re.search(
        r"\b(?:s|season)[\s\-_.]*(\d{1,2})[\s\-_.]*(?:e|ep|episode)[\s\-_.]*(\d{1,3})\b",
        text,
        re.IGNORECASE,
    )
    if se_match:
        req_data["season"] = int(se_match.group(1))
        req_data["episode"] = int(se_match.group(2))
        text = text[:se_match.start()] + " " + text[se_match.end():]
    else:
        # Format B: 1x02, 01x02
        x_match = re.search(r"\b(\d{1,2})x(\d{1,3})\b", text, re.IGNORECASE)
        if x_match:
            req_data["season"] = int(x_match.group(1))
            req_data["episode"] = int(x_match.group(2))
            text = text[:x_match.start()] + " " + text[x_match.end():]
        else:
            # Standalone Season
            s_match = re.search(r"\b(?:season[\s\-_.]*(\d{1,2})|s(\d{1,2}))\b", text, re.IGNORECASE)
            if s_match:
                req_data["season"] = int(s_match.group(1) or s_match.group(2))
                text = text[:s_match.start()] + " " + text[s_match.end():]

            # Standalone Episode
            ep_match = re.search(r"\b(?:episode|ep|e)[\s\-_.]*(\d{1,3})\b", text, re.IGNORECASE)
            if ep_match:
                req_data["episode"] = int(ep_match.group(1))
                text = text[:ep_match.start()] + " " + text[ep_match.end():]

    # 4. Extract Universal Audio
    univ_match = re.search(r"\b(dual[\s\-_.]*audio|dual|multi[\s\-_.]*audio|multi(?![\s\-_.]*sub)|multiaudio)\b", text, re.IGNORECASE)
    if univ_match:
        req_data["universal_audio"] = True
        text = text[:univ_match.start()] + " " + text[univ_match.end():]

    # 5. Extract Language
    all_l_aliases = []
    for lang_name, aliases in LANGUAGE_MAP.items():
        for a in aliases:
            all_l_aliases.append((a, lang_name))
    all_l_aliases.sort(key=lambda x: len(x[0]), reverse=True)

    for alias, canonical_l in all_l_aliases:
        pat = rf"\b{_escape_regex_term(alias)}\b"
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            if not req_data["language"]:
                req_data["language"] = canonical_l
            text = text[:match.start()] + " " + text[match.end():]

    # 6. Extract Release Year (4 digits: 1900-2099)
    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if year_match:
        req_data["year"] = int(year_match.group(1))
        text = text[:year_match.start()] + " " + text[year_match.end():]

    # Clean leftover title without stripping meaningful short words ('It', 'Us', 'The', 'A') or sequel numbers
    title = re.sub(r"\s+", " ", text).strip(" -_:,.")
    req_data["normalized_title"] = title if title else orig

    return SearchRequest(
        raw_query=req_data["raw_query"],
        normalized_title=req_data["normalized_title"],
        year=req_data["year"],
        language=req_data["language"],
        quality=req_data["quality"],
        season=req_data["season"],
        episode=req_data["episode"],
        universal_audio=req_data["universal_audio"],
    )


# ==============================================================================
# 6. MONGODB SEARCH QUERY BUILDER (Section 3)
# ==============================================================================

def clean_media_title_for_comparison(filename: str) -> str:
    """Normalize filename into a clean title representation for scoring."""
    t = str(filename or "").strip()
    # Strip common file extension
    t = re.sub(r"\.(mkv|mp4|avi|mov|wmv|webm|flv|m4v)$", "", t, flags=re.IGNORECASE)
    # Strip release noise
    t = re.sub(
        r"\b(1080p|720p|480p|2160p|4k|uhd|fhd|hd|sd|bluray|web-dl|webrip|hevc|x264|x265|aac|dvdrip|remux|proper|hdr|sdr)\b",
        " ",
        t,
        flags=re.IGNORECASE,
    )
    # Strip languages and audio tags
    for aliases in list(LANGUAGE_MAP.values()) + [UNIVERSAL_AUDIO_TAGS]:
        for a in aliases:
            t = re.sub(rf"\b{re.escape(a)}\b", " ", t, flags=re.IGNORECASE)
    # Strip brackets and hashes
    t = re.sub(r"\[.*?\]|\(.*?\)", " ", t)
    # Normalize separators
    t = re.sub(r"[\._\-+]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def build_mongo_search_query(
    query_input: Any,
    file_type: Optional[str] = None,
    use_caption: bool = True
) -> Dict[str, Any]:
    """
    Construct selective, indexed MongoDB query predicates using $and.
    Cleanly combines Title, Season, Episode, Quality, Language, and Year constraints.
    """
    if isinstance(query_input, SearchRequest):
        parsed = query_input
    elif isinstance(query_input, dict):
        base_search = query_input.get("search", "")
        parsed = parse_user_query(base_search)
        if "quality" in query_input and query_input["quality"]:
            parsed.quality = canonicalize_quality(query_input["quality"])
        if "language" in query_input and query_input["language"]:
            parsed.language = canonicalize_language(query_input["language"])
        if "season" in query_input and query_input["season"]:
            try:
                parsed.season = int(query_input["season"])
            except (ValueError, TypeError):
                pass
        if "episode" in query_input and query_input["episode"]:
            try:
                parsed.episode = int(query_input["episode"])
            except (ValueError, TypeError):
                pass
        if "year" in query_input and query_input["year"]:
            try:
                parsed.year = int(query_input["year"])
            except (ValueError, TypeError):
                pass
    elif isinstance(query_input, list):
        joined = " ".join(str(q) for q in query_input if q)
        parsed = parse_user_query(joined)
    else:
        parsed = parse_user_query(str(query_input or ""))

    and_conditions: List[Dict[str, Any]] = []

    # 1. Title Condition: token boundary regex matching title words
    title_text = parsed.normalized_title or ""
    title_words = [w for w in title_text.split() if w]
    if title_words:
        parts = []
        for w in title_words:
            if re.match(r"^\w+$", w):
                parts.append(rf"\b{re.escape(w)}\b")
            else:
                parts.append(re.escape(w))
        pattern = r".*".join(parts)
        try:
            title_regex = re.compile(pattern, re.IGNORECASE)
            if use_caption:
                and_conditions.append({"$or": [{"file_name": title_regex}, {"caption": title_regex}]})
            else:
                and_conditions.append({"file_name": title_regex})
        except re.error:
            pass

    # 2. Season Condition
    if parsed.season is not None:
        s_regex = build_season_regex(parsed.season)
        if use_caption:
            and_conditions.append({"$or": [{"file_name": s_regex}, {"caption": s_regex}]})
        else:
            and_conditions.append({"file_name": s_regex})

    # 3. Episode Condition
    if parsed.episode is not None:
        e_regex = build_episode_regex(parsed.episode)
        if use_caption:
            and_conditions.append({"$or": [{"file_name": e_regex}, {"caption": e_regex}]})
        else:
            and_conditions.append({"file_name": e_regex})

    # 4. Quality Condition
    if parsed.quality:
        q_regex = build_quality_regex(parsed.quality)
        if q_regex:
            if use_caption:
                and_conditions.append({"$or": [{"file_name": q_regex}, {"caption": q_regex}]})
            else:
                and_conditions.append({"file_name": q_regex})

    # 5. Language Condition (Language aliases OR Universal Audio tags)
    if parsed.language:
        l_regex = build_language_regex(parsed.language)
        if l_regex:
            if use_caption:
                and_conditions.append({"$or": [{"file_name": l_regex}, {"caption": l_regex}]})
            else:
                and_conditions.append({"file_name": l_regex})
    elif parsed.universal_audio:
        u_regex = build_universal_audio_regex()
        if use_caption:
            and_conditions.append({"$or": [{"file_name": u_regex}, {"caption": u_regex}]})
        else:
            and_conditions.append({"file_name": u_regex})

    # 6. Year Condition
    if parsed.year:
        y_regex = re.compile(rf"\b{parsed.year}\b")
        if use_caption:
            and_conditions.append({"$or": [{"file_name": y_regex}, {"caption": y_regex}]})
        else:
            and_conditions.append({"file_name": y_regex})

    # 7. File type filter
    if file_type:
        and_conditions.append({"file_type": file_type})

    if not and_conditions:
        return {}
    if len(and_conditions) == 1:
        return and_conditions[0]
    return {"$and": and_conditions}


# ==============================================================================
# 7. RELEVANCE AND RANKING ENGINE (Section 3)
# ==============================================================================

def get_relevance_score_breakdown(doc_filename: str, parsed_query: Any) -> Dict[str, Any]:
    """Calculate deterministic relevance score and return human-readable breakdown."""
    parsed = parsed_query if isinstance(parsed_query, SearchRequest) else parse_user_query(str(parsed_query.get("search") or parsed_query.get("title") or ""))
    clean_fn = clean_media_title_for_comparison(doc_filename).lower()
    raw_fn = str(doc_filename or "").lower()
    target_title = (parsed.normalized_title or "").strip().lower()

    if not target_title:
        return {"tier": "Fallback", "base_score": 100, "bonuses": 0, "total": 100}

    target_year = parsed.year
    tier = "Partial Token"
    base_score = 0
    bonuses = 0

    # Tier 1: Exact title + Year match
    if (target_title == clean_fn or (target_year and f"{target_title} {target_year}" == clean_fn)) and (target_year and str(target_year) in raw_fn):
        tier = "Tier 1: Exact Title + Year"
        base_score = 1000
    # Tier 2: Exact title match without year conflict
    elif target_title == clean_fn:
        tier = "Tier 2: Exact Title"
        base_score = 800
    # Tier 3: Exact phrase in filename
    elif target_title in clean_fn:
        tier = "Tier 3: Exact Phrase Match"
        base_score = 600
    else:
        target_tokens = [w for w in target_title.split() if len(w) > 1]
        if target_tokens:
            matches_count = sum(1 for tok in target_tokens if tok in clean_fn)
            if matches_count == len(target_tokens):
                tier = "Tier 4: All Title Tokens"
                base_score = 400
            elif matches_count > 0:
                tier = "Tier 5: Partial Tokens"
                base_score = 200 + int((matches_count / len(target_tokens)) * 100)
            else:
                tier = "Tier 6: Loose Candidate"
                base_score = 100
        else:
            base_score = 100

    # Bonuses for structured criteria
    if target_year and str(target_year) in raw_fn:
        bonuses += 50
    if parsed.season is not None and matches_season(raw_fn, parsed.season):
        bonuses += 50
    if parsed.episode is not None and matches_episode(raw_fn, parsed.episode):
        bonuses += 50
    if parsed.quality and matches_quality(raw_fn, parsed.quality):
        bonuses += 30
    if parsed.language and matches_language(raw_fn, parsed.language):
        bonuses += 30
    elif parsed.universal_audio and build_universal_audio_regex().search(raw_fn):
        bonuses += 30

    return {
        "tier": tier,
        "base_score": base_score,
        "bonuses": bonuses,
        "total": base_score + bonuses,
    }


def calculate_relevance_score(doc_filename: str, parsed_query: Any) -> int:
    return get_relevance_score_breakdown(doc_filename, parsed_query)["total"]


def rank_media_results(files: List[Any], parsed_query: Any) -> List[Any]:
    """
    Rank media documents deterministically by relevance score, file size, and file_id.
    Preserves both movie and series results when sharing a title.
    """
    if not files:
        return []

    parsed = parsed_query if isinstance(parsed_query, SearchRequest) else parse_user_query(str(getattr(parsed_query, "get", lambda k, d=None: d)("search") or ""))

    def sort_key(doc):
        fn = getattr(doc, "file_name", "") or ""
        score = calculate_relevance_score(fn, parsed)
        size = getattr(doc, "file_size", 0) or 0
        file_id = str(getattr(doc, "file_id", "") or "")
        return (score, size, file_id)

    return sorted(files, key=sort_key, reverse=True)


# ==============================================================================
# 8. IN-MEMORY BOUNDED SEARCH CACHE (Section 5)
# ==============================================================================

class SearchCache:
    """Bounded in-memory LRU/TTL cache for search snapshots and pages."""
    def __init__(self, max_entries: int = 500, ttl_seconds: int = 120):
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self._cache: Dict[str, Tuple[float, Any, int]] = {}

    def make_key(
        self,
        query_norm: str,
        filters: dict,
        offset: int,
        max_results: int,
        year: Any = None,
        language: Any = None,
        quality: Any = None,
        season: Any = None,
        episode: Any = None,
        universal_audio: bool = False,
        file_type: Optional[str] = None,
        db_mode: str = "single",
        sort_version: str = "v9",
    ) -> str:
        f_repr = "-".join(f"{k}:{v}" for k, v in sorted(filters.items())) if filters else "none"
        return (
            f"q:{query_norm}|y:{year}|l:{language}|qul:{quality}|"
            f"s:{season}|e:{episode}|u:{int(universal_audio)}|"
            f"ft:{file_type or 'all'}|db:{db_mode}|ps:{max_results}|"
            f"f:{f_repr}|off:{offset}|v:{sort_version}"
        )

    def get(self, *args, **kwargs) -> Optional[Tuple[List[Any], str, int]]:
        if len(args) == 1 and isinstance(args[0], str):
            key = args[0]
        elif len(args) >= 4:
            query_norm, filters, offset, max_results = args[:4]
            key = self.make_key(query_norm, filters, offset, max_results)
        else:
            key = kwargs.get("cache_key") or ""

        entry = self._cache.get(key)
        if not entry:
            return None
        ts, files, total = entry
        if time.time() - ts > self.ttl:
            self._cache.pop(key, None)
            return None
        return files, str(entry[1]) if total else "", total

    def set(self, *args, **kwargs):
        if len(args) == 3 and isinstance(args[0], str):
            key, files, total = args
        elif len(args) >= 6:
            query_norm, filters, offset, max_results, files, total = args[:6]
            key = self.make_key(query_norm, filters, offset, max_results)
        else:
            key = kwargs.get("cache_key", "")
            files = kwargs.get("files", [])
            total = kwargs.get("total", 0)

        if len(self._cache) >= self.max_entries:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
            self._cache.pop(oldest_key, None)
        self._cache[key] = (time.time(), files, total)

    def clear(self):
        self._cache.clear()


GLOBAL_SEARCH_CACHE = SearchCache()


# ==============================================================================
# 9. SEARCH ANALYTICS (Section 7)
# ==============================================================================

class SearchAnalytics:
    """Bounded in-memory search analytics without collecting sensitive user data."""
    def __init__(self, max_recent: int = 100):
        self.total_queries = 0
        self.zero_result_queries = 0
        self.total_duration_ms = 0.0
        self.recent_zero_results: List[str] = []
        self.max_recent = max_recent
        self.filter_usage: Dict[str, int] = {"quality": 0, "language": 0, "season": 0}

    def record_search(self, query: str, total_results: int, duration_ms: float, filters: Optional[dict] = None):
        self.total_queries += 1
        self.total_duration_ms += duration_ms
        if total_results == 0:
            self.zero_result_queries += 1
            if len(self.recent_zero_results) >= self.max_recent:
                self.recent_zero_results.pop(0)
            self.recent_zero_results.append(query[:50])
        if filters:
            for k in ("quality", "language", "season"):
                if filters.get(k):
                    self.filter_usage[k] = self.filter_usage.get(k, 0) + 1

    def get_stats(self) -> Dict[str, Any]:
        avg_ms = (self.total_duration_ms / self.total_queries) if self.total_queries > 0 else 0.0
        zero_rate = (self.zero_result_queries / self.total_queries * 100) if self.total_queries > 0 else 0.0
        return {
            # Standard field names
            "total_queries": self.total_queries,
            "zero_results": self.zero_result_queries,
            "zero_result_queries": self.zero_result_queries,
            "zero_result_rate_pct": round(zero_rate, 2),
            "zero_result_rate": f"{round(zero_rate, 2)}%",
            "avg_duration_ms": round(avg_ms, 2),
            "avg_latency_ms": round(avg_ms, 2),
            "filter_usage": dict(self.filter_usage),
            "active_filters_used": sum(self.filter_usage.values()),
            "recent_zero_queries": list(self.recent_zero_results[-10:]),
        }


GLOBAL_SEARCH_ANALYTICS = SearchAnalytics()


# ==============================================================================
# 10. SEARCH SESSION & CONCURRENCY COORDINATION (Section 6)
# ==============================================================================

class SearchSession:
    """
    Thread-safe, isolated search session store preserving full request state,
    monotonically increasing revision to discard stale out-of-order callbacks,
    and a cached ranked candidate snapshot for stable pagination.
    """
    def __init__(self, session_key: str, original_query: str, chat_id: int, user_id: int):
        self.session_key = session_key
        self.original_query = original_query
        self.search_request = parse_user_query(original_query)
        self.parsed_query = self.search_request # Backwards compatibility
        self.chat_id = chat_id
        self.user_id = user_id
        self.active_filters: Dict[str, Any] = {}
        # Pre-seed filters detected from query text itself
        if self.search_request.quality:
            self.active_filters["quality"] = self.search_request.quality
        if self.search_request.language:
            self.active_filters["language"] = self.search_request.language
        if self.search_request.season is not None:
            self.active_filters["season"] = str(self.search_request.season)
        if self.search_request.episode is not None:
            self.active_filters["episode"] = str(self.search_request.episode)

        self.revision = 0
        self.created_at = time.time()
        self.updated_at = time.time()

        # Stable ranked candidate snapshot for consistent pagination
        self.snapshot_candidates: List[Any] = []
        self.total_matched_documents: int = 0
        self.candidate_documents_examined: int = 0
        self.ranked_snapshot_count: int = 0
        self.result_scope: str = "complete"

    def increment_revision(self) -> int:
        self.revision += 1
        self.updated_at = time.time()
        return self.revision

    def set_filter(self, filter_type: str, value: Optional[str]):
        self.increment_revision()
        # Invalidate snapshot when active filters change
        self.snapshot_candidates.clear()
        if value is None or value == "homepage":
            self.active_filters.pop(filter_type, None)
        else:
            if filter_type == "quality":
                self.active_filters[filter_type] = canonicalize_quality(value)
            elif filter_type == "language":
                self.active_filters[filter_type] = canonicalize_language(value)
            elif filter_type == "season":
                self.active_filters[filter_type] = str(value)
            elif filter_type == "episode":
                self.active_filters[filter_type] = str(value)

    def reset_filters(self):
        self.increment_revision()
        self.active_filters.clear()
        self.snapshot_candidates.clear()

    def get_query_input(self) -> Dict[str, Any]:
        """Construct multi-filter dictionary input for MongoDB search."""
        return {
            "search": self.search_request.normalized_title or self.original_query,
            **self.active_filters
        }

    def set_snapshot(
        self,
        candidates: List[Any],
        total_matched: int,
        examined: int,
        ranked_count: int,
        scope: str = "complete"
    ):
        self.snapshot_candidates = candidates
        self.total_matched_documents = total_matched
        self.candidate_documents_examined = examined
        self.ranked_snapshot_count = ranked_count
        self.result_scope = scope

    def get_filter_chip(self) -> Optional[str]:
        chips = []
        if "season" in self.active_filters:
            chips.append(f"S{int(self.active_filters['season']):02d}")
        if "episode" in self.active_filters:
            chips.append(f"E{int(self.active_filters['episode']):02d}")
        if "quality" in self.active_filters:
            chips.append(str(self.active_filters["quality"]).upper())
        if "language" in self.active_filters:
            chips.append(str(self.active_filters["language"]).title())
        return " • ".join(chips) if chips else None


class SearchSessionManager:
    """Thread-safe search session store keyed by chat/message session tokens."""
    def __init__(self, max_sessions: int = 1000, ttl_seconds: int = 3600):
        self.max_sessions = max_sessions
        self.ttl = ttl_seconds
        self._sessions: Dict[str, SearchSession] = {}

    def get_or_create(self, session_key: str, query: str, chat_id: int, user_id: int) -> SearchSession:
        now = time.time()
        if session_key in self._sessions:
            sess = self._sessions[session_key]
            if now - sess.updated_at <= self.ttl:
                return sess
        if len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions.keys(), key=lambda k: self._sessions[k].updated_at)
            self._sessions.pop(oldest, None)
        sess = SearchSession(session_key, query, chat_id, user_id)
        self._sessions[session_key] = sess
        return sess

    def get(self, session_key: str) -> Optional[SearchSession]:
        sess = self._sessions.get(session_key)
        if not sess:
            return None
        if time.time() - sess.updated_at > self.ttl:
            self._sessions.pop(session_key, None)
            return None
        return sess

    def clear(self):
        self._sessions.clear()


GLOBAL_SESSION_MANAGER = SearchSessionManager()


# ==============================================================================
# 11. BUTTON BUILDERS & TELEGRAM CALLBACK VALIDATION (Section 6)
# ==============================================================================

def validate_callback_data(data: str) -> str:
    """Validate that callback_data byte length is strictly between 1 and 64 UTF-8 bytes."""
    encoded_len = len(data.encode("utf-8"))
    if encoded_len < 1 or encoded_len > 64:
        raise ValueError(f"Telegram callback_data must be 1-64 bytes, got {encoded_len} bytes: {data!r}")
    return data


class SearchButton:
    """Lightweight button representation decoupled from Telegram client initialization."""
    def __init__(self, text: str, callback_data: Optional[str] = None, url: Optional[str] = None):
        self.text = text
        if callback_data:
            validate_callback_data(callback_data)
        self.callback_data = callback_data
        self.url = url

    def __repr__(self):
        return f"SearchButton(text={self.text!r}, callback_data={self.callback_data!r}, url={self.url!r})"


def set_active_filter(session_key: str, filter_type: str, value: str) -> Dict[str, Any]:
    sess = GLOBAL_SESSION_MANAGER.get_or_create(session_key, "", 0, 0)
    sess.set_filter(filter_type, value)
    return sess.active_filters


def get_active_filters(session_key: str) -> Dict[str, Any]:
    sess = GLOBAL_SESSION_MANAGER.get(session_key)
    return sess.active_filters if sess else {}


def clear_active_filters(session_key: str):
    sess = GLOBAL_SESSION_MANAGER.get(session_key)
    if sess:
        sess.reset_filters()


def get_filter_chip_label(active_filters: Dict[str, Any]) -> Optional[str]:
    chips = []
    if not active_filters:
        return None
    if "season" in active_filters:
        chips.append(f"S{int(active_filters['season']):02d}")
    if "episode" in active_filters:
        chips.append(f"E{int(active_filters['episode']):02d}")
    if "quality" in active_filters:
        chips.append(str(active_filters["quality"]).upper())
    if "language" in active_filters:
        chips.append(str(active_filters["language"]).title())
    return " • ".join(chips) if chips else None


def build_empty_filter_buttons(key: str, active_filter: Optional[str] = None, button_cls=None) -> List[List[Any]]:
    """
    Build persistent filter control bar when a filter yields 0 results.
    Quality, Language, and Season buttons remain visible and interactive.
    """
    if button_cls is None:
        import os
        if str(os.environ.get("TEST_MODE", "")).lower() in ("1", "true", "yes"):
            button_cls = SearchButton
        else:
            try:
                from pyrogram.types import InlineKeyboardButton
                button_cls = InlineKeyboardButton
            except Exception:
                button_cls = SearchButton

    btn = []
    if active_filter:
        btn.append([
            button_cls(f"🎯 Filter: {active_filter}", callback_data=validate_callback_data(f"filter_info#{active_filter}")),
            button_cls("🔄 Reset Filters", callback_data=validate_callback_data(f"reset_filter#{key}"))
        ])
    else:
        btn.append([
            button_cls("🔄 Reset Filters", callback_data=validate_callback_data(f"reset_filter#{key}"))
        ])
    btn.append([
        button_cls("Qᴜᴀʟɪᴛʏ", callback_data=validate_callback_data(f"qualities#{key}")),
        button_cls("Lᴀɴɢᴜᴀɢᴇ", callback_data=validate_callback_data(f"languages#{key}")),
        button_cls("Sᴇᴀsᴏɴ",  callback_data=validate_callback_data(f"seasons#{key}"))
    ])
    btn.append([
        button_cls("↭ ɴᴏ ʀᴇsᴜʟᴛs ꜰᴏᴜɴᴅ ↭", callback_data=validate_callback_data("pages"))
    ])
    return btn


def format_size(size) -> str:
    units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
    try:
        s = float(size)
    except (ValueError, TypeError):
        return "0 MB"
    i = 0
    while s >= 1024.0 and i < len(units) - 1:
        i += 1
        s /= 1024.0
    return "%.2f %s" % (s, units[i])


def get_display_name(file) -> str:
    """Return raw file title as stored in DB without cleaning, falling back to caption if file_name is None/empty."""
    if not file:
        return "File"
    fn = getattr(file, "file_name", None)
    if fn and str(fn).strip() and str(fn).strip().lower() not in ("none", "null"):
        return str(fn).strip()
    cap = getattr(file, "caption", None)
    if cap and str(cap).strip() and str(cap).strip().lower() not in ("none", "null"):
        clean_cap = re.sub(r"<[^>]+>", "", str(cap)).strip()
        if clean_cap:
            return clean_cap
    return str(fn or "File")


def format_button_label(file_name: str, file_size: int, max_len: int = 58) -> str:
    """Format file button: [{size}] {clean_title} cleanly without artificial badge bloat."""
    fn = str(file_name or "").strip()
    size_str = format_size(file_size)
    prefix = f"[{size_str}]"
    avail = max_len - len(prefix) - 1
    if avail > 5 and len(fn) > avail:
        fn = fn[:avail - 1].rstrip() + "…"
    return f"{prefix} {fn}".strip()


def build_search_buttons(
    files: List[Any],
    key: str,
    offset: Any,
    total_results: int,
    req: Any,
    settings: dict,
    active_filter: Optional[str] = None,
    button_cls=None,
    bot_username: str = "bot"
) -> List[List[Any]]:
    """Build uniform search results with active filter chips & persistent filter controls."""
    if button_cls is None:
        import os
        if str(os.environ.get("TEST_MODE", "")).lower() in ("1", "true", "yes"):
            button_cls = SearchButton
        else:
            try:
                from pyrogram.types import InlineKeyboardButton
                button_cls = InlineKeyboardButton
            except Exception:
                button_cls = SearchButton

    u_name = bot_username
    btn = []
    if active_filter:
        btn.append([
            button_cls(f"🎯 Filter: {active_filter}", callback_data=validate_callback_data(f"filter_info#{active_filter}")),
            button_cls("🔄 Reset Filters", callback_data=validate_callback_data(f"reset_filter#{key}"))
        ])
    btn.append([
        button_cls("ʀᴇᴍᴏᴠᴇ ᴀᴅs", url=f"https://t.me/{u_name}?start=premium"),
        button_cls("Sᴇɴᴅ Aʟʟ", callback_data=validate_callback_data(f"sendfiles#{key}"))
    ])
    btn.append([
        button_cls("Qᴜᴀʟɪᴛʏ", callback_data=validate_callback_data(f"qualities#{key}")),
        button_cls("Lᴀɴɢᴜᴀɢᴇ", callback_data=validate_callback_data(f"languages#{key}")),
        button_cls("Sᴇᴀsᴏɴ",  callback_data=validate_callback_data(f"seasons#{key}"))
    ])
    if settings.get("button", True):
        for file in files:
            label = format_button_label(get_display_name(file), getattr(file, "file_size", 0))
            btn.append([button_cls(text=f"🔗 {label}", callback_data=validate_callback_data(f"file#{file.file_id}"))])

    offset_str = str(offset) if offset not in (None, "") else ""
    if offset_str != "":
        max_btn_val = 10 if settings.get("max_btn") else 10
        page_total = math.ceil(int(total_results) / max_btn_val) if total_results else 1
        btn.append([
            button_cls("ᴘᴀɢᴇ", callback_data=validate_callback_data("pages")),
            button_cls(text=f"1/{page_total}", callback_data=validate_callback_data("pages")),
            button_cls(text="ɴᴇxᴛ ⋟", callback_data=validate_callback_data(f"next_{req}_{key}_{offset_str}"))
        ])
    else:
        btn.append([
            button_cls(text="↭ ɴᴏ ᴍᴏʀᴇ ᴘᴀɢᴇꜱ ᴀᴠᴀɪʟᴀʙʟᴇ ↭", callback_data=validate_callback_data("pages"))
        ])
    return btn
