import unicodedata


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
