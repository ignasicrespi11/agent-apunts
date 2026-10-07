"""How much content hides in images? (D14, D30: measure before building OCR or vision.)

Reads the extract stage's JSON only. Three kinds of pages:
- text: what we read is all there is (as far as we can tell),
- image_only: little or no text ("mostly image"): nothing of it reaches the index today,
- text_and_large_image: has text, but images cover a large share of the page (code screenshots,
  UML diagrams). The silent case: the page is indexed, but part of its content is missing.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from agent_apunts.config import Settings
from agent_apunts.ingestion.extract import processed_path, read_json
from agent_apunts.ingestion.manifest import Manifest


@dataclass
class SubjectImages:
    pages: int = 0
    image_only: int = 0
    text_and_large_image: int = 0


@dataclass
class ImageReport:
    by_subject: dict[str, SubjectImages] = field(default_factory=lambda: defaultdict(SubjectImages))
    # rel_path -> page numbers with text + a large image, for the documents to look at first
    documents: dict[str, list[int]] = field(default_factory=dict)
    not_extracted: int = 0


def image_report(manifest: Manifest, user_id: str, settings: Settings) -> ImageReport:
    threshold = settings.extraction.large_image_min_coverage
    report = ImageReport()
    for record in manifest.documents(user_id):
        path = processed_path(settings, user_id, record.doc_id)
        if not path.is_file():
            report.not_extracted += 1
            continue
        doc = read_json(path)
        subject = doc.metadata.subject if doc.metadata else "(unorganised)"
        stats = report.by_subject[subject]
        hidden = []
        for page in doc.pages:
            stats.pages += 1
            if page.mostly_image:
                stats.image_only += 1
            elif page.image_coverage >= threshold:
                stats.text_and_large_image += 1
                hidden.append(page.number)
        if hidden:
            report.documents[record.rel_path] = hidden
    return report
