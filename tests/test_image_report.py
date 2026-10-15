"""image_report.py: which pages hide content in images (D30)."""

from agent_apunts.ingestion.extract import extract_all
from agent_apunts.ingestion.image_report import image_report
from agent_apunts.ingestion.manifest import Manifest
from agent_apunts.ingestion.register import register_source
from tests.pdf_factory import make_pdf

USER = "ignasi"


def test_counts_image_only_and_text_with_large_image(settings):
    root = settings.source("testing").root
    make_pdf(root / "disseny_software" / "theory" / "observer.pdf", ["slide", "code", "image"])
    make_pdf(root / "informacio_i_seguretat" / "exams" / "e.pdf", ["a4"])
    with Manifest(settings.paths.manifest) as m:
        register_source(m, USER, settings.source("testing"), settings)
        extract_all(m, USER, settings)
        report = image_report(m, USER, settings)

    ds = report.by_subject["disseny_software"]
    assert (ds.pages, ds.image_only, ds.text_and_large_image) == (3, 1, 1)
    assert report.by_subject["informacio_i_seguretat"].text_and_large_image == 0
    assert report.documents == {"disseny_software/theory/observer.pdf": [2]}
