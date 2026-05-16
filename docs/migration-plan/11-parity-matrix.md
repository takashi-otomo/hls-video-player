# 11. 機能対比表 (Python 版 ↔ Docker Web 版)

Phase 4 受入テスト用。旧 Python GUI (`ts-merge --gui`) と新 Docker Web 版 (`make up`) の機能を 1:1 で照合する。

凡例: ✅ 実装済 / 🟡 一部 / ❌ 未 / ➖ 対象外

## 11.1 ライブラリ閲覧 (グリッド再生)

| 機能 | Python (Tkinter Tab2 / Web /play) | Docker Web 版 | 状態 |
|---|---|---|---|
| 変換済み動画の一覧表示 | ✅ | ✅ Library.svelte | ✅ |
| サムネ (poster.png) 表示 | ✅ | ✅ Card.svelte | ✅ |
| ホバーで slideshow (poster→5/30/50/60/80→poster) | ✅ 700ms | ✅ 700ms 同仕様 | ✅ |
| 動画長表示 (⏱ M:SS) | ✅ | ✅ | ✅ |
| ファイル形式表示 (MP4/H.264) | ✅ | ✅ formatLabel | ✅ |
| お気に入りトグル ☆/★ | ✅ | ✅ 楽観的更新 | ✅ |
| お気に入りフィルタ | ✅ | ✅ FilterBar | ✅ |
| 文字列フィルタ (ファイル名/ID) | ✅ | ✅ | ✅ |
| 仮想スクロール (1280件で固まらない) | ✅ viewport place() | ✅ VirtualGrid | ✅ |
| クリックで再生ページへ | ✅ | ✅ | ✅ |
| favorites.json 共有 | ✅ | ✅ 同一ファイル | ✅ |

## 11.2 プレイヤー

| 機能 | Python (player_embed.py) | Docker Web 版 | 状態 |
|---|---|---|---|
| HLS 再生 (Video.js + VHS) | ✅ | ✅ HlsPlayer.svelte | ✅ |
| ポスター画像 | ✅ | ✅ | ✅ |
| シークバーホバーで近傍サムネ preview | ✅ | ✅ 移植 | ✅ |
| 画質セレクタ (Auto/240p/...) | ✅ | ✅ 移植 | ✅ |
| ← 前 / 次 → ナビゲーション | ✅ | ✅ | ✅ |
| ✕ 閉じる | ✅ | ✅ history.back | ✅ |
| ★ お気に入りトグル (プレイヤー内) | ✅ | ✅ | ✅ |
| キーボード ← / → / F / Esc | ✅ | ✅ | ✅ |
| 再生速度 0.5x〜2x | ✅ | ✅ | ✅ |

## 11.3 TS結合管理

| 機能 | Python (Tkinter Tab1) | Docker Web 版 | 状態 |
|---|---|---|---|
| index.md 突合 + ファイル走査 | ✅ | ✅ ts-status.ts | ✅ |
| ステータス分類 (MP4済/TS済/未結合/不完全/未DL) | ✅ | ✅ | ✅ |
| HLS 変換状態カラム | ✅ | ✅ EntryTable | ✅ |
| 状態別フィルタ (チェックボックス) | ✅ | ✅ | ✅ |
| index.md に URL 追加 | ✅ | ✅ AddUrlForm | ✅ |
| index.md から削除 (チェック分一括) | ✅ | ✅ | ✅ |
| TSパート削除 | ✅ | ✅ EntryTable + DELETE /api/ts/ts-parts | ✅ |
| Colab コマンドコピー | ✅ | ➖ Docker 版は変換を内蔵 | ➖ |
| 全選択 / 全解除 | ✅ | ✅ | ✅ |

## 11.4 変換実行

| 機能 | Python (CLI / converter) | Docker Web 版 | 状態 |
|---|---|---|---|
| HLS 変換 (hls-convert) | ✅ CLI | ✅ ConvertPanel → job queue | ✅ |
| TS 結合 (ts-merge) | ✅ CLI | ✅ 同上 | ✅ |
| 変換ログの streaming 表示 | 🟡 GUI 外 (ログファイル) | ✅ WebSocket | ✅ (新規優位) |
| 進捗表示 | 🟡 簡易 | 🟡 簡易 (完了行カウント) | 🟡 |
| 並列ワーカー指定 | ✅ -w N | ✅ workers param | ✅ |
| 中断検出 + 再変換 | ✅ .converting マーカー | ✅ converter が継承 | ✅ |
| hls-index.json 高速判定 | ✅ | ✅ converter が継承 | ✅ |

## 11.5 設定

| 機能 | Python (library_settings) | Docker Web 版 | 状態 |
|---|---|---|---|
| ライブラリパス変更 | ✅ GUI テキスト欄 | ✅ Settings.svelte | ✅ |
| パス検証 (存在/ディレクトリ) | ✅ | ✅ validateLibraryRoot | ✅ |
| 設定の永続化 | ✅ ~/.config/.../settings.json | ✅ /config/settings.json (Docker volume) | ✅ |
| 環境変数フォールバック (LIBRARY_ROOT) | ✅ | ✅ | ✅ |

## 11.6 インフラ / 配布

| 項目 | Python 版 | Docker Web 版 |
|---|---|---|
| ホスト依存 | pipx + Python 3.14 + Tk + ffmpeg + Pillow | Docker Desktop のみ |
| 起動 | `ts-merge --gui <path>` | `make up` → ブラウザ |
| ネイティブ風 | Tk ウィンドウ | PWA インストール |
| 自動起動 | ✗ | docker restart unless-stopped |
| マルチデバイス | ✗ (ローカルのみ) | 🟡 LAN 公開可 (要追加設定) |

## 11.7 受入判定

### 必須 (リリースブロッカー)
- [x] グリッド表示 + サムネ + slideshow
- [x] お気に入り (Python と双方向共有)
- [x] プレイヤー (HLS 再生 + ナビ)
- [x] TS結合管理 (一覧 + index 編集)
- [x] 変換実行 (HLS / TS、ログ streaming)
- [x] 設定 (ライブラリパス)

### 既知の差分 (許容)
- ➖ Colab コマンドコピー → Docker 版は変換を内蔵するため不要
- 🟡 進捗バーの精度 → 完了行カウントの簡易版 (ログで詳細確認可)

### 新版が優位な点
- ✅ 変換ログの WebSocket リアルタイム streaming (Python GUI は外部 tail 必須だった)
- ✅ ブラウザネイティブの 60fps スクロール
- ✅ ホスト無汚染 (Docker のみ)
- ✅ PWA でドック登録
- ✅ Bun サーバの低メモリ (~30MB)

## 11.8 結論

**必須機能はすべて達成**。許容範囲の差分のみ残存 (TSパート個別削除・進捗精度)。
Phase 4 のロールアウト判定: **合格**。並行運用へ移行可能。
