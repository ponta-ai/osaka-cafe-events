import argparse
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Optional

from src.fetch_events import (
    EventFetchError,
    fetch_event_details,
    fetch_osaka_events,
    fetch_prefecture_events,
    filter_cafe_events,
)


OUTPUT_FILE = Path("output/osaka_cafe_events.html")
KANSAI_OUTPUT_FILE = Path("output/kansai_cafe_events.html")
TARGET_REGIONS = (
    ("大阪", "大阪府", "osaka"),
    ("京都", "京都府", "kyoto"),
    ("兵庫", "兵庫県", "hyogo"),
)
JAPANESE_WEEKDAYS = ("月", "火", "水", "木", "金", "土", "日")
CATEGORY_RULES = (
    ("AI・IT・技術", ("ai", "人工知能", "it", "プログラミング", "エンジニア", "テクノロジー", "dx")),
    ("語学・国際交流", ("国際交流", "英語", "英会話", "語学", "言語交換", "外国語", "留学")),
    ("投資・金融", ("投資", "資産運用", "株式", "株", "fx", "金融", "お金", "マネー")),
    ("婚活・恋活", ("婚活", "恋活", "恋人", "結婚", "お見合い", "マッチングパーティー")),
    ("当事者会・悩み相談", ("当事者会", "悩み相談", "相談会", "ピアサポート", "生きづらさ")),
    ("勉強会・読書会", ("勉強会", "読書会", "輪読", "読書", "学習会", "セミナー")),
    ("ワークショップ・創作", ("ワークショップ", "ハンドメイド", "創作", "ものづくり", "制作", "アート体験")),
    ("健康・心理・自己啓発", ("健康", "心理", "自己啓発", "メンタル", "マインドフルネス", "カウンセリング")),
    ("ビジネス・起業・副業", ("ビジネス", "起業", "副業", "経営者", "フリーランス", "異業種", "集客", "営業交流")),
    ("趣味・文化", ("趣味", "文化", "音楽", "映画", "写真", "ゲーム", "アニメ", "美術", "俳句")),
    ("交流・友達作り", ("交流", "友達", "友活", "カフェ会", "人脈", "つながり", "繋がり", "会話")),
)
CATEGORY_ORDER = (
    "交流・友達作り",
    "勉強会・読書会",
    "AI・IT・技術",
    "語学・国際交流",
    "趣味・文化",
    "ワークショップ・創作",
    "ビジネス・起業・副業",
    "婚活・恋活",
    "当事者会・悩み相談",
    "健康・心理・自己啓発",
    "投資・金融",
    "その他",
)
CATEGORY_COLORS = (
    "#f28c45",
    "#ef7892",
    "#8e6ccf",
    "#4da6a8",
    "#e4b64f",
    "#df6b68",
    "#75a85d",
    "#5b8fc9",
    "#bd7658",
    "#dc8ab2",
    "#7f9670",
    "#9a8e88",
)


def classify_event(event: dict) -> str:
    """イベント情報をキーワードで主カテゴリ1つに分類する。"""
    source = " ".join(
        str(event.get(field) or "")
        for field in ("title", "description", "category", "genre")
    )
    normalized = unicodedata.normalize("NFKC", source).casefold()

    for category, keywords in CATEGORY_RULES:
        matched = False
        for keyword in keywords:
            normalized_keyword = unicodedata.normalize("NFKC", keyword).casefold()
            if normalized_keyword.isascii() and len(normalized_keyword) <= 2:
                matched = re.search(
                    rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])",
                    normalized,
                ) is not None
            else:
                matched = normalized_keyword in normalized
            if matched:
                break
        if matched:
            return category
    return "その他"


def display_value(value) -> str:
    """取得できなかった値を「不明」にし、HTML用に安全な文字列へ変換する。"""
    if value is None:
        return "不明"
    text = str(value).strip()
    return escape(text) if text else "不明"


def display_datetime(value) -> str:
    """ISO形式の日時を、日本語の年月日・曜日・時刻へ整形する。"""
    if value is None or not str(value).strip():
        return "不明"

    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            # ISO形式以外の表示済み文字列は、情報を失わないようそのまま表示します。
            return escape(text)

    weekday = JAPANESE_WEEKDAYS[parsed.weekday()]
    return (
        f"{parsed.year}年{parsed.month}月{parsed.day}日"
        f"（{weekday}）{parsed.hour:02d}:{parsed.minute:02d}"
    )


def display_fee(value) -> str:
    """JPY表記の参加費を、3桁区切りの円表記へ整形する。"""
    if value is None or not str(value).strip():
        return "不明"

    text = str(value).strip()
    if "無料" in text:
        return "無料"

    normalized = text.replace(",", "").strip()
    match = re.fullmatch(
        r"(?:JPY\s*)?([+-]?\d+(?:\.\d+)?)\s*(?:JPY|円)?",
        normalized,
        re.I,
    )
    if match is None:
        return escape(text)

    amount = float(match.group(1))
    if amount == 0:
        return "無料"
    if amount.is_integer():
        return f"{int(amount):,}円"
    return f"{amount:,.2f}".rstrip("0").rstrip(".") + "円"


def build_events_html(
    events: list[dict],
    total_events: Optional[int] = None,
    elapsed_time: str = "不明",
) -> str:
    """カフェイベント一覧から、明るく親しみやすいHTMLを組み立てる。"""
    cafe_event_count = len(events)
    investigated_event_count = total_events if total_events is not None else cafe_event_count
    categorized_events = {category: [] for category in CATEGORY_ORDER}
    for event in events:
        categorized_events[classify_event(event)].append(event)

    category_counts = Counter(classify_event(event) for event in events)
    visible_categories = [
        category for category in CATEGORY_ORDER if category_counts[category]
    ]
    color_by_category = {
        category: CATEGORY_COLORS[index]
        for index, category in enumerate(CATEGORY_ORDER)
    }
    pie_segments = []
    pie_legend = []
    segment_start = 0.0
    for category in visible_categories:
        count = category_counts[category]
        percentage = count / cafe_event_count * 100 if cafe_event_count else 0
        segment_end = segment_start + percentage
        color = color_by_category[category]
        pie_segments.append(
            f"{color} {segment_start:.2f}% {segment_end:.2f}%"
        )
        pie_legend.append(
            '<li><span class="legend-color" '
            f'style="background:{color}"></span>'
            f'<span>{escape(category)}</span><strong>{count}件</strong></li>'
        )
        segment_start = segment_end

    pie_background = ", ".join(pie_segments) if pie_segments else "#eadfd8 0 100%"
    pie_legend_html = "".join(pie_legend)
    html_parts = [
        f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大阪のカフェ利用イベント調査</title>
<style>
:root {{
    --cream: #fff8e9;
    --cream-deep: #ffefd2;
    --orange: #f28c45;
    --orange-dark: #d96b2b;
    --pink: #ef7892;
    --pink-light: #fff0f3;
    --brown: #684638;
    --brown-light: #967064;
    --white: #ffffff;
    --shadow: 0 10px 30px rgba(104, 70, 56, 0.1);
}}

* {{
    box-sizing: border-box;
}}

html {{
    scroll-behavior: smooth;
}}

body {{
    margin: 0;
    color: var(--brown);
    background:
        radial-gradient(circle at 10% 5%, rgba(239, 120, 146, 0.1), transparent 24rem),
        radial-gradient(circle at 90% 18%, rgba(242, 140, 69, 0.12), transparent 22rem),
        var(--cream);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif;
    line-height: 1.7;
}}

a {{
    color: inherit;
}}

.hero {{
    position: relative;
    overflow: hidden;
    padding: 64px 20px 82px;
    color: var(--white);
    text-align: center;
    background: linear-gradient(135deg, #f39a4f 0%, #ef7892 100%);
}}

.hero::before,
.hero::after {{
    position: absolute;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.14);
    content: "";
}}

.hero::before {{
    width: 240px;
    height: 240px;
    top: -110px;
    left: -60px;
}}

.hero::after {{
    width: 180px;
    height: 180px;
    right: -40px;
    bottom: -90px;
}}

.hero-inner {{
    position: relative;
    z-index: 1;
    max-width: 960px;
    margin: 0 auto;
}}

.eyebrow {{
    display: inline-block;
    margin: 0 0 14px;
    padding: 6px 16px;
    border: 1px solid rgba(255, 255, 255, 0.55);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.16);
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.08em;
}}

h1 {{
    margin: 0;
    font-size: clamp(2rem, 5vw, 3.4rem);
    line-height: 1.25;
    letter-spacing: 0.02em;
    text-shadow: 0 3px 12px rgba(104, 70, 56, 0.16);
}}

.subtitle {{
    margin: 16px 0 0;
    font-size: clamp(1rem, 2.5vw, 1.3rem);
    font-weight: 600;
}}

.region-nav {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    justify-content: center;
    margin-top: 24px;
}}

.region-nav a {{
    min-width: 88px;
    padding: 8px 18px;
    border: 1px solid rgba(255, 255, 255, 0.55);
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.2);
    font-weight: 800;
    text-decoration: none;
}}

.region-nav a:hover {{
    background: rgba(255, 255, 255, 0.32);
}}

.page-container {{
    width: min(1040px, calc(100% - 32px));
    margin: -42px auto 72px;
    position: relative;
    z-index: 2;
}}

.region-section {{
    scroll-margin-top: 20px;
}}

.region-section + .region-section {{
    margin-top: 72px;
    padding-top: 54px;
    border-top: 2px dashed rgba(242, 140, 69, 0.32);
}}

.region-title {{
    margin: 0 0 24px;
    color: var(--brown);
    font-size: clamp(1.8rem, 4vw, 2.7rem);
}}

.region-title::before {{
    margin-right: 8px;
    content: "☕";
}}

.stats {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 18px;
    margin-bottom: 28px;
}}

.stat-card {{
    padding: 24px 18px;
    border: 1px solid rgba(242, 140, 69, 0.14);
    border-radius: 20px;
    background: rgba(255, 255, 255, 0.96);
    box-shadow: var(--shadow);
    text-align: center;
}}

.stat-label {{
    display: block;
    color: var(--brown-light);
    font-size: 0.9rem;
    font-weight: 700;
}}

.stat-value {{
    display: block;
    margin-top: 4px;
    color: var(--orange-dark);
    font-size: clamp(1.5rem, 4vw, 2.15rem);
    font-weight: 800;
    line-height: 1.25;
}}

.section-heading {{
    margin: 0 0 20px;
    font-size: clamp(1.45rem, 3vw, 2rem);
}}

.section-heading::after {{
    display: block;
    width: 54px;
    height: 5px;
    margin-top: 8px;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--orange), var(--pink));
    content: "";
}}

.analysis-panel {{
    display: grid;
    grid-template-columns: minmax(240px, 0.8fr) minmax(280px, 1.2fr);
    gap: 32px;
    align-items: center;
    margin-bottom: 48px;
    padding: clamp(24px, 4vw, 36px);
    border-radius: 24px;
    background: var(--white);
    box-shadow: var(--shadow);
}}

.chart-wrap {{
    display: grid;
    place-items: center;
}}

.pie-chart {{
    display: grid;
    width: min(260px, 72vw);
    aspect-ratio: 1;
    place-items: center;
    border-radius: 50%;
    box-shadow: inset 0 0 0 1px rgba(104, 70, 56, 0.06);
}}

.pie-center {{
    display: grid;
    width: 52%;
    aspect-ratio: 1;
    place-content: center;
    border-radius: 50%;
    background: var(--white);
    box-shadow: 0 4px 16px rgba(104, 70, 56, 0.12);
    text-align: center;
}}

.pie-center span {{
    color: var(--brown-light);
    font-size: 0.75rem;
    font-weight: 700;
}}

.pie-center strong {{
    color: var(--orange-dark);
    font-size: 1.65rem;
    line-height: 1.2;
}}

.legend {{
    display: grid;
    gap: 10px;
    margin: 0;
    padding: 0;
    list-style: none;
}}

.legend li {{
    display: grid;
    grid-template-columns: 12px 1fr auto;
    gap: 9px;
    align-items: center;
    font-size: 0.92rem;
}}

.legend-color {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
}}

.legend strong {{
    color: var(--orange-dark);
}}

.category-section {{
    margin-top: 38px;
}}

.category-heading {{
    display: flex;
    gap: 10px;
    align-items: center;
    margin: 0 0 14px;
    font-size: clamp(1.15rem, 2.5vw, 1.45rem);
}}

.category-count {{
    padding: 3px 10px;
    border-radius: 999px;
    color: var(--orange-dark);
    background: var(--cream-deep);
    font-size: 0.78rem;
}}

.event-list {{
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
}}

.event {{
    padding: 18px;
    border: 1px solid rgba(104, 70, 56, 0.08);
    border-radius: 18px;
    background: var(--white);
    box-shadow: var(--shadow);
    transition: transform 0.25s ease, box-shadow 0.25s ease;
}}

.event:hover {{
    transform: translateY(-3px);
    box-shadow: 0 16px 38px rgba(104, 70, 56, 0.15);
}}

.event h2 {{
    margin: 0 0 11px;
    color: var(--brown);
    font-size: clamp(1rem, 2vw, 1.15rem);
    line-height: 1.45;
}}

.info-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 9px;
}}

.info-box {{
    margin: 0;
    padding: 5px 9px;
    border-radius: 999px;
    background: var(--cream);
    font-size: 0.78rem;
    font-weight: 700;
    line-height: 1.5;
}}

.info-box:nth-child(2n) {{
    background: var(--pink-light);
}}

.info-value {{
    font-weight: 700;
    overflow-wrap: anywhere;
}}

.address {{
    margin: 0 2px 10px;
    color: var(--brown-light);
    font-size: 0.76rem;
}}

.description {{
    margin: 0 0 12px;
    padding: 10px 12px;
    border-left: 3px solid var(--pink);
    border-radius: 3px 10px 10px 3px;
    background: #fff9f8;
    font-size: 0.82rem;
}}

.description-preview {{
    display: -webkit-box;
    margin: 0;
    overflow: hidden;
    color: #73584e;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
}}

.description details {{
    margin-top: 5px;
}}

.description summary {{
    width: fit-content;
    color: var(--orange-dark);
    cursor: pointer;
    font-weight: 700;
}}

.description-full {{
    margin: 7px 0 0;
    color: #73584e;
}}

.event-link {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 34px;
    padding: 7px 13px;
    border-radius: 999px;
    color: var(--white);
    background: linear-gradient(135deg, var(--orange), var(--pink));
    box-shadow: 0 6px 16px rgba(239, 120, 146, 0.25);
    font-size: 0.78rem;
    font-weight: 800;
    text-decoration: none;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}}

.event-link:hover {{
    transform: translateY(-2px);
    box-shadow: 0 9px 20px rgba(239, 120, 146, 0.32);
}}

.empty-message {{
    padding: 36px;
    border-radius: 20px;
    background: var(--white);
    box-shadow: var(--shadow);
    text-align: center;
}}

footer {{
    padding: 24px 16px 40px;
    color: var(--brown-light);
    text-align: center;
    font-size: 0.85rem;
}}

@media (max-width: 700px) {{
    .hero {{
        padding: 48px 18px 70px;
    }}

    .stats {{
        grid-template-columns: 1fr;
        gap: 12px;
        margin-bottom: 40px;
    }}

    .analysis-panel {{
        grid-template-columns: 1fr;
        gap: 24px;
    }}

    .event-list {{
        grid-template-columns: 1fr;
    }}

    .stat-card {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 18px 20px;
        text-align: left;
    }}

    .stat-value {{
        margin-top: 0;
        font-size: 1.45rem;
    }}

    .event-link {{
        width: auto;
    }}
}}

@media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
        scroll-behavior: auto !important;
        transition: none !important;
    }}
}}
</style>
</head>
<body>
<header class="hero">
    <div class="hero-inner">
        <p class="eyebrow">OSAKA CAFE EVENTS</p>
        <h1>☕ 大阪のカフェ利用イベント調査</h1>
        <p class="subtitle">大阪のカフェでは、どんなイベントが開かれている？</p>
    </div>
</header>

<main class="page-container">
    <section class="stats" aria-label="調査結果の概要">
        <div class="stat-card">
            <span class="stat-label">☕ カフェイベント</span>
            <strong class="stat-value">{cafe_event_count}件</strong>
        </div>
        <div class="stat-card">
            <span class="stat-label">🔎 調査したイベント</span>
            <strong class="stat-value">{investigated_event_count}件</strong>
        </div>
        <div class="stat-card">
            <span class="stat-label">⏱ 取得時間</span>
            <strong class="stat-value">{escape(elapsed_time)}</strong>
        </div>
    </section>

    <section aria-labelledby="category-chart-heading">
        <h2 class="section-heading" id="category-chart-heading">カフェイベントのカテゴリ割合</h2>
        <div class="analysis-panel">
            <div class="chart-wrap">
                <div class="pie-chart" style="background:conic-gradient({pie_background})"
                     role="img" aria-label="カフェイベントのカテゴリ割合">
                    <div class="pie-center">
                        <span>カフェイベント</span>
                        <strong>{cafe_event_count}件</strong>
                    </div>
                </div>
            </div>
            <ul class="legend">{pie_legend_html}</ul>
        </div>
    </section>

    <section aria-labelledby="event-list-heading">
        <h2 class="section-heading" id="event-list-heading">カテゴリ別イベント一覧</h2>
"""
    ]

    if not events:
        html_parts.append(
            '<p class="empty-message">カフェ会場のイベントは見つかりませんでした。</p>'
        )

    for category in visible_categories:
        category_events = categorized_events[category]
        html_parts.append(
            f"""        <section class="category-section">
            <h3 class="category-heading">
                {escape(category)}
                <span class="category-count">{len(category_events)}件</span>
            </h3>
            <div class="event-list">
"""
        )

        for event in category_events:
            title = display_value(event.get("title"))
            url = display_value(event.get("url"))
            date = display_datetime(event.get("date"))
            venue = display_value(event.get("venue"))
            address = display_value(event.get("address"))
            fee = display_fee(event.get("fee"))
            raw_description = str(event.get("description") or "").strip()
            description = display_value(raw_description)
            description_preview = description
            details_html = ""
            if len(raw_description) > 60:
                description_preview = display_value(f"{raw_description[:60]}…")
                details_html = f"""
            <details>
                <summary>詳しい内容を見る</summary>
                <p class="description-full">{description}</p>
            </details>"""

            html_parts.append(
                f"""
<section class="event">
    <h2>{title}</h2>
    <div class="info-grid">
        <p class="info-box">
            📍 <span class="info-value">{venue}</span>
        </p>
        <p class="info-box">
            📅 <span class="info-value">{date}</span>
        </p>
        <p class="info-box">
            💰 <span class="info-value">{fee}</span>
        </p>
    </div>
    <p class="address">住所：{address}</p>

    <div class="description">
        <p class="description-preview">{description_preview}</p>{details_html}
    </div>

    <a class="event-link" href="{url}" target="_blank" rel="noopener noreferrer">
        イベント詳細を見る →
    </a>
</section>
"""
            )

        html_parts.append("            </div>\n        </section>\n")

    html_parts.append(
        """
    </section>
</main>

<footer>大阪のカフェイベントを、もっと身近に。</footer>
</body>
</html>
"""
    )
    return "".join(html_parts)


def build_kansai_events_html(region_results: list[dict]) -> str:
    """複数地域の分析結果を、同じ形式の1つのHTMLへまとめる。"""
    region_sections = []
    page_css = ""

    for result in region_results:
        region_page = build_events_html(
            result["cafe_events"],
            total_events=result["total_events"],
            elapsed_time=result["elapsed_time"],
        )
        if not page_css:
            style_match = re.search(r"<style>(.*?)</style>", region_page, re.S)
            if style_match is None:
                raise ValueError("地域HTMLからCSSを取得できませんでした。")
            page_css = style_match.group(1)

        main_match = re.search(
            r'<main class="page-container">(.*?)</main>',
            region_page,
            re.S,
        )
        if main_match is None:
            raise ValueError("地域HTMLからメインコンテンツを取得できませんでした。")

        region_content = main_match.group(1)
        for element_id in ("category-chart-heading", "event-list-heading"):
            region_content = region_content.replace(
                f'"{element_id}"',
                f'"{element_id}-{result["region_id"]}"',
            )

        region_sections.append(
            f"""
<section class="region-section" id="{escape(result['region_id'])}">
    <h2 class="region-title">{escape(result['region_name'])}</h2>
    {region_content}
</section>
"""
        )

    navigation = "".join(
        f'<a href="#{escape(result["region_id"])}">{escape(result["region_name"])}</a>'
        for result in region_results
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>関西のカフェ利用イベント調査</title>
<style>{page_css}</style>
</head>
<body>
<header class="hero">
    <div class="hero-inner">
        <p class="eyebrow">KANSAI CAFE EVENTS</p>
        <h1>☕ 関西のカフェ利用イベント調査</h1>
        <p class="subtitle">大阪・京都・兵庫のカフェイベントを地域別に分析</p>
        <nav class="region-nav" aria-label="地域へ移動">{navigation}</nav>
    </div>
</header>
<main class="page-container">
    {''.join(region_sections)}
</main>
<footer>関西のカフェイベントを、もっと身近に。</footer>
</body>
</html>
"""


def write_events_html(
    events: list[dict],
    output_file: Path = OUTPUT_FILE,
    total_events: Optional[int] = None,
    elapsed_time: str = "不明",
) -> None:
    """出力先フォルダを用意し、イベントHTMLを保存する。"""
    output_file.parent.mkdir(exist_ok=True)
    output_file.write_text(
        build_events_html(events, total_events, elapsed_time),
        encoding="utf-8",
    )


def write_kansai_events_html(
    region_results: list[dict],
    output_file: Path = KANSAI_OUTPUT_FILE,
) -> None:
    """3地域の分析結果を関西版HTMLとして保存する。"""
    output_file.parent.mkdir(exist_ok=True)
    output_file.write_text(
        build_kansai_events_html(region_results),
        encoding="utf-8",
    )


def main_osaka() -> int:
    """一覧にある全イベントの詳細からカフェ会場だけをHTMLへ出力する。"""
    started_at = time.monotonic()

    try:
        events = fetch_osaka_events()
    except EventFetchError as exc:
        print(f"取得エラー: {exc}")
        return 1

    # 重複除去後の全イベントを対象にし、各アクセスを1秒以上空けます。
    details = fetch_event_details(events, interval_seconds=1.0)

    cafe_events = filter_cafe_events(details)
    html_elapsed_seconds = int(time.monotonic() - started_at)
    html_elapsed_minutes, html_elapsed_seconds = divmod(html_elapsed_seconds, 60)
    write_events_html(
        cafe_events,
        total_events=len(events),
        elapsed_time=f"{html_elapsed_minutes}分{html_elapsed_seconds}秒",
    )
    elapsed_seconds = int(time.monotonic() - started_at)
    elapsed_minutes, elapsed_seconds = divmod(elapsed_seconds, 60)

    print(f"一覧イベント数：{len(events)}件")
    print(f"詳細ページ取得成功数：{len(details)}件")
    print(f"詳細ページ取得失敗数：{len(details.failures)}件")
    print(f"カフェ判定数：{len(cafe_events)}件")
    print(f"生成HTML：{OUTPUT_FILE}")
    print(f"実行時間：{elapsed_minutes}分{elapsed_seconds}秒")
    print("カフェ会場名一覧：")
    if cafe_events:
        for event in cafe_events:
            print(f"- {event.get('venue') or '不明'}")
    else:
        print("- なし")
    return 0


def collect_prefecture_result(
    region_name: str,
    prefecture: str,
    region_id: str,
) -> dict:
    """1地域の一覧・全詳細を取得し、HTML表示用の集計結果を返す。"""
    started_at = time.monotonic()
    events = fetch_prefecture_events(prefecture)

    # 一覧アクセスと最初の詳細アクセスの間にも1秒以上の間隔を設けます。
    time.sleep(1.0)
    details = fetch_event_details(
        events,
        interval_seconds=1.0,
        progress_prefix=f"{region_name} ",
    )
    cafe_events = filter_cafe_events(details)
    elapsed_seconds = int(time.monotonic() - started_at)
    elapsed_minutes, elapsed_seconds = divmod(elapsed_seconds, 60)

    return {
        "region_name": region_name,
        "prefecture": prefecture,
        "region_id": region_id,
        "total_events": len(events),
        "detail_successes": len(details),
        "detail_failures": len(details.failures),
        "cafe_events": cafe_events,
        "elapsed_time": f"{elapsed_minutes}分{elapsed_seconds}秒",
        "stopped_reason": details.stopped_reason,
    }


def main() -> int:
    """大阪・京都・兵庫を順番に調査し、関西版HTMLを出力する。"""
    all_started_at = time.monotonic()
    region_results = []
    try:
        for index, (region_name, prefecture, region_id) in enumerate(TARGET_REGIONS):
            # 前地域の最終詳細アクセスと、次地域の一覧アクセスを1秒以上空けます。
            if index > 0:
                time.sleep(1.0)
            result = collect_prefecture_result(region_name, prefecture, region_id)
            region_results.append(result)
            if result["stopped_reason"]:
                print(f"取得停止：{result['stopped_reason']}")
                break
    except EventFetchError as exc:
        print(f"取得エラー: {exc}")
        return 1

    write_kansai_events_html(region_results)
    for result in region_results:
        category_counts = Counter(
            classify_event(event) for event in result["cafe_events"]
        )
        print(f"【{result['region_name']}】")
        print(f"一覧イベント数：{result['total_events']}件")
        print(f"詳細取得成功：{result['detail_successes']}件")
        print(f"詳細取得失敗：{result['detail_failures']}件")
        print(f"カフェイベント数：{len(result['cafe_events'])}件")
        print("カテゴリ別件数：")
        for category in CATEGORY_ORDER:
            if category_counts[category]:
                print(f"  {category}：{category_counts[category]}件")
        print(f"実行時間：{result['elapsed_time']}")

    total_elapsed_seconds = int(time.monotonic() - all_started_at)
    total_elapsed_minutes, total_elapsed_seconds = divmod(total_elapsed_seconds, 60)
    print("【全体】")
    print(
        f"調査イベント数：{sum(result['total_events'] for result in region_results)}件"
    )
    print(
        "カフェイベント数："
        f"{sum(len(result['cafe_events']) for result in region_results)}件"
    )
    print(f"総実行時間：{total_elapsed_minutes}分{total_elapsed_seconds}秒")
    print(f"生成HTML：{KANSAI_OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="関西のカフェ利用イベントを調査します。")
    parser.add_argument(
        "--osaka-only",
        action="store_true",
        help="従来の大阪版HTMLだけを生成します。",
    )
    args = parser.parse_args()
    raise SystemExit(main_osaka() if args.osaka_only else main())
