"""
core/text_cleaner.py
===================
Context-aware text processing, hallucination cleaning, and keyword formatting
specifically optimized for Thai dubbing & Thai-English code-switching in game/anime dialogues.
"""

import re
import logging

logger = logging.getLogger(__name__)

# Common game & anime dubbing keywords that often appear in Thai speech
COMMON_ENGLISH_KEYWORDS = {
    # Gaming terms
    "hp": "HP",
    "mp": "MP",
    "exp": "EXP",
    "sp": "SP",
    "skill": "Skill",
    "level": "Level",
    "item": "Item",
    "boss": "Boss",
    "player": "Player",
    "quest": "Quest",
    "combo": "Combo",
    "damage": "Damage",
    "critical": "Critical",
    "mana": "Mana",
    "guild": "Guild",
    "server": "Server",
    "event": "Event",
    "rank": "Rank",
    "class": "Class",
    "party": "Party",
    "master": "Master",
    "lord": "Lord",
    "system": "System",
    "mode": "Mode",
    "status": "Status",
    "option": "Option",
    "stage": "Stage",
    "dungeon": "Dungeon",
    "pvp": "PVP",
    "pve": "PVE",
    "buff": "Buff",
    "debuff": "Debuff",
    "cooldown": "Cooldown",
    "npc": "NPC",
    "ai": "AI",
    "game": "Game",
    "over": "Over",
    "clear": "Clear",
    "start": "Start",
    "stop": "Stop",
    "ready": "Ready",
    "go": "Go",
    "ok": "OK",
    "okay": "OK",
    "no": "No",
    "yes": "Yes",
}

class ThaiTextCleaner:
    @staticmethod
    def remove_repetitive_hallucinations(text: str) -> str:
        """
        Removes repetitive Whisper hallucination loops (e.g. 'ขอบคุณครับ ขอบคุณครับ ขอบคุณครับ').
        """
        if not text:
            return ""

        # Remove repeated words (2+ chars) repeated 3 or more times consecutively
        # e.g. "ขอบคุณครับ ขอบคุณครับ ขอบคุณครับ" -> "ขอบคุณครับ"
        words = text.strip().split()
        if not words:
            return ""

        cleaned_words = []
        i = 0
        n = len(words)

        while i < n:
            word = words[i]
            # Check 1-word repeat
            repeat_count = 1
            while i + repeat_count < n and words[i + repeat_count].lower() == word.lower():
                repeat_count += 1
            
            if repeat_count >= 3:
                # Keep only 1 or 2 occurrences
                cleaned_words.extend([word] * min(2, repeat_count))
                i += repeat_count
                continue

            # Check 2-word phrase repeat
            if i + 3 < n:
                phrase2 = (words[i], words[i+1])
                phrase_repeat = 1
                while i + phrase_repeat * 2 + 1 < n and (words[i + phrase_repeat*2], words[i + phrase_repeat*2 + 1]) == phrase2:
                    phrase_repeat += 1
                if phrase_repeat >= 3:
                    cleaned_words.extend(list(phrase2))
                    i += phrase_repeat * 2
                    continue

            cleaned_words.append(word)
            i += 1

        text = " ".join(cleaned_words)
        # Catch unspaced repeating Thai phrases
        text = re.sub(r'(.{3,15}?)\1{2,}', r'\1', text)
        return text

    @staticmethod
    def normalize_thai_spacing(text: str) -> str:
        """
        Fixes stray spaces within Thai character words while maintaining clean spacing between Thai and English.
        """
        if not text:
            return ""

        # Remove spaces between Thai characters: e.g. "ส ว ั ส ด ี" -> "สวัสดี"
        # Only collapse spaces when a single Thai character is isolated. Preserve spaces of 2+ consecutive Thai chars on each side.
        prev_text = ""
        curr_text = text
        while prev_text != curr_text:
            prev_text = curr_text
            curr_text = re.sub(
                r'(?<![\u0e00-\u0e7f])([\u0e00-\u0e7f])\s+([\u0e00-\u0e7f])|([\u0e00-\u0e7f])\s+([\u0e00-\u0e7f])(?![\u0e00-\u0e7f])',
                lambda m: (m.group(1) or m.group(3)) + (m.group(2) or m.group(4)),
                curr_text
            )

        # Fix punctuation spaces
        curr_text = re.sub(r'\s+([,.!?])', r'\1', curr_text)
        curr_text = re.sub(r'\s+', ' ', curr_text).strip()
        return curr_text

    @staticmethod
    def preserve_keywords(text: str) -> str:
        """
        Ensures English loanwords and terms in Thai speech retain clean capitalization and context formatting.
        """
        if not text:
            return ""

        tokens = text.split()
        res = []
        for token in tokens:
            # Strip punctuation for lookup
            clean_tok = re.sub(r'[^a-zA-Z0-9]', '', token).lower()
            if clean_tok in COMMON_ENGLISH_KEYWORDS:
                replacement = COMMON_ENGLISH_KEYWORDS[clean_tok]
                # Re-attach original non-alphanumeric prefix/suffix
                prefix = re.match(r'^[^a-zA-Z0-9]+', token)
                suffix = re.search(r'[^a-zA-Z0-9]+$', token)
                p_str = prefix.group(0) if prefix else ""
                s_str = suffix.group(0) if suffix else ""
                res.append(f"{p_str}{replacement}{s_str}")
            else:
                res.append(token)

        return " ".join(res)

    @classmethod
    def process_transcript(cls, text: str, language: str = "th", clean_hallucinations: bool = True, format_keywords: bool = True) -> str:
        if not text:
            return ""

        result = text.strip()

        if clean_hallucinations:
            result = cls.remove_repetitive_hallucinations(result)

        if language == "th" or any('\u0e00' <= c <= '\u0e7f' for c in result):
            result = cls.normalize_thai_spacing(result)

        if format_keywords:
            result = cls.preserve_keywords(result)

        return result
