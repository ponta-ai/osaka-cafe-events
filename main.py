import time
from html import escape
from pathlib import Path

from src.fetch_events import (
    EventFetchError,
    fetch_event_details,
    fetch_osaka_events,
    filter_cafe_events,
)


OUTPUT_FILE = Path("output/osaka_cafe_events.html")


def display_value(value) -> str:
    """取得できなかった値を「不明」にし、HTML用に安全な文字列へ変換する。"""
    if value is None:
        return "不明"
    text = str(value).strip()
    return escape(text) if text else "不明"


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
        address = display_value(event.get("address"))
        fee = display_value(event.get("fee"))
        capacity = display_value(event.get("capacity"))
        description = display_value(event.get("description"))

        html_parts.append(
            f"""
<section class="event">
    <h2>{title}</h2>
    <p><strong>会場名：</strong>{venue}</p>
    <p><strong>会場住所：</strong>{address}</p>
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
    write_events_html(cafe_events)
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


if __name__ == "__main__":
    raise SystemExit(main())
