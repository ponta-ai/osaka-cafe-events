import json
import time
import unicodedata
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag


# 取得先やHTML解析の設定を一か所に集め、サイト側の変更に対応しやすくします。
OSAKA_EVENTS_URL = "https://www.kokuchpro.com/s/area-%E5%A4%A7%E9%98%AA%E5%BA%9C/"
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
}

# イベント詳細へのリンクと、そのリンクを含む一覧カードの候補です。
EVENT_LINK_SELECTOR = 'a[href*="/event/"]'
EVENT_CARD_SELECTOR = ", ".join(
    (
        "article",
        "li[class*='event']",
        "div[class*='event_list']",
        "div[class*='event-list']",
        "div[class*='event_item']",
        "div[class*='event-item']",
    )
)

# 一覧ページで表示される項目の候補です。構造が変わったときは主にここを直します。
EVENT_FIELD_SELECTORS = {
    "date": (".event_date", ".event-date", "[class*='date']", "time"),
    "venue": (".event_place", ".event-place", ".venue", "[class*='place']"),
    "area": (".event_area", ".event-area", ".area", "[class*='area']"),
    "fee": (".event_fee", ".event-fee", ".fee", "[class*='fee']"),
    "capacity": (
        ".event_capacity",
        ".event-capacity",
        ".capacity",
        "[class*='capacity']",
    ),
    "category": (
        ".event_category",
        ".event-category",
        ".category",
        "[class*='category']",
    ),
    "organizer": (
        ".event_organizer",
        ".event-organizer",
        ".organizer",
        "[class*='organizer']",
    ),
    "description": (
        ".event_description",
        ".event-description",
        ".description",
        ".summary",
    ),
}

EVENT_FIELD_LABELS = {
    "date": ("開催日時", "日時", "日程"),
    "venue": ("開催場所", "会場"),
    "area": ("地域", "エリア"),
    "fee": ("参加費", "料金"),
    "capacity": ("定員", "募集人数"),
    "category": ("カテゴリ", "ジャンル"),
    "organizer": ("主催", "主催者"),
}

# 詳細ページでは構造化データを優先し、見つからない項目だけHTML表示から補います。
DETAIL_FIELD_LABELS = {
    "date": ("開催日時", "日時", "日程"),
    "venue": ("会場", "会場名", "開催場所"),
    "address": ("住所", "会場住所", "所在地"),
    "fee": ("参加費", "料金", "費用"),
    "capacity": ("定員", "募集人数"),
}
DETAIL_DESCRIPTION_SELECTORS = (
    "[itemprop='description']",
    ".event_description",
    ".event-description",
    "#event_description",
    "meta[name='description']",
)
ACCESS_RESTRICTION_MARKERS = (
    "captcha",
    "cf-chl-captcha",
    "アクセスが制限されています",
    "アクセスが集中しています",
    "too many requests",
)


class EventFetchError(RuntimeError):
    """イベント一覧を安全に取得できなかった場合のエラー。"""


class AccessRestrictionError(EventFetchError):
    """403、429、CAPTCHAなどのアクセス制限を検出した場合のエラー。"""


class DetailFetchResults(list):
    """取得できた詳細と、取得失敗の情報をまとめて保持するリスト。"""

    def __init__(self):
        super().__init__()
        self.failures = []
        self.stopped_reason = None


# カフェを表す一般的な言葉です。
# 判定語を増やしたい場合は、このタプルに文字列を追加します。
CAFE_KEYWORDS = (
    "カフェ",
    "cafe",
    "café",
    "喫茶店",
    "コーヒー",
    "珈琲",
)

# 店名からもカフェと判断できるよう、代表的なチェーン名をまとめます。
CAFE_CHAIN_NAMES = (
    "スターバックス",
    "スタバ",
    "Starbucks",
    "ドトール",
    "DOUTOR",
    "タリーズ",
    "TULLY'S",
    "コメダ",
    "星乃珈琲",
    "サンマルクカフェ",
    "PRONTO",
    "プロント",
)

# 一般的な言葉とチェーン名を一つにまとめ、判定処理を単純にします。
CAFE_LOCATION_TERMS = CAFE_KEYWORDS + CAFE_CHAIN_NAMES


def is_cafe_location(location: str) -> bool:
    """開催場所の文字列にカフェを示す言葉が含まれるか判定する。"""
    # 空文字や None など、文字列でない値はカフェではないものとして扱います。
    if not isinstance(location, str) or not location:
        return False

    # 全角英字などをそろえ、英字の大文字・小文字を区別せず比較します。
    normalized_location = unicodedata.normalize("NFKC", location).casefold()

    return any(
        unicodedata.normalize("NFKC", term).casefold() in normalized_location
        for term in CAFE_LOCATION_TERMS
    )


def filter_cafe_events(events: list[dict]) -> list[dict]:
    """イベント一覧から、カフェで開催されるイベントだけを取り出す。"""
    # 元の一覧は変更せず、条件に合うイベントを新しい一覧として返します。
    return [
        event
        for event in events
        if is_cafe_location(event.get("venue"))
    ]


def fetch_event_page(
    url: str = OSAKA_EVENTS_URL,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """公開イベント一覧を1回だけHTTP取得し、HTML文字列を返す。"""
    try:
        # requests.get はこの1回だけです。ページ送りや詳細ページ取得は行いません。
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
    except requests.Timeout as exc:
        raise EventFetchError(
            f"イベント一覧の取得が{timeout}秒でタイムアウトしました: {url}"
        ) from exc
    except requests.RequestException as exc:
        raise EventFetchError(f"イベント一覧の取得に失敗しました: {url} ({exc})") from exc

    if response.status_code in (401, 403, 429):
        raise EventFetchError(
            "サイトのアクセス制限によりイベント一覧を取得できませんでした: "
            f"HTTP {response.status_code} {url}"
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise EventFetchError(
            f"イベント一覧の取得でHTTPエラーが発生しました: {exc}"
        ) from exc

    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        raise EventFetchError(
            "イベント一覧ではない応答を受け取りました: "
            f"Content-Type={content_type or '不明'} {url}"
        )

    return response.text


def fetch_detail_page(
    url: str,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """イベント詳細ページを1回取得し、アクセス制限も検査する。"""
    try:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=timeout)
    except requests.Timeout as exc:
        raise EventFetchError(
            f"詳細ページの取得が{timeout}秒でタイムアウトしました: {url}"
        ) from exc
    except requests.RequestException as exc:
        raise EventFetchError(f"詳細ページの取得に失敗しました: {url} ({exc})") from exc

    if response.status_code in (403, 429):
        raise AccessRestrictionError(
            "サイトのアクセス制限により詳細ページを取得できませんでした: "
            f"HTTP {response.status_code} {url}"
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise EventFetchError(f"詳細ページでHTTPエラーが発生しました: {exc}") from exc

    content_type = response.headers.get("Content-Type", "")
    if "html" not in content_type.lower():
        raise EventFetchError(
            "詳細ページではない応答を受け取りました: "
            f"Content-Type={content_type or '不明'} {url}"
        )

    normalized_html = response.text.casefold()
    if any(marker.casefold() in normalized_html for marker in ACCESS_RESTRICTION_MARKERS):
        raise AccessRestrictionError(
            f"CAPTCHAまたはアクセス制限画面を検出しました: {url}"
        )

    return response.text


def _clean_text(element: Optional[Tag]) -> Optional[str]:
    """HTML要素内の余分な空白を除去し、空ならNoneを返す。"""
    if element is None:
        return None

    text = " ".join(element.stripped_strings)
    return text or None


def _select_field(card: Tag, field_name: str) -> Optional[str]:
    """CSSセレクタまたは日本語の項目名から値を取得する。"""
    for selector in EVENT_FIELD_SELECTORS[field_name]:
        value = _clean_text(card.select_one(selector))
        if value:
            return value

    # CSSクラスが変わっても、dt/dd形式や「項目名: 値」形式なら取得できます。
    labels = EVENT_FIELD_LABELS.get(field_name, ())
    for label in labels:
        heading = card.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name in ("dt", "th")
            and tag.get_text(" ", strip=True).rstrip("：:") == label
        )
        if heading is not None:
            value = _clean_text(heading.find_next_sibling(("dd", "td")))
            if value:
                return value

        for text in card.stripped_strings:
            normalized = text.strip()
            for separator in ("：", ":"):
                prefix = f"{label}{separator}"
                if normalized.startswith(prefix):
                    value = normalized[len(prefix):].strip()
                    if value:
                        return value

    return None


def _find_labeled_value(container: Tag, labels: tuple) -> Optional[str]:
    """「会場」「住所」などの表示ラベルに対応する値を探す。"""
    for label in labels:
        heading = container.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name in ("dt", "th")
            and tag.get_text(" ", strip=True).rstrip("：:") == label
        )
        if heading is not None:
            value = _clean_text(heading.find_next_sibling(("dd", "td")))
            if value:
                return value

        # ラベルと値が隣接する別要素の場合にも対応します。
        label_element = container.find(
            lambda tag: isinstance(tag, Tag)
            and tag.name in ("div", "span", "p", "strong", "label")
            and tag.get_text(" ", strip=True).rstrip("：:") == label
        )
        if label_element is not None:
            value = _clean_text(label_element.find_next_sibling())
            if value:
                return value

        for text in container.stripped_strings:
            normalized = text.strip()
            for separator in ("：", ":"):
                prefix = f"{label}{separator}"
                if normalized.startswith(prefix):
                    value = normalized[len(prefix):].strip()
                    if value:
                        return value

    return None


def _iter_json_ld_items(soup: BeautifulSoup):
    """詳細ページ内のJSON-LDを、入れ子も含めて順番に返す。"""
    def walk(value):
        if isinstance(value, dict):
            yield value
            graph = value.get("@graph")
            if isinstance(graph, list):
                for child in graph:
                    yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        yield from walk(data)


def _find_event_json_ld(soup: BeautifulSoup) -> dict:
    """JSON-LDからEvent型のデータを探す。"""
    for item in _iter_json_ld_items(soup):
        item_type = item.get("@type")
        types = item_type if isinstance(item_type, list) else [item_type]
        if "Event" in types:
            return item
    return {}


def _address_text(address) -> Optional[str]:
    """文字列またはPostalAddress形式の住所を読みやすく結合する。"""
    if isinstance(address, str):
        return address.strip() or None
    if not isinstance(address, dict):
        return None

    raw_parts = [
        address.get("postalCode"),
        address.get("addressRegion"),
        address.get("addressLocality"),
        address.get("streetAddress"),
    ]
    parts = []
    for raw_part in raw_parts:
        if not raw_part:
            continue
        part = str(raw_part).strip()
        # 例: addressRegionが「大阪府」、addressLocalityが「大阪府大阪市」の場合、
        # 連続する「大阪府大阪府」を一つにまとめます。
        if parts and part.startswith(parts[-1]):
            part = part[len(parts[-1]):].lstrip()
        if part:
            parts.append(part)
    return " ".join(parts) or None


def _offer_fee(offers) -> Optional[str]:
    """JSON-LDの参加費を通貨付き文字列へ変換する。"""
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict) or offers.get("price") is None:
        return None

    price = str(offers["price"])
    currency = offers.get("priceCurrency")
    return f"{price} {currency}" if currency else price


def parse_event_detail(html: str, url: str) -> dict:
    """詳細ページHTMLからイベント情報を辞書へ変換する。"""
    soup = BeautifulSoup(html, "html.parser")
    structured = _find_event_json_ld(soup)
    location = structured.get("location")
    if isinstance(location, list):
        location = location[0] if location else None
    location = location if isinstance(location, dict) else {}

    title_element = soup.select_one("h1") or soup.select_one("meta[property='og:title']")
    title_fallback = (
        title_element.get("content")
        if isinstance(title_element, Tag) and title_element.name == "meta"
        else _clean_text(title_element)
    )

    description = structured.get("description")
    if not description:
        for selector in DETAIL_DESCRIPTION_SELECTORS:
            element = soup.select_one(selector)
            if element is None:
                continue
            description = element.get("content") if element.name == "meta" else _clean_text(element)
            if description:
                break

    return {
        "title": structured.get("name") or title_fallback,
        "date": structured.get("startDate")
        or _find_labeled_value(soup, DETAIL_FIELD_LABELS["date"]),
        # 会場名は構造化データのPlace.nameを最優先します。
        "venue": location.get("name")
        or _find_labeled_value(soup, DETAIL_FIELD_LABELS["venue"]),
        "address": _address_text(location.get("address"))
        or _find_labeled_value(soup, DETAIL_FIELD_LABELS["address"]),
        "fee": _offer_fee(structured.get("offers"))
        or _find_labeled_value(soup, DETAIL_FIELD_LABELS["fee"]),
        "capacity": structured.get("maximumAttendeeCapacity")
        or _find_labeled_value(soup, DETAIL_FIELD_LABELS["capacity"]),
        "description": description,
        "url": url,
    }


def fetch_event_details(
    events: list[dict],
    interval_seconds: float = 1.0,
) -> list[dict]:
    """重複しない全イベントの詳細を、1秒以上の間隔で順番に取得する。"""
    if interval_seconds < 1.0:
        raise ValueError("詳細ページへのアクセス間隔は1秒以上にしてください。")

    # 一覧側のイベントIDによる重複除去を維持しつつ、同一URLへのアクセスも防ぎます。
    targets = []
    seen_urls = set()
    for event in events:
        url = event.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        targets.append(event)

    details = DetailFetchResults()
    for index, event in enumerate(targets, start=1):
        if index > 1:
            time.sleep(interval_seconds)

        url = event["url"]
        print(f"{index}/{len(targets)} 詳細ページ取得中", flush=True)
        try:
            html = fetch_detail_page(url)
            details.append(parse_event_detail(html, url))
        except AccessRestrictionError as exc:
            reason = str(exc)
            details.failures.append({"url": url, "reason": reason})
            details.stopped_reason = reason
            print(f"取得停止：{reason}", flush=True)
            break
        except EventFetchError as exc:
            reason = str(exc)
            details.failures.append({"url": url, "reason": reason})
            print(f"詳細ページ取得失敗：{url}（{reason}）", flush=True)

    return details


def print_detail_results(events: list[dict]) -> None:
    """詳細ページの取得結果とカフェ判定を表示する。"""
    for event in events:
        print(f"タイトル：{event.get('title') or '不明'}")
        print(f"会場名：{event.get('venue') or '不明'}")
        print(f"住所：{event.get('address') or '不明'}")
        print(f"カフェ判定：{is_cafe_location(event.get('venue'))}")
        print(f"URL：{event.get('url') or '不明'}")
        print()


def _event_key(url: str) -> Optional[str]:
    """同じイベントの複数開催日をまとめるための識別子を返す。"""
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0] != "event":
        return None

    # /event/イベントID/開催回ID/ でも、イベントIDが同じなら一覧では1件にします。
    return "/".join(path_parts[:2])


def _find_event_card(link: Tag) -> Tag:
    """イベントリンクを囲む一覧カードを見つける。"""
    # タイトルだけの要素を避け、項目情報を含む最も近い祖先を選びます。
    field_selector = ", ".join(
        selector
        for selectors in EVENT_FIELD_SELECTORS.values()
        for selector in selectors
    )
    parent = link.parent
    for _ in range(8):
        if not isinstance(parent, Tag):
            break
        if parent.select_one(field_selector) is not None:
            return parent
        parent = parent.parent

    card = link.find_parent(EVENT_CARD_SELECTOR)
    if isinstance(card, Tag):
        return card

    # クラス名が変わった場合も、近くのliまたはdivを解析対象にします。
    return link.find_parent(("li", "div")) or link


def parse_event_card(card: Tag, link: Tag, base_url: str) -> dict:
    """一覧カード1件を、後続処理で扱いやすい辞書へ変換する。"""
    return {
        "title": _clean_text(link),
        "url": urljoin(base_url, link.get("href", "")),
        "date": _select_field(card, "date"),
        "venue": _select_field(card, "venue"),
        "area": _select_field(card, "area"),
        "fee": _select_field(card, "fee"),
        "capacity": _select_field(card, "capacity"),
        "category": _select_field(card, "category"),
        "organizer": _select_field(card, "organizer"),
        "description": _select_field(card, "description"),
    }


def parse_event_list(html: str, base_url: str = OSAKA_EVENTS_URL) -> list[dict]:
    """イベント一覧HTMLを辞書のリストへ変換する。"""
    soup = BeautifulSoup(html, "html.parser")
    events = []
    seen_event_keys = set()

    for link in soup.select(EVENT_LINK_SELECTOR):
        event_url = urljoin(base_url, link.get("href", ""))
        event_key = _event_key(event_url)
        if event_key is None or event_key in seen_event_keys:
            continue

        event = parse_event_card(_find_event_card(link), link, base_url)
        if event["title"]:
            events.append(event)
            seen_event_keys.add(event_key)

    if not events:
        raise EventFetchError(
            "イベントを1件も解析できませんでした。"
            "サイトのHTML構造またはアクセス制限を確認してください。"
        )

    return events


def fetch_osaka_events() -> list[dict]:
    """大阪府の公開イベント一覧を1ページだけ取得して解析する。"""
    html = fetch_event_page()
    return parse_event_list(html)


def print_event_preview(events: list[dict], limit: int = 5) -> None:
    """取得結果の先頭だけをターミナルで確認しやすく表示する。"""
    print(f"取得したイベント件数: {len(events)}件")
    for index, event in enumerate(events[:limit], start=1):
        print(f"\n{index}. {event['title'] or '（タイトル不明）'}")
        print(f"   開催日: {event['date'] or '（一覧ページに記載なし）'}")
        print(f"   会場: {event['venue'] or '（一覧ページに記載なし）'}")
        print(f"   URL: {event['url']}")


if __name__ == "__main__":
    try:
        print_event_preview(fetch_osaka_events())
    except EventFetchError as exc:
        raise SystemExit(f"取得エラー: {exc}") from exc
