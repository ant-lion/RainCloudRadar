# Rain Cloud Radar (雨雲レーダー) for Home Assistant

現在地（任意の地点）を中心にした雨雲レーダーの画像を生成し、Home Assistant の
ダッシュボードに表示するカスタム統合です。レーダーのタイル画像とベースマップを
サーバー側で合成するので、カードは普通の `camera` / `image` エンティティを
表示するだけで済みます。

| | |
| --- | --- |
| 提供元 | 気象庁 高解像度降水ナウキャスト（日本）/ RainViewer（世界） |
| エンティティ | `camera.<名前>_レーダー` と `image.<名前>_レーダー` |
| 設定方法 | UI（設定 → デバイスとサービス → 統合を追加） |
| 対応バージョン | Home Assistant 2024.6 以降 |

## 特徴

- **地点中心の画像**：Home Assistant の現在地（または地図で選んだ任意の地点）を
  中心にタイルを切り出して合成します。中心にはマーカーを描画します。
- **2 つの提供元**
  - **気象庁 高解像度降水ナウキャスト** — 日本国内を高解像度で表示します。
    ズーム 4〜10、最大 1 時間先までの予測に対応。
  - **RainViewer** — 世界の広い範囲をカバーします。
- **予測表示**：`予測の時間` を 30 分にすると、30 分後の予測フレームを表示します。
  0 なら常に最新の実況です。
- **ベースマップの選択**：地理院タイル（淡色 / 標準 / 白地図）、OpenStreetMap、
  CARTO ライト / ダーク、なし、任意の XYZ タイル URL。
- **タイルのキャッシュ**：ベースマップは 24 時間、レーダーは 15 分メモリ上に
  保持します。画像はフレームが更新されたときだけ再合成され、`camera` と
  `image` の両エンティティで 1 枚を共有します。

## インストール

### HACS（カスタムリポジトリ）

1. HACS → 統合 → 右上のメニュー → **カスタムリポジトリ**
2. リポジトリに `https://github.com/ant-lion/RainCloudRadar`、種別に **Integration** を指定
3. 「Rain Cloud Radar」をインストールして Home Assistant を再起動

### 手動

`custom_components/raincloudradar` を Home Assistant の設定ディレクトリ配下の
`custom_components/` にコピーして再起動してください。

## 設定

**設定 → デバイスとサービス → 統合を追加 → Rain Cloud Radar**

初期設定で聞かれる項目：

| 項目 | 説明 |
| --- | --- |
| 名前 | エンティティ名とキャプションに使われます |
| レーダー提供元 | 気象庁 / RainViewer |
| 地点 | 地図で指定します。既定値は Home Assistant の現在地 |
| ズームレベル | 大きいほど狭い範囲を詳細に表示します |
| 画像の幅 / 高さ | 出力する PNG のサイズ（ピクセル） |

追加した後、統合の **設定** から次の項目を変更できます。変更すると
エントリが再読み込みされ、すぐに反映されます。

| 項目 | 既定値 | 説明 |
| --- | --- | --- |
| ベースマップ | 提供元に応じて自動 | 地理院タイル / OSM / CARTO / なし / カスタム |
| カスタムベースマップ URL | – | `https://example.com/{z}/{x}/{y}.png` の形式 |
| 雨雲の不透明度 | 0.85 | 0.1〜1.0 |
| 予測の時間 | 0 分 | 0 は実況、5〜60 分で予測フレーム |
| 更新間隔 | 5 分 | フレーム一覧を取得する間隔 |
| 中心にマーカーを表示 | オン | |
| 日時のキャプションを表示 | オン | 画像上部に地点名と時刻を描画します |
| RainViewer のカラースキーム | 4 | 気象庁では使用しません |

### ダッシュボードの例

以下の例は既定の名前 (`Rain Cloud Radar`) のときのエンティティ ID です。
実際の ID は 設定 → デバイスとサービス → Rain Cloud Radar のデバイスページで
確認してください。

```yaml
# 画像エンティティ（フレームが更新されると自動で再読み込みされます）
type: picture-entity
entity: image.rain_cloud_radar_radar
show_state: false
show_name: false
```

```yaml
# カメラエンティティ（スナップショットや通知に添付したい場合）
type: picture-entity
entity: camera.rain_cloud_radar_radar
camera_view: auto
```

雨が降り出したときに画像を通知へ添付する例：

```yaml
automation:
  - alias: 雨雲が近づいたら通知
    triggers:
      - trigger: numeric_state
        entity_id: sensor.home_precipitation
        above: 0
    actions:
      - action: camera.snapshot
        target:
          entity_id: camera.rain_cloud_radar_radar
        data:
          filename: /media/radar.png
      - action: notify.mobile_app
        data:
          message: 雨雲が近づいています
          data:
            image: /media/radar.png
```

### 日本語のキャプションについて

キャプションはサーバー側で画像に描画するため、日本語を表示するには
**日本語グリフを持つフォントが Home Assistant のコンテナ内に必要**です。
統合は Noto Sans CJK / VL Gothic / IPA ゴシックなどを自動的に探し、
見つからない場合は Latin フォントで描画します（日本語部分は豆腐になります）。

その場合は次のいずれかで対応できます。

- `config/fonts/` に任意の日本語フォント（`.ttf` / `.ttc` / `.otf`）を置く
  （統合がこのディレクトリも探索します）
- 名前を英数字にする
- 「日時のキャプションを表示」をオフにする

## エンティティの属性

| 属性 | 内容 |
| --- | --- |
| `frame_time` | 表示中のフレームの時刻（ISO 8601, UTC） |
| `is_forecast` | 予測フレームなら `true` |
| `source` | 提供元の名称 |
| `zoom` | 実際に使用されたズームレベル |

ズームは提供元とベースマップの両方が配信している範囲へ丸められます。たとえば
気象庁のナウキャストはズーム 10 までなので、12 を指定しても 10 で描画されます。

## データソースと利用上の注意

この統合は各提供元のタイルをそのまま取得して合成します。**提供元の利用条件は
利用者自身が確認してください。**

- 気象庁 高解像度降水ナウキャスト — <https://www.jma.go.jp/bosai/nowc/>
- 地理院タイル — <https://maps.gsi.go.jp/development/ichiran.html>
- OpenStreetMap タイル利用ポリシー — <https://operations.osmfoundation.org/policies/tiles/>
- RainViewer API — <https://www.rainviewer.com/api.html>

更新間隔を必要以上に短くしないでください。既定の 5 分でも、レーダー自体の更新は
5 分間隔なのでそれより細かくしても得られる情報は増えません。ベースマップのタイルは
24 時間キャッシュされるため、通常のリクエストはレーダータイルだけです。

## 開発

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

テストはすべてオフラインで動作します（HTTP は `aioclient_mock` で差し替え、
タイルは Pillow で生成した合成画像を使用）。

## ライセンス

MIT License. 詳細は [LICENSE](LICENSE) を参照してください。
