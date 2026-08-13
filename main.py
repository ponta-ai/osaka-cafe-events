from html import escape
from pathlib import Path
from typing import Optional

from src.fetch_events import (
    EventFetchError,
    fetch_event_details,
    fetch_osaka_events,
    print_detail_results,
)


OUTPUT_FILE = Path("output/osaka_cafe_events.html")


def display_value(value: Optional[str]) -> str:
    """取得できなかった値を「不明」にし、HTML用に安全な文字列へ変換する。"""
    return escape(value.strip()) if isinstance(value, str) and value.strip() else "不明"


def build_events_html(events: list[dict]) -> str:
    """カフェイベント一覧から、既存デザインを保ったHTMLを組み立てる。"""
    html_parts = [
        """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>大阪のカフェ利用イベント調査</title>
<style>
body {
    font-family: sans-serif;
    max-width: 900px;
    margin: 40px auto;
    padding: 0 16px;
    background: #f5f5f5;
}
h1 {
    color: #5b3d2b;
}
.event {
    background: white;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
}
.summary {
    background: #efe3d7;
    padding: 10px;
    border-left: 4px solid #6f4e37;
}
.event-link {
    color: #5b3d2b;
}
</style>
</head>
<body>
<h1>大阪のカフェ利用イベント調査</h1>
"""
    ]

    if not events:
        html_parts.append("<p>カフェ会場のイベントは見つかりませんでした。</p>")

    for event in events:
        title = display_value(event.get("title"))
        url = display_value(event.get("url"))
        date = display_value(event.get("date"))
        venue = display_value(event.get("venue"))
        fee = display_value(event.get("fee"))
        capacity = display_value(event.get("capacity"))
        description = display_value(event.get("description"))

        html_parts.append(
            f"""
<section class="event">
    <h2>{title}</h2>
    <p><strong>開催場所：</strong>{venue}</p>
    <p><strong>開催日時：</strong>{date}</p>
    <p><strong>参加費：</strong>{fee}</p>
    <p><strong>定員：</strong>{capacity}</p>

    <h3>内容</h3>
    <p class="summary">{description}</p>

    <p><strong>イベントURL：</strong>
        <a class="event-link" href="{url}" rel="noopener noreferrer">{url}</a>
    </p>
</section>
"""
        )

    html_parts.append(
        """
</body>
</html>
"""
    )
    return "".join(html_parts)


def write_events_html(events: list[dict], output_file: Path = OUTPUT_FILE) -> None:
    """出力先フォルダを用意し、イベントHTMLを保存する。"""
    output_file.parent.mkdir(exist_ok=True)
    output_file.write_text(build_events_html(events), encoding="utf-8")


def main() -> int:
    """一覧の先頭5イベントだけ、詳細情報とカフェ判定を確認する。"""
    try:
        events = fetch_osaka_events()
        print(f"一覧ページの取得結果: 重複除去後{len(events)}件")

        # 詳細ページは必ず先頭5件まで、各アクセスの間隔は1秒以上にします。
        details = fetch_event_details(events, limit=5, interval_seconds=1.0)
    except EventFetchError as exc:
        print(f"取得エラー: {exc}")
        return 1

    print(f"詳細ページの取得結果: {len(details)}件\n")
    print_detail_results(details)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
