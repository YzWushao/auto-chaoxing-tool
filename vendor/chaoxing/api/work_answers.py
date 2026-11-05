"""Conservative answer matching for chapter work; unknown answers stay blank."""
import re
import unicodedata

from api.answer_check import check_judgement


def matched_answer(question, result, tiku):
    kind = question['type']
    if kind == 'judgement':
        value = check_judgement(result, tiku.true_list, tiku.false_list)
        return 'true' if value == 1 else 'false' if value == 0 else ''
    if result is None or result == '':
        return ''
    if kind not in {'single', 'multiple'}:
        if isinstance(result, list):
            return ''.join(result) if result and all(isinstance(v, str) and v.strip() for v in result) else ''
        return result.strip() if isinstance(result, str) else ''

    def normalized(value):
        return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip().casefold()

    options = []
    for line in question.get('options', '').splitlines():
        match = re.match(r'^\s*([A-Z])(?:\s*[.、:：)）]|\s+)\s*(.+)$', line)
        if match:
            options.append((match[1], normalized(match[2])))
    if not options:
        return ''

    def match_one(value):
        if not isinstance(value, str) or not value.strip():
            return ''
        text = normalized(value)
        # Compare whole option text before interpreting a bare option letter.
        matches = [letter for letter, body in options if body == text]
        if not matches:
            matches = [letter for letter, _ in options if letter == value.strip().upper()]
        if not matches:
            labeled = re.match(r'^\s*([A-Z])[.、:：)）]\s*(.+)$', value)
            if labeled:
                matches = [letter for letter, body in options if letter == labeled[1] and body == normalized(labeled[2])]
        return matches[0] if len(matches) == 1 else ''

    if kind == 'single':
        return match_one(result)
    if isinstance(result, list):
        parts = result
    elif isinstance(result, str):
        whole = match_one(result)
        if whole:
            return whole
        parts = list(result.strip()) if re.fullmatch(r'[A-Z]{2,}', result.strip()) else re.split(r'[\n\r|#;；、]+', result)
        if len(parts) == 1:
            parts = re.split(r'[,，]', result)
    else:
        return ''
    letters = [match_one(part) for part in parts]
    # A partial match must not become a supposedly covered multiple-choice answer.
    return ''.join(sorted(set(letters))) if letters and all(letters) else ''
