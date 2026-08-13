from pathlib import Path

events = [
    {
        "title": "朝のゆる交流会",
        "venue": "ドトールコーヒーショップ 大阪駅前店",
        "date": "2026年8月3日 10:00",
        "fee": "500円",
        "capacity": "8名",
        "category": "交流・友達作り",
        "summary": "少人数で気軽に会話する友達作り交流会",
        "description": (
            "少人数でコーヒーを飲みながら、最近興味を持っていることや"
            "休日の過ごし方について自由に話す交流会です。"
        ),
    },
    {
        "title": "朝の読書シェア会",
        "venue": "スターバックス コーヒー 梅田中央店",
        "date": "2026年8月6日 8:00",
        "fee": "無料",
        "capacity": "6名",
        "category": "勉強会・読書会",
        "summary": "最近読んだ本の内容や感想を共有する少人数読書会",
        "description": (
            "各自が最近読んだ本を持ち寄り、印象に残った部分や"
            "学んだことを参加者同士で共有します。"
        ),
    },
    {
        "title": "初心者向け生成AIミニ勉強会",
        "venue": "梅田駅近くのカフェ",
        "date": "2026年8月12日 19:00",
        "fee": "1,000円",
        "capacity": "5名",
        "category": "AI・IT・技術",
        "summary": "生成AIの基本操作と活用例を学ぶ初心者向け勉強会",
        "description": (
            "ChatGPTなどの生成AIを初めて使う人を対象に、"
            "基本操作や簡単なプロンプト作成を体験します。"
        ),
    },
]

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
</style>
</head>
<body>
<h1>大阪のカフェ利用イベント調査</h1>
"""
]

for event in events:
    html_parts.append(
        f"""
<section class="event">
    <h2>{event["title"]}</h2>
    <p><strong>開催場所：</strong>{event["venue"]}</p>
    <p><strong>開催日時：</strong>{event["date"]}</p>
    <p><strong>参加費：</strong>{event["fee"]}</p>
    <p><strong>定員：</strong>{event["capacity"]}</p>

    <h3>内容</h3>
    <p>{event["description"]}</p>

    <h3>内容の短い要約</h3>
    <p class="summary">{event["summary"]}</p>

    <p><strong>カテゴリ：</strong>{event["category"]}</p>
</section>
"""
    )

html_parts.append(
    """
</body>
</html>
"""
)

output_dir = Path("output")
output_dir.mkdir(exist_ok=True)

output_file = output_dir / "osaka_cafe_events.html"
output_file.write_text("".join(html_parts), encoding="utf-8")

print(f"HTMLを生成しました: {output_file}")