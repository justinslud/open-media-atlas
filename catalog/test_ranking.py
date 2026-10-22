from django.test import TestCase
from django.utils import timezone

from .models import Source, SourceRecord, Version, Work, WorkType
from .ranking import metadata_richness, select_timeline_highlights, work_language


class RankingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.film = WorkType.objects.create(code="film", label="Film", medium="screen")
        cls.novel = WorkType.objects.create(code="novel", label="Novel", medium="text")
        cls.source = Source.objects.create(title="Synthetic source", url="https://example.test/source")

    def make_work(self, title, kind=None, **kwargs):
        return Work.objects.create(title=title, work_type=kind or self.film, visibility="public", **kwargs)

    def add_sitelinks(self, work, count):
        SourceRecord.objects.create(
            source=self.source,
            external_key=f"Q{work.pk}",
            matched_work=work,
            payload_hash=f"hash-{work.pk}",
            retrieved_at=timezone.now(),
            raw_payload={"id": f"Q{work.pk}", "sitelinks": {f"x{i}wiki": {} for i in range(count)}},
        )

    def test_richness_uses_metadata_not_publication_state(self):
        sparse = self.make_work("Sparse")
        rich = self.make_work(
            "Rich",
            description="A described work",
            image_url="https://example.test/image.jpg",
            first_publication_year=2000,
            first_publication_date_text="2000-01-02",
            date_evidence={"precision": 11},
        )
        self.add_sitelinks(sparse, 1)
        self.add_sitelinks(rich, 12)
        Version.objects.create(work=rich, label="Original work", kind="original", language="English")
        sparse_result = metadata_richness(sparse)
        rich_result = metadata_richness(rich)
        self.assertGreater(rich_result["score"], sparse_result["score"])
        self.assertIn("12 sitelinks", rich_result["signals"])
        self.assertIn("language: English", rich_result["signals"])
        self.assertIn("full date", rich_result["signals"])
        self.assertEqual(work_language(rich), "English")

    def test_highlights_stay_chronological_and_avoid_duplicate_titles(self):
        events = []
        for index in range(20):
            title = "Romeo and Juliet" if index < 6 else f"Adaptation {index:02}"
            work = self.make_work(title, first_publication_year=1900 + index)
            events.append({
                "work": work,
                "year": work.first_publication_year,
                "prominence": 20 - index,
            })
        selected = select_timeline_highlights(events, limit=8)
        self.assertEqual(len(selected), 8)
        self.assertEqual([event["year"] for event in selected], sorted(event["year"] for event in selected))
        self.assertEqual(
            len([event for event in selected if event["work"].title == "Romeo and Juliet"]),
            1,
        )
