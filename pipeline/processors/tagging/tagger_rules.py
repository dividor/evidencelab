"""Rule-based helpers for tagger classification."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def compile_keyword_rules() -> List[Tuple[str, List[re.Pattern]]]:
    """
    Return ordered rules: (label, [compiled regex patterns]).
    Rules are designed to be conservative to avoid false positives.
    """

    def compile_patterns(phrases: List[str]) -> List[re.Pattern]:
        return [re.compile(phrase, flags=re.IGNORECASE) for phrase in phrases]

    # Patterns use word boundaries where possible.
    # Avoid bare "summary" because it over-matches (e.g., "summary of findings").
    return [
        (
            "front_matter",
            compile_patterns(
                [
                    r"\btable\s+of\s+contents\b",
                    r"^\s*contents\s*$",
                    r"\bsommaire\b",
                    r"\btable\s+des\s+mati[eè]res\b",
                    r"\b[ií]ndice\b",
                    r"\blista\s+de\s+figuras\b",
                    r"\blista\s+de\s+tablas\b",
                    r"\blista\s+de\s+gr[aá]ficos\b",
                    r"\blista\s+de\s+mapas\b",
                    r"\blista\s+de\s+cuadros\b",
                    r"\blist\s+of\s+figures\b",
                    r"\blist\s+of\s+tables\b",
                    r"\bliste\s+des\s+figures\b",
                    r"\bliste\s+des\s+tableaux\b",
                    r"\backnowledg(e)?ments\b",
                    r"\bremerciements\b",
                    r"\bagradecimientos\b",
                    r"\bforeword\b",
                    r"\bavant[-\s]?propos\b",
                    r"\bpreface\b",
                    r"\bdisclaimer\b",
                    r"\bdescargo\s+de\s+responsabilidad\b",
                    r"\bexenci[oó]n\s+de\s+responsabilidad\b",
                    r"\bpersonal\s+clave\b",
                    r"\bcr[eé]ditos?\s+fotogr[aá]ficos\b",
                    r"\bcopyright\b",
                ]
            ),
        ),
        (
            "acronyms",
            compile_patterns(
                [
                    r"\bacronyms\b",
                    r"\babbreviations\b",
                    r"\bglossary\b",
                    r"\bglossaire\b",
                    r"\bglosario\b",
                    r"\bsigles\b",
                    r"\babr[eé]viations\b",
                ]
            ),
        ),
        (
            "executive_summary",
            compile_patterns(
                [
                    # English
                    r"\bexecutive\s+summary\b",
                    r"\bevaluation\s+brief\b",
                    r"^\s*summary\s*$",  # Only exact "Summary"
                    # French
                    r"\br[eé]sum[eé]\s+ex[eé]cutif\b",
                    r"\bnote\s+d['’]?évaluation\b",
                    r"\bnote\s+d['’]?evaluation\b",
                    # Spanish
                    r"\bresumen\s+ejecutivo\b",
                    r"\bnota\s+de\s+evaluaci[oó]n\b",
                    # Russian (исполнительное резюме)
                    r"\bисполнительное\s+резюме\b",
                    # Hindi (कार्यकारी सारांश)
                    r"\bकार्यकारी\s+सारांश\b",
                    # Arabic (ملخص تنفيذي)
                    r"\bملخص\s+تنفيذي\b",
                    # Portuguese
                    r"\bresumo\s+executivo\b",
                    r"\bnota\s+de\s+avalia[çc][aã]o\b",
                    # German
                    r"\bexekutive\s+zusammenfassung\b",
                    # Italian
                    r"\briassunto\s+esecutivo\b",
                ]
            ),
        ),
        (
            "recommendations",
            compile_patterns(
                [
                    # English
                    r"\brecommendations?\b",
                    r"\bmanagement\s+response\b",
                    r"\bway\s+forward\b",
                    r"\bnext\s+steps\b",
                    r"\bconsiderations?\b",
                    r"\baction\s+plan\b",
                    r"\bpriority\s+actions?\b",
                    # French
                    r"\brecommandations?\b",
                    # Spanish
                    r"\brecomendaciones?\b",
                    # Russian (рекомендации)
                    r"\bрекомендации\b",
                    # Hindi (सिफारिशें)
                    r"\bसिफारिशें\b",
                    # Arabic (التوصيات)
                    r"\bالتوصيات\b",
                    # Portuguese
                    r"\brecomenda[çc][oõ]es\b",
                    # German
                    r"\bempfehlungen\b",
                    # Italian
                    r"\braccomandazioni\b",
                ]
            ),
        ),
        (
            "conclusions",
            compile_patterns(
                [
                    # English
                    r"\bconclusions?\b",
                    # Spanish
                    r"\bconclusiones?\b",
                    # French
                    r"\bconclusions?\b",
                    # Russian (выводы, заключение)
                    r"\bвыводы\b",
                    r"\bзаключение\b",
                    # Hindi (निष्कर्ष)
                    r"\bनिष्कर्ष\b",
                    # Arabic (الاستنتاجات, الخلاصة)
                    r"\bالاستنتاجات\b",
                    r"\bالخلاصة\b",
                    # Portuguese
                    r"\bconclus[oõ]es\b",
                    # German
                    r"\bschlussfolgerungen\b",
                    # Italian
                    r"\bconclusioni\b",
                ]
            ),
        ),
        (
            "methodology",
            compile_patterns(
                [
                    # English
                    r"\bmethodology\b",
                    r"\bmethods?\b",
                    r"\bapproach\b",
                    r"\bdata\s+collection\b",
                    r"\blimitations?\b",
                    r"\bevaluation\s+design\b",
                    r"\bresearch\s+design\b",
                    # French
                    r"\bm[eé]thodologie\b",
                    r"\bm[eé]thodes\b",
                    # Spanish
                    r"\bmetodolog[ií]a\b",
                    r"\bm[eé]todos\b",
                    # Russian (методология, методы)
                    r"\bметодология\b",
                    r"\bметоды\b",
                    # Hindi (कार्यप्रणाली, विधि)
                    r"\bकार्यप्रणाली\b",
                    r"\bविधि\b",
                    # Arabic (منهجية, طرق)
                    r"\bمنهجية\b",
                    r"\bطرق\b",
                    # Portuguese
                    r"\bmetodologia\b",
                    r"\bm[eé]todos\b",
                    # German
                    r"\bmethodik\b",
                    r"\bmethoden\b",
                    # Italian
                    r"\bmetodologia\b",
                    r"\bmetodi\b",
                ]
            ),
        ),
        (
            "introduction",
            compile_patterns(
                [
                    # English
                    r"\bintroduction\b",
                    r"\bpurpose\b",
                    r"\bscope\b",
                    r"\bobject\s+of\s+evaluation\b",
                    r"\bobjectives?\s+of\s+the\s+evaluation\b",
                    r"\bevaluation\s+objectives?\b",
                    r"\bevaluation\s+aims?\b",
                    r"\bevaluation\s+questions?\b",
                    r"\bevaluation\s+features\b",
                    r"\bevaluation\s+strategy\b",
                    # French
                    r"\bintroduction\b",
                    r"\bobjectifs?\s+de\s+l['']?évaluation\b",
                    r"\bport[ée]e\b",
                    r"\bobjet\s+de\s+l['']?évaluation\b",
                    # Spanish
                    r"\bintroducci[oó]n\b",
                    r"\bobjetivos?\s+de\s+la\s+evaluaci[oó]n\b",
                    r"\balcance\b",
                    r"\bobjeto\s+de\s+la\s+evaluaci[oó]n\b",
                    # Russian
                    r"\bвведение\b",
                    r"\bцели\s+оценки\b",
                    r"\bзадачи\b",
                    r"\bобъект\s+оценки\b",
                    # Hindi
                    r"\bपरिचय\b",
                    r"\bमूल्यांकन\s+के\s+उद्देश्य\b",
                    r"\bपरिधि\b",
                    # Arabic
                    r"\bمقدمة\b",
                    r"\bأهداف\s+التقييم\b",
                    r"\bنطاق\b",
                    # Portuguese
                    r"\bintrodu[çc][aã]o\b",
                    r"\bobjetivos?\s+da\s+avalia[çc][aã]o\b",
                    r"\bescopo\b",
                    # German
                    r"\beinf[üu]hrung\b",
                    r"\bziele\s+der\s+bewertung\b",
                    r"\bumfang\b",
                    # Italian
                    r"\bintroduzione\b",
                    r"\bobiettivi\s+della\s+valutazione\b",
                    r"\bambito\b",
                ]
            ),
        ),
        (
            "context",
            compile_patterns(
                [
                    # English
                    r"\boverview\b",
                    r"\bbackground\b",
                    r"\bcontext\b",
                    r"\bproject\s+description\b",
                    r"\btheory\s+of\s+change\b",
                    r"\bintervention\b",
                    r"\bstrategic\s+plan\b",
                    # French
                    r"\bcontexte\b",
                    r"\bvue\s+d['\']ensemble\b",
                    r"\bdescription\s+du\s+projet\b",
                    # Spanish
                    r"\bcontexto\b",
                    r"\bdescripci[oó]n\s+del\s+proyecto\b",
                    # Russian
                    r"\bобзор\b",
                    r"\bконтекст\b",
                    r"\bописание\s+проекта\b",
                    # Hindi
                    r"\bपृष्ठभूमि\b",
                    r"\bप्रसंग\b",
                    # Arabic
                    r"\bخلفية\b",
                    r"\bسياق\b",
                    # Portuguese
                    r"\bcontexto\b",
                    r"\bdescri[çc][aã]o\s+do\s+projeto\b",
                    # German
                    r"\bkontext\b",
                    r"\bprojektbeschreibung\b",
                    # Italian
                    r"\bcontesto\b",
                    r"\bdescrizione\s+del\s+progetto\b",
                ]
            ),
        ),
        (
            "appendix",
            compile_patterns(
                [
                    # English
                    r"\bappendix\b",
                    r"\bappendices\b",
                    # French
                    r"\bappendice\b",
                    r"\bappendices\b",
                    # Spanish
                    r"\bap[eé]ndice\b",
                    r"\bap[eé]ndices\b",
                    # Russian (приложение)
                    r"\bприложение\b",
                    r"\bприложения\b",
                    # Hindi (परिशिष्ट)
                    r"\bपरिशिष्ट\b",
                    # Arabic (ملحق)
                    r"\bملحق\b",
                    r"\bملاحق\b",
                    # Portuguese
                    r"\bap[eê]ndice\b",
                    r"\bap[eê]ndices\b",
                    # German
                    r"\banhang\b",
                    r"\banh[aä]nge\b",
                    # Italian
                    r"\bappendice\b",
                    r"\bappendici\b",
                ]
            ),
        ),
        (
            "findings",
            compile_patterns(
                [
                    # English
                    r"\bfindings?\b",
                    r"\bresults?\b",
                    r"\bobservations?\b",
                    r"\banalysis\b",
                    # Spanish
                    r"\bhallazgos\b",
                    # French
                    r"\br[eé]sultats?\b",
                    r"\bconstatations?\b",
                    # Russian (выводы, результаты)
                    r"\bвыводы\b",
                    r"\bрезультаты\b",
                    r"\bнаблюдения\b",
                    # Hindi (निष्कर्ष, परिणाम)
                    r"\bनिष्कर्ष\b",
                    r"\bपरिणाम\b",
                    # Arabic (النتائج, الاستنتاجات)
                    r"\bالنتائج\b",
                    r"\bالاستنتاجات\b",
                    # Portuguese
                    r"\bresultados\b",
                    r"\bobserva[çc][oõ]es\b",
                    # German
                    r"\bergebnisse\b",
                    r"\bbeobachtungen\b",
                    # Italian
                    r"\brisultati\b",
                    r"\bosservazioni\b",
                    # Evaluation criteria often map into findings in these reports:
                    r"\brelevance\b",
                    r"\beffectiveness\b",
                    r"\befficiency\b",
                    r"\bimpact\b",
                    r"\bsustainability\b",
                    r"\bcoherence\b",
                    r"\bpertinence\b",
                    r"\befficacit[eé]\b",
                    r"\befficience\b",
                    r"\bdurabilit[eé]\b",
                    r"\bcoh[eé]rence\b",
                ]
            ),
        ),
        (
            "bibliography",
            compile_patterns(
                [
                    # English
                    r"\bbibliography\b",
                    r"\bworks\s+cited\b",
                    r"\breferences\b",
                    # French
                    r"\bbibliographie\b",
                    r"\br[eé]f[eé]rences\b",
                    # Spanish
                    r"\bbibliograf[ií]a\b",
                    r"\breferencias\b",
                    # Russian (библиография, ссылки)
                    r"\bбиблиография\b",
                    r"\bссылки\b",
                    r"\bлитература\b",
                    # Hindi (ग्रंथ सूची, संदर्भ)
                    r"\bग्रंथ\s+सूची\b",
                    r"\bसंदर्भ\b",
                    # Arabic (المراجع, قائمة المراجع)
                    r"\bالمراجع\b",
                    r"\bقائمة\s+المراجع\b",
                    # Portuguese
                    r"\bbibliografia\b",
                    r"\brefer[eê]ncias\b",
                    # German
                    r"\bbibliographie\b",
                    r"\breferenzen\b",
                    # Italian
                    r"\bbibliografia\b",
                    r"\breferenze\b",
                ]
            ),
        ),
        (
            "annexes",
            compile_patterns(
                [
                    # English
                    r"\bannex(es)?\b",
                    r"\bannexure(s)?\b",
                    r"\bappendix\b",
                    r"\bappendices\b",
                    r"\battachments?\b",
                    r"\battachment\b",
                    # French
                    r"\bannexe(s)?\b",
                    r"\bappendice(s)?\b",
                    r"\btermes\s+de\s+r[eé]f[eé]rence\b",
                    r"\btdr\b",
                    # Spanish
                    r"\banexo(s)?\b",
                    r"\bap[eé]ndice(s)?\b",
                    r"\badjuntos?\b",
                    # Russian (приложение, приложения)
                    r"\bприложение\b",
                    r"\bприложения\b",
                    # Hindi (अनुलग्नक)
                    r"\bअनुलग्नक\b",
                    # Arabic (ملحق)
                    r"\bملحق\b",
                    r"\bملاحق\b",
                    # Portuguese
                    r"\banexo(s)?\b",
                    r"\bap[eê]ndice(s)?\b",
                    r"\btermos\s+de\s+refer[eê]ncia\b",
                    # German
                    r"\banhang\b",
                    r"\banh[aä]nge\b",
                    # Italian
                    r"\ballegato(s)?\b",
                    r"\bappendice(s)?\b",
                    # Chinese
                    r"附录",
                    r"附件",
                    # Common terms
                    r"\bterms\s+of\s+reference\b",
                    r"\btor\b",
                    # Common truncations
                    r"\banex\b",
                    r"\bapend\b",
                ]
            ),
        ),
    ]


def apply_keyword_locking(toc_entries: List[Dict[str, Any]]) -> Dict[int, str]:
    """
    Apply deterministic keyword rules and return locked labels keyed by TOC entry index.
    """
    locked_labels: Dict[int, str] = {}
    keyword_rules = compile_keyword_rules()

    for entry in toc_entries:
        index_value = entry["index"]
        title_text = entry["title"]
        if not title_text:
            continue

        normalized_title = entry["normalized_title"]

        for label, patterns in keyword_rules:
            for pattern in patterns:
                if pattern.search(normalized_title):
                    locked_labels[index_value] = label
                    break
            if index_value in locked_labels:
                break

    return locked_labels


def propagate_hierarchy(
    entries: List[Dict[str, Any]], labels: Dict[int, str]
) -> Dict[int, str]:
    """
    Fill in missing labels using hierarchy.
    - Inherit parent label if current is unknown/"other".
    - Strongly enforce inheritance for key structural sections:
      executive_summary, findings, annexes.
    """
    final_labels = labels.copy()

    # Stack: [(level, label)]
    stack: List[Tuple[int, str]] = []

    # Sections that strictly enforce inheritance to children
    # If a parent is one of these, ALL children MUST be one of these (usually the same one)
    STRONG_CONTAINERS = {
        "executive_summary",
        "findings",
        "methodology",
        "recommendations",
        "introduction",
        "context",
        "annexes",
        "appendix",
        "bibliography",
        "acronyms",
    }

    override_allowed = {
        # Allow explicit cross-over labels only when clearly signaled by the title.
        "findings": {
            "recommendations",
            "conclusions",
            "annexes",
            "appendix",
            "bibliography",
        },
        "recommendations": {"conclusions", "annexes", "appendix", "bibliography"},
        "conclusions": {"recommendations", "annexes", "appendix", "bibliography"},
    }

    keyword_patterns = {label: pats for label, pats in compile_keyword_rules()}

    for entry in entries:
        lvl = entry["level"]
        idx = entry["index"]

        _pop_stack_for_level(stack, lvl)

        parent_label = stack[-1][1] if stack else None
        curr_label = final_labels.get(idx, "other")
        title = entry.get("title", "")

        curr_label = _resolve_hierarchy_label(
            curr_label,
            parent_label,
            title,
            STRONG_CONTAINERS,
            override_allowed,
            keyword_patterns,
        )

        final_labels[idx] = curr_label
        if curr_label:
            stack.append((lvl, curr_label))

    return final_labels


def _pop_stack_for_level(stack: List[Tuple[int, str]], level: int) -> None:
    while stack and stack[-1][0] >= level:
        stack.pop()


def _resolve_hierarchy_label(
    curr_label: str,
    parent_label: Optional[str],
    title: str,
    strong_containers: set[str],
    override_allowed: Dict[str, set[str]],
    keyword_patterns: Dict[str, List[re.Pattern]],
) -> str:
    if parent_label in strong_containers:
        if curr_label == parent_label:
            return parent_label
        if _can_override_label(
            curr_label, parent_label, title, override_allowed, keyword_patterns
        ):
            return curr_label
        return parent_label
    if curr_label == "other" and parent_label:
        return parent_label
    return curr_label


def _can_override_label(
    curr_label: str,
    parent_label: str,
    title: str,
    override_allowed: Dict[str, set[str]],
    keyword_patterns: Dict[str, List[re.Pattern]],
) -> bool:
    override_patterns = keyword_patterns.get(curr_label, [])
    allow_overrides = override_allowed.get(parent_label, set())
    if curr_label not in allow_overrides:
        return False
    if not override_patterns:
        return False
    return _matches_patterns(title, override_patterns)


def apply_sequence_rules(
    entries: List[Dict[str, Any]],
    labels: Dict[int, str],
    document: Optional[Dict[str, Any]] = None,
) -> Dict[int, str]:
    """
    Apply strict sequence rules:
    0. Short Document Rule: If document is 3 or fewer pages, all sections are executive_summary.
    1. Annexes Boundary: Once 'annexes' starts, no 'pre-content' sections allowed after.
    2. Executive Summary Uniqueness: Can only appear as one contiguous block.
    3. Front Matter Boundary: NEVER classify as front_matter if past the first
       third of the document.
    """
    final_labels = labels.copy()
    total_pages = _resolve_total_pages(document)

    short_doc_result = _apply_short_doc_rule(entries, final_labels, total_pages)
    if short_doc_result is not None:
        return short_doc_result

    _apply_front_matter_boundary(entries, final_labels, total_pages)
    _apply_roman_front_matter_restrictions(entries, final_labels, document)
    _apply_roman_boundary_reset(entries, final_labels, total_pages)
    _apply_exec_summary_dominance(entries, final_labels, document)
    _apply_roman_boundary_allowed_labels(entries, final_labels, total_pages)
    _apply_explicit_annex_detection(entries, final_labels)
    _apply_annex_boundary(entries, final_labels)
    _apply_exec_summary_uniqueness(entries, final_labels)
    _apply_front_matter_requires_front_pages(entries, final_labels, total_pages)

    return final_labels


def _apply_front_matter_requires_front_pages(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    total_pages: Optional[int],
) -> None:
    first_third_page = total_pages / 3 if total_pages and total_pages > 0 else None
    keyword_patterns = {label: pats for label, pats in compile_keyword_rules()}
    front_patterns = keyword_patterns.get("front_matter", [])
    for entry in entries:
        idx = entry["index"]
        if final_labels.get(idx) != "front_matter":
            continue
        if entry.get("fm"):
            continue
        entry_page = entry.get("page")
        title = entry.get("title", "")
        if (
            entry_page is not None
            and first_third_page is not None
            and entry_page <= first_third_page
            and _matches_patterns(title, front_patterns)
        ):
            continue
        final_labels[idx] = "other"


def _resolve_total_pages(document: Optional[Dict[str, Any]]) -> Optional[int]:
    if not document:
        return None
    page_count = document.get("page_count")
    if page_count is None:
        page_count = document.get("sys_page_count")
    return page_count


def _apply_short_doc_rule(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    total_pages: Optional[int],
) -> Optional[Dict[int, str]]:
    if total_pages and total_pages > 0 and total_pages <= 3:
        for entry in entries:
            final_labels[entry["index"]] = "executive_summary"
        return final_labels
    return None


def _apply_front_matter_boundary(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    total_pages: Optional[int],
) -> None:
    if not total_pages or total_pages <= 0:
        return
    first_third_page = total_pages / 3
    for entry in entries:
        idx = entry["index"]
        entry_page = entry.get("page")
        if entry_page is not None and entry_page > first_third_page:
            if final_labels.get(idx) == "front_matter":
                final_labels[idx] = "other"

    annex_patterns = _find_annex_patterns()
    if not annex_patterns:
        return
    for entry in entries:
        idx = entry["index"]
        entry_page = entry.get("page")
        if entry_page is None or entry_page > first_third_page:
            continue
        normalized_title = entry.get("normalized_title", "")
        if normalized_title and any(
            pattern.search(normalized_title) for pattern in annex_patterns
        ):
            final_labels[idx] = "front_matter"


def _find_roman_page_range(
    entries: List[Dict[str, Any]], total_pages: Optional[int] = None
) -> Optional[Tuple[int, int]]:
    fm_pages = sorted(
        {
            entry.get("page")
            for entry in entries
            if entry.get("fm") and entry.get("page")
        }
    )
    if fm_pages:
        return fm_pages[0], fm_pages[-1]
    return None


def _roman_to_int(token: str) -> Optional[int]:
    if not token:
        return None
    normalized = token.strip().upper()
    if not normalized:
        return None
    if "M" in normalized:
        return None
    roman_map = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev_value = 0
    for char in reversed(normalized):
        value = roman_map.get(char)
        if value is None:
            return None
        if value < prev_value:
            total -= value
        else:
            total += value
            prev_value = value
    return total


def _apply_roman_front_matter_restrictions(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    document: Optional[Dict[str, Any]],
) -> None:
    roman_range = _find_roman_page_range(entries, _resolve_total_pages(document))
    if not roman_range:
        return
    _, roman_end = roman_range
    logger.info("Applying roman front-matter scope through page %s", roman_end)
    allowed_labels = {"front_matter", "executive_summary", "acronyms"}
    for entry in entries:
        idx = entry["index"]
        entry_page = entry.get("page")
        if entry_page is None or entry_page > roman_end:
            continue
        if final_labels.get(idx) not in allowed_labels:
            final_labels[idx] = "front_matter"


def _apply_exec_summary_dominance(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    document: Optional[Dict[str, Any]],
) -> None:
    roman_range = _find_roman_page_range(entries, _resolve_total_pages(document))
    if not roman_range:
        return
    roman_start, roman_end = roman_range
    patterns = _build_label_patterns()
    start_index = _find_exec_summary_start_index(
        entries, final_labels, roman_start, roman_end, patterns["executive_summary"]
    )
    if start_index is None:
        return
    _apply_exec_summary_block(
        entries,
        final_labels,
        roman_start,
        roman_end,
        start_index,
        patterns,
    )


def _matches_patterns(title: str, patterns: List[re.Pattern]) -> bool:
    if not title:
        return False
    normalized = title.strip().lower()
    return any(pattern.search(normalized) for pattern in patterns)


def _build_label_patterns() -> Dict[str, List[re.Pattern]]:
    return {label: pats for label, pats in compile_keyword_rules()}


def _find_exec_summary_start_index(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    roman_start: int,
    roman_end: int,
    exec_patterns: List[re.Pattern],
) -> Optional[int]:
    for entry in entries:
        entry_page = entry.get("page")
        if entry_page is None or entry_page < roman_start or entry_page > roman_end:
            continue
        idx = entry["index"]
        title = entry.get("title", "")
        if final_labels.get(idx) == "executive_summary" or _matches_patterns(
            title, exec_patterns
        ):
            final_labels[idx] = "executive_summary"
            return idx + 1
    return None


def _apply_exec_summary_block(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    roman_start: int,
    roman_end: int,
    start_index: int,
    patterns: Dict[str, List[re.Pattern]],
) -> None:
    front_patterns = patterns.get("front_matter", [])
    acronym_patterns = patterns.get("acronyms", [])
    for entry in entries:
        idx = entry["index"]
        entry_page = entry.get("page")
        if (
            entry_page is None
            or entry_page < roman_start
            or entry_page > roman_end
            or idx < start_index
        ):
            continue
        title = entry.get("title", "")
        if _matches_patterns(title, front_patterns):
            final_labels[idx] = "front_matter"
        elif _matches_patterns(title, acronym_patterns):
            final_labels[idx] = "acronyms"
        else:
            final_labels[idx] = "executive_summary"


def _update_hierarchy_stack(
    stack: List[Tuple[int, str]], entry: Dict[str, Any]
) -> None:
    level = entry.get("level")
    if not isinstance(level, int):
        return
    while stack and stack[-1][0] >= level:
        stack.pop()


def _record_pre_roman_label(
    stack: List[Tuple[int, str]],
    entry: Dict[str, Any],
    final_labels: Dict[int, str],
) -> None:
    idx = entry["index"]
    current_label = final_labels.get(idx)
    if current_label:
        stack.append((entry.get("level") or 0, current_label))


def _resolve_post_roman_label(
    entry: Dict[str, Any],
    stack: List[Tuple[int, str]],
    final_labels: Dict[int, str],
    patterns: Dict[str, List[re.Pattern]],
    roman_only_labels: set[str],
) -> Optional[str]:
    title = entry.get("title", "")
    parent_label = stack[-1][1] if stack else None
    if parent_label == "executive_summary":
        return "executive_summary"
    if _matches_patterns(title, patterns.get("executive_summary", [])):
        return "executive_summary"
    if _matches_patterns(title, patterns.get("acronyms", [])):
        return "acronyms"
    label = final_labels.get(entry["index"])
    if label in roman_only_labels:
        return "other"
    return None


def _apply_roman_boundary_allowed_labels(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    total_pages: Optional[int],
) -> None:
    roman_range = _find_roman_page_range(entries, total_pages)
    if not roman_range:
        return
    _, roman_end = roman_range
    allowed_labels = {"front_matter", "executive_summary", "acronyms"}
    for entry in entries:
        idx = entry["index"]
        entry_page = entry.get("page")
        if entry_page is None or entry_page > roman_end:
            continue
        if final_labels.get(idx) not in allowed_labels:
            final_labels[idx] = "front_matter"


def _apply_roman_boundary_reset(
    entries: List[Dict[str, Any]],
    final_labels: Dict[int, str],
    total_pages: Optional[int],
) -> None:
    roman_range = _find_roman_page_range(entries, total_pages)
    if not roman_range:
        return
    _, roman_end = roman_range
    roman_only_labels = {"front_matter", "executive_summary", "acronyms"}
    patterns = _build_label_patterns()
    stack: List[Tuple[int, str]] = []

    for entry in entries:
        _update_hierarchy_stack(stack, entry)
        idx = entry["index"]
        entry_page = entry.get("page")
        if entry_page is None or entry_page <= roman_end:
            _record_pre_roman_label(stack, entry, final_labels)
            continue

        label = _resolve_post_roman_label(
            entry, stack, final_labels, patterns, roman_only_labels
        )
        if label:
            final_labels[idx] = label
            stack.append((entry.get("level") or 0, label))
        else:
            existing = final_labels.get(idx)
            if existing:
                stack.append((entry.get("level") or 0, existing))


def _find_annex_patterns() -> Optional[List[re.Pattern]]:
    for label, patterns in compile_keyword_rules():
        if label == "annexes":
            return patterns
    return None


def _apply_explicit_annex_detection(
    entries: List[Dict[str, Any]], final_labels: Dict[int, str]
) -> None:
    annex_pattern = (
        r"\bannex(es)?\b|\bannexe(s)?\b|\banexo(s)?\b|\bannexure(s)?\b|"
        r"\bappendix\b|\bappendices\b|\battachment(s)?\b"
    )
    for entry in entries:
        idx = entry["index"]
        title = entry.get("title", "")
        if re.search(annex_pattern, title, re.IGNORECASE):
            if final_labels.get(idx) != "front_matter":
                final_labels[idx] = "annexes"


def _apply_annex_boundary(
    entries: List[Dict[str, Any]], final_labels: Dict[int, str]
) -> None:
    annex_start_idx = -1
    for entry in entries:
        idx = entry["index"]
        if final_labels.get(idx) == "annexes":
            annex_start_idx = idx
            break
    if annex_start_idx == -1:
        return

    pre_annex_types = {
        "front_matter",
        "executive_summary",
        "acronyms",
        "introduction",
        "context",
        "methodology",
        "findings",
        "recommendations",
        "conclusions",
    }
    for entry in entries:
        idx = entry["index"]
        if idx > annex_start_idx and final_labels.get(idx) in pre_annex_types:
            final_labels[idx] = "annexes"


def _apply_exec_summary_uniqueness(
    entries: List[Dict[str, Any]], final_labels: Dict[int, str]
) -> None:
    has_seen_exec = False
    in_exec_block = False
    for entry in entries:
        idx = entry["index"]
        lbl = final_labels.get(idx)
        if lbl == "executive_summary":
            if has_seen_exec and not in_exec_block:
                final_labels[idx] = "findings"
            else:
                has_seen_exec = True
                in_exec_block = True
        else:
            if in_exec_block:
                in_exec_block = False
