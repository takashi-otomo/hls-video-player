# media/source

このディレクトリに変換元の MP4 ファイルを配置してください。

```bash
cd backend
npm run convert -- ../media/source/my-movie.mp4
```

変換結果は `media/hls/<id>/` と `media/sprites/<id>.{jpg,vtt,json}` に出力されます。
