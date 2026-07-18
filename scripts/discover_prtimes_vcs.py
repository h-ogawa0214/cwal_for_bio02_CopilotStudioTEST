"""One-off helper: resolve PR TIMES company_id for a list of VC names.

Parses the server-rendered search page (``action.php?page=searchkey``) and
counts the ``company_id`` links whose poster name matches the query. Prints a
best candidate per VC plus any misses so entries can be added to
``config/companies.yaml``.

Usage: python scripts/discover_prtimes_vcs.py
"""

from __future__ import annotations

import re
import sys
import time
from collections import Counter
from urllib.parse import quote

from bs4 import BeautifulSoup

sys.path.insert(0, ".")
from src.http_client import HttpClient  # noqa: E402
from src.settings import load_settings  # noqa: E402

VC_NAMES = [
    "Angel Bridge",
    "Beyond Next Ventures",
    "D3",
    "DBJキャピタル",
    "Diamond Medino Capital",
    "Eight Roads Ventures Japan",
    "F-Prime Capital Partners",
    "FFGベンチャービジネスパートナーズ",
    "Hike Ventures",
    "JICベンチャー・グロース・インベストメンツ",
    "MedVenture Partners",
    "MP Healthcare Venture Management",
    "Newsight Tech Angels",
    "PF Capital",
    "Plug and Play Japan",
    "SMBCベンチャーキャピタル",
    "Taiho Ventures",
    "いよぎんキャピタル",
    "グローバル・ブレイン",
    "ケイエスピー",
    "産学連携キャピタル",
    "ジャフコ グループ",
    "ちばぎんキャピタル",
    "ニッセイ・キャピタル",
    "日本アジア投資",
    "ファストトラックイニシアティブ",
    "ヘルスケア・イノベーション",
    "北海道ベンチャーキャピタル",
    "みやこキャピタル",
    "メディカルインキュベータジャパン",
    "ユニバーサル マテリアルズ インキュベーター",
    "伊藤忠テクノロジーベンチャーズ",
    "京銀リース・キャピタル",
    "京都大学イノベーションキャピタル",
    "広島ベンチャーキャピタル",
    "三菱UFJキャピタル",
    "新生キャピタルパートナーズ",
    "新生企業投資",
    "神戸大学キャピタル",
    "栖峰投資ワークス",
    "大阪大学ベンチャーキャピタル",
    "大分ベンチャーキャピタル",
    "大鵬イノベーションズ",
    "東京大学エッジキャピタルパートナーズ",
    "東京大学協創プラットフォーム開発",
    "日本ベンチャーキャピタル",
]

_DROP = ["株式会社", "有限責任事業組合", "合同会社", "（株）", "(株)"]


def norm(s: str) -> str:
    s = s or ""
    for d in _DROP:
        s = s.replace(d, "")
    s = s.replace("・", "").replace("／", "").replace("　", "")
    s = s.replace(" ", "").replace("-", "").replace("－", "")
    return s.strip().lower()


def resolve(http: HttpClient, name: str) -> list[tuple[str, str, int]]:
    url = f"https://prtimes.jp/main/action.php?run=html&page=searchkey&search_word={quote(name)}"
    try:
        html = http.get_text(url)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! fetch error: {exc}")
        return []
    soup = BeautifulSoup(html, "lxml")
    q = norm(name)
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    for a in soup.select('a[href*="company_id/"]'):
        m = re.search(r"company_id/(\d+)", a.get("href", ""))
        if not m:
            continue
        cid = m.group(1)
        label = a.get_text(" ", strip=True)
        nl = norm(label)
        if not nl:
            continue
        # Match when the poster name and the query overlap strongly.
        if nl == q or nl.startswith(q) or q.startswith(nl) or q in nl or nl in q:
            counts[cid] += 1
            labels[cid] = label
    return [(cid, labels[cid], c) for cid, c in counts.most_common(3)]


def main() -> None:
    s = load_settings()
    http = HttpClient(s.user_agent, s.request_timeout_seconds)
    found: list[tuple[str, str, str]] = []
    missing: list[str] = []
    for name in VC_NAMES:
        print(f"== {name}")
        cands = resolve(http, name)
        if cands:
            for cid, label, cnt in cands:
                print(f"   id={cid:>8}  x{cnt}  {label}")
            found.append((name, cands[0][0], cands[0][1]))
        else:
            print("   (no PR TIMES match)")
            missing.append(name)
        time.sleep(0.7)
    http.close()

    print("\n===== SUMMARY (best candidate) =====")
    for name, cid, label in found:
        print(f"{cid}\t{name}\t<= {label}")
    print(f"\n===== MISSING ({len(missing)}) =====")
    for name in missing:
        print(name)


if __name__ == "__main__":
    main()
