# Locales & Language Packs

This directory contains external language packs for Voicer Studio.

## How to add a new language (e.g. Japanese or Chinese):
1. Create a new JSON file named after the ISO 639-1 language code, e.g. `ja.json`, `zh.json`, `es.json`.
2. Add the `_meta` object with the language display name:
   ```json
   {
     "_meta": {
       "name": "日本語 (Japanese)"
     },
     "menu_file": "ファイル",
     "menu_edit": "編集",
     "menu_view": "表示",
     "menu_help": "ヘルプ",
     "tb_import": "動画をインポート",
     "tb_analyze": "解析",
     "tb_export": "パック書き出し"
   }
   ```
3. Any key omitted will automatically fall back to standard English.
4. Restart Voicer Studio or open Settings to select your language!
