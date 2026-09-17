# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vsevolod Kiriouchine
"""Terms and concepts, all deterministic and all labelled with how they were found.

- `acronym`: "Extended Kalman Filter (EKF)" or "EKF (Extended Kalman Filter)" with matching initials
- `defined`: "X is defined as …", "X refers to …", "X means …", "X: …" in a glossary table
- `glossary`: two-column tables under a glossary/abbreviations/nomenclature heading
- `macro`: adapter-provided `term` blocks (LaTeX `\\newacronym`, `\\newglossaryentry`)
- `heading`: section titles as topics (generic ones excluded)
- `keyphrase`: corpus TF-IDF over stopword-filtered 1-3 word n-grams, fixed rounding, explicit
  tie-breaks, capped per document (the cap is announced)

Terms are corpus-wide nodes (`term:<normalised>`) that record where they are defined and where
they occur; the link stage turns those into `defines`, `mentions_term` and `shares_term` edges."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from contextmax.docs.base import DocumentTree
from contextmax.docs.structure import Structure
from contextmax.model.ids import doc_id, normalize_term

DEFAULT_CAP = 40
MIN_TF = 2
STOPWORDS = frozenset(
    ["a", "an", "the", "and", "or", "but", "if", "then", "else", "of", "to", "in", "on", "at", "by", "for", "with", "from", "as", "is", "are", "was", "were", "be", "been", "being", "this", "that", "these", "those", "it", "its", "they", "them", "their", "we", "our", "you", "your", "he", "she", "his", "her", "not", "no", "yes", "can", "could", "may", "might", "will", "would", "shall", "should", "do", "does", "did", "done", "have", "has", "had", "having", "into", "over", "under", "than", "more", "most", "less", "least", "very", "also", "only", "such", "which", "who", "whom", "whose", "what", "when", "where", "why", "how", "all", "any", "each", "both", "few", "many", "much", "some", "other", "another", "same", "so", "too", "here", "there", "about", "above", "below", "between", "through", "during", "before", "after", "again", "further", "once", "because", "until", "while", "although", "though", "since", "whether", "either", "neither", "nor", "own", "per", "via", "versus", "i.e", "e.g", "etc", "et", "al", "figure", "fig", "table", "section", "chapter", "page", "pages", "equation", "eq", "eqs", "using", "used", "use", "uses", "based", "given", "shown", "shows", "show", "see", "one", "two", "three", "four", "five", "first", "second", "third", "new", "different", "following", "however", "therefore", "thus", "hence", "within", "without", "upon", "toward", "towards", "among", "along", "across", "still", "already", "always", "often", "never", "sometimes", "usually", "just", "like", "well", "way", "ways", "case", "cases", "example", "examples", "result", "results", "value", "values", "number", "numbers", "respectively", "i.e.", "e.g.", "de", "het", "een", "van", "en", "of"]
)
GENERIC_HEADINGS = frozenset(
    {"introduction", "conclusion", "conclusions", "summary", "abstract", "references", "bibliography",
     "contents", "appendix", "appendices", "acknowledgements", "acknowledgments", "overview", "background",
     "discussion", "results", "method", "methods", "methodology", "preface", "index", "glossary",
     "nomenclature", "notation", "list of figures", "list of tables", "title page", "table of contents",
     "recommendations", "future work", "recommendations and future work", "motivation"}
)
GLOSSARY_HEADINGS = re.compile(r"glossar|abbreviation|acronym|nomenclature|notation|symbols|definitions|terminolog", re.I)
CONNECTORS = {"of", "and", "the", "for", "in", "on", "to", "a", "an", "de", "der", "von"}
WORD_CAP = r"[A-Z][A-Za-z\-]+"
ACRONYM_AFTER = re.compile(
    rf"\b((?:{WORD_CAP}|of|and|the|for|in|on|to)(?:\s+(?:{WORD_CAP}|of|and|the|for|in|on|to)){{0,6}})\s*\(([A-Z][A-Z0-9\-]{{1,9}}s?)\)"
)
ACRONYM_BEFORE = re.compile(rf"\b([A-Z][A-Z0-9\-]{{1,9}})\s*\(((?:{WORD_CAP}|of|and|the|for|in|on|to)(?:\s+(?:{WORD_CAP}|of|and|the|for|in|on|to)){{0,6}})\)")
DEFINITION = re.compile(
    r"(?:^|(?<=[.;:!?]\s)|(?<=\n))(?:The\s+|A\s+|An\s+)?(?P<term>[A-Za-z][\w\-]*(?:\s+[\w\-]+){0,4}?)\s+"
    r"(?:is|are)\s+(?:defined\s+as|called|known\s+as|referred\s+to\s+as)\s+(?P<def>[^.\n]{5,240})",
)
DEFINITION2 = re.compile(
    r"(?:^|(?<=[.;!?]\s)|(?<=\n))(?:The\s+|A\s+|An\s+)?(?P<term>[A-Z][\w\-]*(?:\s+[\w\-]+){0,4}?)\s+"
    r"(?:refers\s+to|denotes|means)\s+(?P<def>[^.\n]{5,240})",
)
QUOTED_DEF = re.compile(r"[“\"']([A-Za-z][\w\- ]{2,40})[”\"']\s+(?:is|means|refers to|denotes)\s+(?P<def>[^.\n]{5,240})")
TOKEN = re.compile(r"[A-Za-z][A-Za-z\-]{1,}")
SENTENCE_BREAK = re.compile(r"[.;:!?()\[\]{}\"“”]|\n")
METHOD_RANK = {"macro": 0, "glossary": 1, "acronym": 2, "defined": 3, "heading": 4, "keyphrase": 5}


@dataclass
class TermHit:
    label: str
    method: str
    doc: str
    section: str | None
    acronym: str | None = None
    expansion: str | None = None
    definition: str | None = None
    score: float = 0.0
    tf: int = 0
    n: int = 1
    line: int = 0
    page: int | None = None


@dataclass
class DocTerms:
    key: str
    hits: list[TermHit] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)  # keyphrase candidate -> tf
    surface: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    notes: list[str] = field(default_factory=list)


def initials(phrase: str) -> str:
    out = []
    for word in phrase.split():
        if word.lower() in CONNECTORS:
            continue
        for part in word.split("-"):
            if part:
                out.append(part[0].upper())
    return "".join(out)


def acronym_matches(acronym: str, phrase: str) -> bool:
    core = acronym.rstrip("s").replace("-", "")
    init = initials(phrase)
    if not core or len(core) < 2:
        return False
    if init == core:
        return True
    # allow connectors counted ("Time of Flight" -> ToF/TOF) and one dropped letter
    with_connectors = "".join(w[0].upper() for w in phrase.split() if w)
    return with_connectors == core or (len(init) >= 3 and core in init)


def trim_phrase(phrase: str, acronym: str) -> str:
    """The shortest trailing phrase whose initials match the acronym (the regex is greedy
    leftwards, so "The Extended Kalman Filter (EKF)" trims to "Extended Kalman Filter")."""
    words = phrase.split()
    for start in range(len(words) - 1, -1, -1):
        candidate = " ".join(words[start:])
        if acronym_matches(acronym, candidate):
            return candidate
    return phrase


# ----- per-document extraction ---------------------------------------------------------------------
def extract(tree: DocumentTree, key: str, structure: Structure, stopwords: frozenset[str], cap: int) -> DocTerms:
    result = DocTerms(key=key)
    own = doc_id(key)
    section_of = structure.block_section
    section_titles = {s.id: s.title for s in structure.sections}
    # In configuration files and spreadsheets a "heading" is a key or a sheet name, not a topic.
    headings_are_topics = tree.adapter not in ("config-v1", "sheet-v1", "image-v1")

    for idx, block in enumerate(tree.blocks):
        section = section_of[idx] if idx < len(section_of) else None
        base = {"doc": own, "section": section, "line": block.line, "page": block.page}
        if block.kind == "term" and block.text:
            result.hits.append(TermHit(label=block.text, method="macro", acronym=block.target or None,
                                       expansion=block.text, definition=block.extra.get("definition"), **base))
            continue
        if block.kind == "heading" and block.text:
            title = block.text.strip().rstrip(":.")
            words = title.split()
            if headings_are_topics and 1 <= len(words) <= 6 and title.lower() not in GENERIC_HEADINGS \
                    and any(len(w) > 2 for w in words) and not re.fullmatch(r"[\d.\s]+", title):
                result.hits.append(TermHit(label=title, method="heading", **base))
            continue
        if block.kind == "table" and block.rows and section in section_titles and GLOSSARY_HEADINGS.search(section_titles[section]):
            for r_index, row in enumerate(block.rows):
                if len(row) < 2 or not row[0].strip() or not row[1].strip():
                    continue
                if r_index == 0 and row[0].strip().lower() in ("term", "symbol", "abbreviation", "acronym", "name", "notation", "word"):
                    continue
                head = row[0].strip()
                acronym = head if re.fullmatch(r"[A-Z][A-Z0-9\-]{1,9}", head) else None
                result.hits.append(TermHit(label=head, method="glossary", acronym=acronym,
                                           expansion=row[1].strip() if acronym else None,
                                           definition=row[1].strip()[:240], **base))
            continue
        if block.kind not in ("paragraph", "list_item", "table", "cell"):
            continue
        text = block.text or ("\n".join("\t".join(r) for r in block.rows or []))
        if not text:
            continue
        for m in ACRONYM_AFTER.finditer(text):
            phrase, acronym = m.group(1), m.group(2)
            if acronym_matches(acronym, phrase):
                result.hits.append(TermHit(label=trim_phrase(phrase, acronym), method="acronym", acronym=acronym,
                                           expansion=trim_phrase(phrase, acronym), **base))
        for m in ACRONYM_BEFORE.finditer(text):
            acronym, phrase = m.group(1), m.group(2)
            if acronym_matches(acronym, phrase):
                result.hits.append(TermHit(label=phrase, method="acronym", acronym=acronym, expansion=phrase, **base))
        for pattern in (DEFINITION, DEFINITION2, QUOTED_DEF):
            for m in pattern.finditer(text):
                term = m.group(1).strip() if pattern is QUOTED_DEF else m.group("term").strip()
                if 2 <= len(term) <= 60 and term.lower() not in stopwords and re.search(r"[A-Za-z]{3,}", term):
                    result.hits.append(TermHit(label=term, method="defined", definition=m.group("def").strip()[:240], **base))
        # keyphrase candidates (tf per document, surface forms remembered); configuration files
        # and spreadsheets hold keys and cells, not prose, so they contribute none
        if not headings_are_topics:
            continue
        for chunk in SENTENCE_BREAK.split(text):
            words = TOKEN.findall(chunk)
            lowered = [w.lower() for w in words]
            for n in (1, 2, 3):
                for i in range(len(words) - n + 1):
                    gram = lowered[i : i + n]
                    if gram[0] in stopwords or gram[-1] in stopwords:
                        continue
                    if any(len(w) < 3 or w[0] == "-" or w.endswith("-") for w in gram):
                        continue
                    if n == 1 and len(gram[0]) < 4:
                        continue
                    if all(w in stopwords for w in gram):
                        continue
                    phrase = " ".join(gram)
                    result.counts[phrase] += 1
                    result.surface[phrase][" ".join(words[i : i + n])] += 1
    return result


# ----- corpus-wide assembly ------------------------------------------------------------------------
def build_terms(
    docs: list[tuple[str, DocumentTree, Structure]],
    section_cites: dict[str, str],
    stopwords_extra: list[str] | None = None,
    cap: int = DEFAULT_CAP,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, list[dict[str, Any]]]]:
    """(term rows, terms per document, top terms per document for catalogs and views)."""
    stopwords = STOPWORDS | {w.lower() for w in (stopwords_extra or [])}
    per_doc = [extract(tree, key, structure, stopwords, cap) for key, tree, structure in docs]
    n_docs = len(per_doc)
    df: Counter = Counter()
    for d in per_doc:
        df.update(set(d.counts))

    # Keyphrases per document: tf >= MIN_TF, scored by tf-idf, capped with the cap announced.
    for d in per_doc:
        scored = []
        for phrase, tf in d.counts.items():
            if tf < MIN_TF:
                continue
            n = phrase.count(" ") + 1
            idf = 1.0 + math.log((n_docs + 1) / (df[phrase] + 1))
            score = round(tf * idf * (1.0 + 0.25 * (n - 1)), 6)
            scored.append((-score, phrase, tf, n, score))
        scored.sort()
        own = doc_id(d.key)
        for _neg, phrase, tf, n, score in scored[:cap]:
            surface = d.surface[phrase].most_common()
            surface.sort(key=lambda kv: (-kv[1], kv[0]))
            d.hits.append(TermHit(label=surface[0][0], method="keyphrase", doc=own, section=None, score=score, tf=tf, n=n))
        if len(scored) > cap:
            d.notes.append(f"terms cap: {cap} of {len(scored)} keyphrase candidates kept (documents.terms_cap)")

    # Merge into corpus-wide term rows.
    merged: dict[str, dict[str, Any]] = {}
    per_doc_count: dict[str, int] = defaultdict(int)
    per_doc_top: dict[str, list[dict[str, Any]]] = defaultdict(list)
    counted: set[tuple[str, str]] = set()
    for d in per_doc:
        own = doc_id(d.key)
        for hit in d.hits:
            norm = normalize_term(hit.label)
            if not norm or len(norm) < 2:
                continue
            row = merged.setdefault(
                norm,
                {
                    "id": f"term:{norm}",
                    "kind": "term",
                    "family": "doc",
                    "name": hit.label,
                    "label_norm": norm,
                    "surface": Counter(),
                    "methods": set(),
                    "acronym": None,
                    "expansion": None,
                    "definition": None,
                    "defined_in": [],
                    "occurrences": {},
                    "documents": set(),
                    "score": 0.0,
                    "tf": 0,
                },
            )
            row["surface"][hit.label] += 1
            row["methods"].add(hit.method)
            row["documents"].add(own)
            row["score"] = max(row["score"], hit.score)
            row["tf"] = max(row["tf"], hit.tf)
            if hit.acronym and not row["acronym"]:
                row["acronym"] = hit.acronym
            if hit.expansion and not row["expansion"]:
                row["expansion"] = hit.expansion
            if hit.definition and not row["definition"]:
                row["definition"] = hit.definition
            defines_here = hit.method in ("acronym", "defined", "glossary", "macro") and hit.section
            if defines_here and hit.section not in row["defined_in"]:
                row["defined_in"].append(hit.section)
            if (norm, own) not in counted:
                counted.add((norm, own))
                per_doc_count[own] += 1
            # acronyms are terms in their own right, pointing at the expansion
            if hit.acronym and hit.method in ("acronym", "glossary", "macro"):
                acro_norm = normalize_term(hit.acronym)
                acro = merged.setdefault(
                    acro_norm,
                    {
                        "id": f"term:{acro_norm}", "kind": "term", "family": "doc", "name": hit.acronym,
                        "label_norm": acro_norm, "surface": Counter(), "methods": set(), "acronym": hit.acronym,
                        "expansion": hit.expansion or hit.label, "definition": hit.definition, "defined_in": [],
                        "occurrences": {}, "documents": set(), "score": 0.0, "tf": 0,
                    },
                )
                acro["surface"][hit.acronym] += 1
                acro["methods"].add(hit.method)
                acro["documents"].add(own)
                if hit.section and hit.section not in acro["defined_in"]:
                    acro["defined_in"].append(hit.section)
                if (acro_norm, own) not in counted:
                    counted.add((acro_norm, own))
                    per_doc_count[own] += 1

    doc_files = {doc_id(key): key for key, _tree, _structure in docs}

    # Occurrences per section for defined terms and acronyms (whole-word, case-insensitive).
    defined_rows = [r for r in merged.values() if r["methods"] & {"acronym", "defined", "glossary", "macro"}]
    if defined_rows:
        for key, _tree, structure in docs:
            own = doc_id(key)
            text = structure.text
            for row in defined_rows:
                forms = {row["name"], row["acronym"] or "", row["expansion"] or ""} - {""}
                pattern = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)) + r")(?![\w-])",
                                     re.I if all(len(f) > 4 for f in forms) else 0)
                for section in structure.sections:
                    body = text[section.text_start : section.text_end]
                    count = len(pattern.findall(body))
                    if count:
                        row["occurrences"][section.id] = count
                        row["documents"].add(own)
                if not structure.sections:
                    count = len(pattern.findall(text))
                    if count:
                        row["occurrences"][own] = count

    rows: list[dict[str, Any]] = []
    for norm, row in sorted(merged.items()):
        surface = sorted(row["surface"].items(), key=lambda kv: (-kv[1], kv[0]))
        methods = sorted(row["methods"], key=lambda m: METHOD_RANK.get(m, 9))
        defined_in = sorted(row["defined_in"])
        occurrences = [{"section": s, "count": c} for s, c in sorted(row["occurrences"].items())]
        documents = sorted(row["documents"])
        # Where to verify this term: its first defining section, else its first occurrence,
        # else the first document it was counted in (keyphrases have no section of their own).
        first_cite = section_cites.get(defined_in[0]) if defined_in else None
        if not first_cite and occurrences:
            first_cite = section_cites.get(occurrences[0]["section"])
        if not first_cite and documents:
            first_cite = doc_files.get(documents[0], documents[0])
        out = {
            "id": row["id"],
            "kind": "term",
            "family": "doc",
            "name": surface[0][0],
            "label_norm": norm,
            "methods": methods,
            "method": methods[0],
            "acronym": row["acronym"],
            "expansion": row["expansion"],
            "definition": row["definition"],
            "defined_in": defined_in,
            "occurrences": occurrences,
            "n_occurrences": sum(o["count"] for o in occurrences),
            "documents": documents,
            "n_documents": len(documents),
            "score": row["score"],
            "tf": row["tf"],
            "variants": [s for s, _ in surface[1:6]],
            "cite": first_cite or "",
        }
        rows.append(out)
        for doc in out["documents"]:
            per_doc_top[doc].append(out)
    for items in per_doc_top.values():
        items.sort(key=lambda r: (METHOD_RANK.get(r["method"], 9), -r["score"], -r["n_occurrences"], r["id"]))
    notes = {doc_id(d.key): d.notes for d in per_doc if d.notes}
    per_doc_top["__notes__"] = [{"doc": k, "notes": v} for k, v in sorted(notes.items())]
    return rows, dict(per_doc_count), dict(per_doc_top)
