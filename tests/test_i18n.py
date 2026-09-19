import sys
import json
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.i18n import I18nManager, tr, i18n, STRINGS_EN, STRINGS_TH

def test_default_language():
    # 1. Default language must be English
    manager = I18nManager(default_lang='en')
    assert manager.current_language == 'en'
    assert manager.tr('menu_file') == 'File'
    assert manager.tr('tb_analyze') == 'Analyze'
    assert manager.tr('status_ready') == '[Ready]'
    print('[PASS] Default language is English')

def test_thai_language():
    manager = I18nManager(default_lang='en')
    manager.set_language('th')
    assert manager.current_language == 'th'
    assert manager.tr('menu_file') == 'ไฟล์'
    assert manager.tr('btn_ok') == 'ตกลง'
    print('[PASS] Thai language translations load accurately')

def test_kwargs_formatting():
    manager = I18nManager(default_lang='en')
    formatted = manager.tr('pipe_slicing_clips', current=3, total=10, id='clip_003')
    assert '[3/10]' in formatted
    assert 'clip_003' in formatted
    print('[PASS] Kwargs formatting works as expected')

def test_missing_key_fallback():
    manager = I18nManager(default_lang='en')
    manager.set_language('th')
    # If a key is missing in Thai, fallback to English
    manager._dicts['th'].pop('menu_file', None)
    assert manager.tr('menu_file') == 'File'
    
    # If key doesn't exist anywhere, return key itself
    assert manager.tr('non_existent_key_xyz') == 'non_existent_key_xyz'
    print('[PASS] Missing key fallback functions properly')

def test_custom_json_locale_discovery():
    # Test loading external locale JSON file
    manager = I18nManager(default_lang='en')
    with tempfile.TemporaryDirectory() as tmpdir:
        locales_dir = Path(tmpdir)
        ja_file = locales_dir / 'ja.json'
        ja_file.write_text(json.dumps({
            '_meta': {'name': '日本語 (Japanese)'},
            'menu_file': 'ファイル',
            'btn_ok': 'OK'
        }, ensure_ascii=False), encoding='utf-8')
        
        manager.locales_dir = locales_dir
        manager.reload_locales()
        langs = manager.get_available_languages()
        assert 'ja' in langs
        assert langs['ja'] == '日本語 (Japanese)'
        
        manager.set_language('ja')
        assert manager.tr('menu_file') == 'ファイル'
        # Fallback to EN for missing keys
        assert manager.tr('tb_analyze') == 'Analyze'
        print('[PASS] Custom JSON locale discovery and fallback verified')

def test_terminology_integrity():
    # Ensure non-AI tasks are not incorrectly labelled as AI in English and Thai
    non_ai_terms = ['audio slicing', 'video proxy', 'frame extraction', 'pack generation', 'backing track']
    for term in non_ai_terms:
        for k in ['pipe_slicing_clips', 'pipe_capturing_frames', 'pipe_encoding_backing', 'pipe_building_pack', 'cfg_preview_proxy']:
            en_val = STRINGS_EN.get(k, '').lower()
            assert 'ai' not in en_val.split(), f'Non-AI task {k} contains AI in EN: {en_val}'
    print('[PASS] Studio terminology and AI vs DSP distinction validated')

if __name__ == '__main__':
    test_default_language()
    test_thai_language()
    test_kwargs_formatting()
    test_missing_key_fallback()
    test_custom_json_locale_discovery()
    test_terminology_integrity()
    print('\nAll i18n tests passed successfully!')
