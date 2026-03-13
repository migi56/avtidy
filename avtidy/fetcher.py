from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import quote_plus

import requests


SEARCH_URL = 'https://www.javdatabase.com/?post_type=movies%2Cuncensored&s={query}'
JABLE_URL = 'https://jable.tv/videos/{slug}/'
AV_WIKI_URL = 'https://av-wiki.net/{slug}/'
AVWIKIDB_URL = 'https://avwikidb.com/en/video/{code}/'
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36',
    'Accept-Language': 'ja-JP,ja;q=0.9,zh-TW;q=0.8,en-US;q=0.7,en;q=0.6',
}


def _clean_html_text(fragment: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', fragment)
    text = unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _html_to_text(html: str) -> str:
    html = re.sub(r'<(br|/p|/div|/li|/tr|/h[1-6])[^>]*>', '\n', html, flags=re.I)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = unescape(html)
    lines = [re.sub(r'\s+', ' ', line).strip() for line in html.splitlines()]
    return '\n'.join(line for line in lines if line)


def _labeled_links(html: str, label: str) -> list[str]:
    pattern = re.compile(
        rf'(?is)<(?:p|div|li)[^>]*>[^<]*<b[^>]*>[^<]*{re.escape(label)}[^<]*</b>(.*?)</(?:p|div|li)>'
    )
    values: list[str] = []
    for match in pattern.finditer(html):
        block = match.group(1)
        for anchor in re.findall(r'<a[^>]*>(.*?)</a>', block, flags=re.I | re.S):
            text = _clean_html_text(anchor)
            if text:
                values.append(text)
    return values


def _labeled_single(html: str, label: str) -> str | None:
    pattern = re.compile(
        rf'(?is)<(?:p|div|li)[^>]*>\s*<b[^>]*>[^<]*{re.escape(label)}[^<]*</b>\s*[:\-–]?\s*(.*?)</(?:p|div|li)>'
    )
    match = pattern.search(html)
    if not match:
        return None

    block = match.group(1)
    block = re.split(r'<b[^>]*>.*?</b>', block, maxsplit=1)[0]
    block = re.sub(r'(?is)<br\s*/?>', '\n', block)
    first_line = next((line for line in block.splitlines() if line.strip()), '')
    return _clean_html_text(first_line)


def _extract_meta_content(html: str, attr: str, value: str) -> str:
    match = re.search(
        rf'(?is)<meta[^>]+{attr}="{re.escape(value)}"[^>]+content="([^"]+)"',
        html,
    )
    if match:
        return _clean_html_text(match.group(1))
    match = re.search(
        rf'(?is)<meta[^>]+content="([^"]+)"[^>]+{attr}="{re.escape(value)}"',
        html,
    )
    return _clean_html_text(match.group(1)) if match else ''


def _fetch_text(url: str) -> str:
    response = requests.get(url, timeout=20, headers=REQUEST_HEADERS)
    response.raise_for_status()
    return response.text or ''


def _normalize_code(code: str) -> str:
    return re.sub(r'[^A-Za-z0-9]+', '', code).upper()


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r'[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]', text or ''))


def _normalize_title(title: str, code: str, actresses: list[str] | None = None) -> str:
    text = _clean_html_text(title)
    text = re.sub(r'\s+-\s+JAV Database.*$', '', text, flags=re.I)
    text = re.sub(r'\s+-\s+Jable\.TV.*$', '', text, flags=re.I)
    text = re.sub(r'\s+\|.*$', '', text)
    if code:
        text = re.sub(rf'^{re.escape(code)}\s*[-:：]?\s*', '', text, flags=re.I)
    for actress in actresses or []:
        if actress and text.endswith(f' {actress}'):
            text = text[: -(len(actress) + 1)].rstrip(' -')
    return text.strip()


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _extract_dl_value(html: str, label: str) -> str:
    match = re.search(rf'(?is)<dt>\s*{re.escape(label)}\s*</dt>\s*<dd>(.*?)</dd>', html)
    return _clean_html_text(match.group(1)) if match else ''


def _extract_dl_links(html: str, label: str) -> list[str]:
    match = re.search(rf'(?is)<dt>\s*{re.escape(label)}\s*</dt>\s*<dd>(.*?)</dd>', html)
    if not match:
        return []
    return _dedupe_keep_order(
        [_clean_html_text(item) for item in re.findall(r'<a[^>]*>(.*?)</a>', match.group(1), flags=re.I | re.S)]
    )


def _merge_missing_metadata(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if not fallback:
        return primary

    merged = dict(primary)
    for field in ['title', 'release_date', 'studio', 'runtime', 'director', 'series', 'dvd_id', 'content_id']:
        if fallback.get(field) and not merged.get(field):
            merged[field] = fallback[field]

    actresses = fallback.get('actresses')
    if isinstance(actresses, list) and actresses and not merged.get('actresses'):
        merged['actresses'] = actresses

    genres = fallback.get('genres')
    if isinstance(genres, list) and genres and not merged.get('genres'):
        merged['genres'] = genres

    if fallback.get('cover_url') and not merged.get('cover_url'):
        merged['cover_url'] = fallback['cover_url']
    if fallback.get('source_url_ja') and not merged.get('source_url_ja'):
        merged['source_url_ja'] = fallback['source_url_ja']
    if fallback.get('title_english') and not merged.get('title_english'):
        merged['title_english'] = fallback['title_english']

    actress_aliases = fallback.get('actress_aliases')
    if isinstance(actress_aliases, dict) and actress_aliases:
        current = merged.get('actress_aliases')
        alias_map = dict(current) if isinstance(current, dict) else {}
        for japanese_name, english_name in actress_aliases.items():
            if japanese_name and english_name and japanese_name not in alias_map:
                alias_map[japanese_name] = english_name
        merged['actress_aliases'] = alias_map

    return merged


def fetch_search(query: str) -> list[dict[str, str]]:
    html = _fetch_text(SEARCH_URL.format(query=quote_plus(query)))
    card_pattern = re.compile(
        r'(?is)<div[^>]+class="[^"]*\bcard\b[^"]*\bborderlesscard\b[^"]*"[^>]*>(.*?)</div>'
    )
    results: list[dict[str, str]] = []

    for match in card_pattern.finditer(html):
        block = match.group(1)
        code = ''
        link = ''

        code_match = re.search(
            r'(?is)<p[^>]+class="[^"]*\bpcard\b[^"]*"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            block,
        )
        if code_match:
            link = code_match.group(1)
            code = _clean_html_text(code_match.group(2))

        title_match = re.search(
            r'(?is)<(?:div|p|span)[^>]+class="[^"]*\bmt-auto\b[^"]*"[^>]*>(.*?)</(?:div|p|span)>',
            block,
        )
        title = code
        if title_match:
            anchor_match = re.search(r'(?is)<a[^>]*>(.*?)</a>', title_match.group(1))
            if anchor_match:
                title = _clean_html_text(anchor_match.group(1)) or code

        release_date = ''
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', _clean_html_text(block))
        if date_match:
            release_date = date_match.group(1)

        studio = ''
        studio_match = re.search(
            r'(?is)<span[^>]+class="[^"]*\bbtn(?:-primary)?\b[^"]*"[^>]*>.*?<a[^>]*>(.*?)</a>',
            block,
        )
        if studio_match:
            studio = _clean_html_text(studio_match.group(1))

        if link:
            results.append(
                {
                    'code': code,
                    'title': title,
                    'link': link,
                    'release_date': release_date,
                    'studio': studio,
                }
            )

    return results


def fetch_poster_url_from_html(html: str) -> str:
    block_match = re.search(r'(?is)<div[^>]+id="poster-container"[^>]*>(.*?)</div>', html)
    if block_match:
        image_match = re.search(r'<img[^>]+src="([^"]+)"', block_match.group(1), flags=re.I)
        if image_match:
            return image_match.group(1)

    image_match = re.search(
        r'(?is)<div[^>]+class="[^"]*\bposter\b[^"]*"[^>]*>.*?<img[^>]+src="([^"]+)"',
        html,
    )
    if image_match:
        return image_match.group(1)

    image_match = re.search(
        r'<img[^>]+alt="[^"]*JAV Movie Cover[^"]*"[^>]*src="([^"]+)"',
        html,
        flags=re.I,
    )
    return image_match.group(1) if image_match else ''


def fetch_movie_metadata(page_url: str) -> dict[str, Any]:
    html = _fetch_text(page_url)
    page_text = _html_to_text(html)

    def extract(patterns: list[str], max_words: int | None = None) -> str | None:
        for pattern in patterns:
            regex = re.compile(rf'{pattern}\s*[:\-–]?\s*(.*?)\s*(?:\n|$)', re.I)
            match = regex.search(page_text)
            if match:
                value = re.sub(r'\s{2,}', ' ', match.group(1).strip())
                if max_words is not None:
                    words = value.split()
                    if len(words) > max_words:
                        value = ' '.join(words[:max_words])
                return value
        return None

    title_match = re.search(r'(?is)<h1[^>]*>(.*?)</h1>', html)
    actresses = sorted(set(_labeled_links(html, 'Idol')))
    genres = sorted(set(_labeled_links(html, 'Genre')))

    director = _labeled_single(html, 'Director') or extract(['Director'], max_words=8) or ''
    if 'Genre' in director or 'Idol' in director:
        director = ''

    return {
        'title': _normalize_title(_clean_html_text(title_match.group(1)) if title_match else '', '', actresses),
        'dvd_id': _labeled_single(html, 'DVD ID') or extract(['DVD ID', 'DVD'], max_words=4) or '',
        'content_id': _labeled_single(html, 'Content ID') or extract(['Content ID'], max_words=4) or '',
        'release_date': _labeled_single(html, 'Release Date') or extract(['Released'], max_words=4) or '',
        'runtime': _labeled_single(html, 'Runtime') or extract(['Runtime'], max_words=8) or '',
        'studio': _labeled_single(html, 'Studio') or extract(['Studio'], max_words=8) or '',
        'director': director,
        'series': _labeled_single(html, 'Series') or extract(['Series'], max_words=8) or '',
        'actresses': actresses,
        'genres': genres,
        'cover_url': fetch_poster_url_from_html(html),
        'source_url': page_url,
    }


def fetch_jable_metadata_by_code(code: str) -> dict[str, Any]:
    slug = code.strip().lower()
    if not slug:
        return {}

    url = JABLE_URL.format(slug=slug)
    try:
        html = _fetch_text(url)
    except requests.RequestException:
        return {}

    if _normalize_code(code) not in _normalize_code(html):
        return {}

    models_block_match = re.search(r'(?is)<div class="models">(.*?)</div>', html)
    models_block = models_block_match.group(1) if models_block_match else ''
    actresses = _dedupe_keep_order(
        [_clean_html_text(name) for name in re.findall(r'title="([^"]+)"', models_block, flags=re.I | re.S)]
    )
    if not actresses:
        actresses = [name for name in _dedupe_keep_order(re.findall(r'title="([^"]+)"', html, flags=re.I | re.S)) if _contains_cjk(name)]

    raw_title = _extract_meta_content(html, 'property', 'og:title') or _extract_meta_content(html, 'name', 'title')
    if not raw_title:
        h4_match = re.search(r'(?is)<h4[^>]*>(.*?)</h4>', html)
        raw_title = _clean_html_text(h4_match.group(1)) if h4_match else ''

    title = _normalize_title(raw_title, code, actresses)
    cover_url = _extract_meta_content(html, 'property', 'og:image')

    if not _contains_cjk(title) and not any(_contains_cjk(name) for name in actresses):
        return {}

    return {
        'title': title,
        'actresses': actresses,
        'cover_url': cover_url,
        'source_url_ja': url,
    }


def fetch_av_wiki_metadata_by_code(code: str) -> dict[str, Any]:
    slug = code.strip().lower()
    if not slug:
        return {}

    url = AV_WIKI_URL.format(slug=slug)
    try:
        html = _fetch_text(url)
    except requests.RequestException:
        return {}

    if _normalize_code(code) not in _normalize_code(html):
        return {}

    actresses = _extract_dl_links(html, 'AV女優名')
    studio = _extract_dl_value(html, 'メーカー')
    release_date = _extract_dl_value(html, '配信開始日') or _extract_dl_value(html, '発売日')
    dvd_id = _extract_dl_value(html, 'メーカー品番') or _extract_dl_value(html, '品番')
    content_id = _extract_dl_value(html, 'FANZA品番')
    series = _extract_dl_value(html, 'シリーズ')
    page_title = _clean_html_text(_extract_meta_content(html, 'property', 'og:title'))
    title = page_title
    for token in ['に出てるAV女優名まとめ', 'に出てるAV女優は誰？ 名前は？']:
        if token in title:
            title = title.split(token, 1)[0].strip()
    title = _normalize_title(title, code, actresses)
    cover_match = re.search(r'data-src="([^"]*pics\.dmm\.co\.jp[^"]+)"', html)
    cover_url = cover_match.group(1) if cover_match else ''

    if not any([actresses, studio, release_date, title]):
        return {}

    return {
        'title': title,
        'actresses': actresses,
        'studio': studio,
        'release_date': release_date,
        'dvd_id': dvd_id,
        'content_id': content_id,
        'series': series,
        'cover_url': cover_url,
        'source_url_ja': url,
    }


def fetch_avwikidb_metadata_by_code(code: str) -> dict[str, Any]:
    normalized = code.strip().upper()
    if not normalized:
        return {}

    url = AVWIKIDB_URL.format(code=normalized)
    try:
        html = _fetch_text(url)
    except requests.RequestException:
        return {}

    if 'Just a moment...' in html or _normalize_code(code) not in _normalize_code(html):
        return {}

    page_text = _html_to_text(html)
    actresses = _dedupe_keep_order(re.findall(r'Actress\s*\n([^\n]+)', page_text, flags=re.I))
    title = _extract_meta_content(html, 'property', 'og:title')
    release_date_match = re.search(r'(\d{4}-\d{2}-\d{2})', page_text)
    release_date = release_date_match.group(1) if release_date_match else ''
    studio_match = re.search(r'Maker\s*\n([^\n]+)', page_text, flags=re.I)
    studio = studio_match.group(1).strip() if studio_match else ''

    if not any([title, actresses, release_date, studio]):
        return {}

    return {
        'title': _normalize_title(title, code, actresses),
        'actresses': actresses,
        'release_date': release_date,
        'studio': studio,
        'source_url_ja': url,
    }


def apply_kanji_fallback(primary: dict[str, Any], fallback: dict[str, Any], code: str) -> dict[str, Any]:
    if not fallback:
        return primary

    merged = dict(primary)
    english_title = str(primary.get('title') or '').strip()
    fallback_title = str(fallback.get('title') or '').strip()
    fallback_actresses = [str(item).strip() for item in fallback.get('actresses', []) if str(item).strip()]
    english_actresses = [str(item).strip() for item in primary.get('actresses', []) if str(item).strip()]

    if fallback_title and _contains_cjk(fallback_title):
        merged['title'] = fallback_title
        normalized_english_title = _normalize_title(english_title, code, english_actresses)
        if normalized_english_title and normalized_english_title != fallback_title:
            merged['title_english'] = normalized_english_title

    if fallback_actresses and any(_contains_cjk(name) for name in fallback_actresses):
        merged['actresses'] = fallback_actresses
        if english_actresses:
            alias_map: dict[str, str] = {}
            if len(english_actresses) == len(fallback_actresses):
                for japanese_name, english_name in zip(fallback_actresses, english_actresses):
                    if english_name and japanese_name != english_name:
                        alias_map[japanese_name] = english_name
            elif len(fallback_actresses) == 1 and len(english_actresses) == 1 and fallback_actresses[0] != english_actresses[0]:
                alias_map[fallback_actresses[0]] = english_actresses[0]
            if alias_map:
                merged['actress_aliases'] = alias_map

    if fallback.get('cover_url') and not merged.get('cover_url'):
        merged['cover_url'] = fallback['cover_url']
    if fallback.get('source_url_ja') and not merged.get('source_url_ja'):
        merged['source_url_ja'] = fallback['source_url_ja']
    return merged


def lookup_metadata_by_code(code: str) -> dict[str, Any]:
    results = fetch_search(code)
    metadata: dict[str, Any] = {'code': code}

    if results:
        normalized_code = _normalize_code(code)
        selected = next((item for item in results if _normalize_code(item.get('code', '')) == normalized_code), results[0])
        metadata = fetch_movie_metadata(selected['link'])

        if not metadata.get('title'):
            metadata['title'] = selected.get('title', '')
        if not metadata.get('release_date'):
            metadata['release_date'] = selected.get('release_date', '')
        if not metadata.get('studio'):
            metadata['studio'] = selected.get('studio', '')

        metadata['code'] = selected.get('code') or code

    code_value = str(metadata.get('code') or code)
    metadata['title'] = _normalize_title(str(metadata.get('title') or ''), code_value, metadata.get('actresses'))

    for fallback_fetcher in [fetch_av_wiki_metadata_by_code, fetch_avwikidb_metadata_by_code]:
        fallback = fallback_fetcher(code_value)
        metadata = _merge_missing_metadata(metadata, fallback)

    jable_fallback = fetch_jable_metadata_by_code(code_value)
    metadata = apply_kanji_fallback(metadata, jable_fallback, code_value)
    metadata['code'] = metadata.get('code') or code
    return metadata
