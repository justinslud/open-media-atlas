"""Seed the expanded OMA relationship vocabulary.

This is a data command, not a schema migration. It is idempotent and only
updates labels/inverse labels for known codes; it never deletes a code.
"""
from django.core.management.base import BaseCommand

from catalog.models import RelationshipType


VOCABULARY = (
    ("based-on", "Based on", "Works based on this", "derivation"),
    ("adapted-from", "Adapted from", "Adaptations", "derivation"),
    ("remake-of", "Remake of", "Remade as", "derivation"),
    ("reboot-of", "Reboot of", "Rebooted as", "derivation"),
    ("reimagining-of", "Reimagining of", "Reimagined as", "derivation"),
    ("retelling-of", "Retelling of", "Retold as", "derivation"),
    ("sequel-to", "Sequel to", "Sequels", "sequence"),
    ("prequel-to", "Prequel to", "Prequels", "sequence"),
    ("spin-off-of", "Spin-off of", "Spin-offs", "derivation"),
    ("continuation-of", "Continuation of", "Continuations", "sequence"),
    ("side-story-of", "Side story of", "Side stories", "reference"),
    ("alternative-version-of", "Alternative version of", "Alternative versions", "derivation"),
    ("parody-of", "Parody of", "Parodies", "derivation"),
    ("pastiche-of", "Pastiche of", "Pastiches", "derivation"),
    ("homage-to", "Homage to", "Homages", "reference"),
    ("fan-work-of", "Fan work of", "Fan works", "reference"),
    ("translation-of", "Translation of", "Translations", "derivation"),
    ("abridgment-of", "Abridgment of", "Abridgments", "derivation"),
    ("modernization-of", "Modernization of", "Modernizations", "derivation"),
    ("edition-of", "Edition of", "Editions", "derivation"),
    ("part-of-series", "Part of series", "Series members", "sequence"),
    ("shares-universe-with", "Shares universe with", "Shared-universe works", "reference"),
    ("crossover-with", "Crossover with", "Crossovers", "reference"),
    ("uses-same-character", "Uses same character", "Works using this character", "reference"),
    ("uses-same-historical-event", "Uses same historical event", "Works using this event", "reference"),
    ("follows", "Follows", "Followed by", "sequence"),
    ("followed-by", "Followed by", "Follows", "sequence"),
    ("inspired-by", "Inspired by", "Inspired works", "reference"),
    ("influenced-by", "Influenced by", "Influenced works", "reference"),
    ("derivative-work", "Derivative work", "Derivative of", "derivation"),
    ("remix-of", "Remix of", "Remixes", "derivation"),
    ("cover-of", "Cover of", "Covers", "derivation"),
    ("sample-of", "Sample of", "Samples", "derivation"),
    ("interpolation-of", "Interpolation of", "Interpolations", "derivation"),
    ("mashup-of", "Mashup of", "Mashups", "derivation"),
    ("medley-of", "Medley of", "Medleys", "derivation"),
    ("edit-of", "Edit of", "Edits", "derivation"),
    ("instrumental-of", "Instrumental of", "Instrumentals", "derivation"),
    ("dub-of", "Dub of", "Dubs", "derivation"),
    ("localization-of", "Localization of", "Localizations", "derivation"),
    ("fansub-of", "Fansub of", "Fansubs", "reference"),
    ("scanlation-of", "Scanlation of", "Scanlations", "reference"),
    ("fanvid-of", "Fanvid of", "Fanvids", "reference"),
    ("podfic-of", "Podfic of", "Podfics", "reference"),
    ("recursive-fanwork-of", "Recursive fanwork of", "Recursive fanworks", "reference"),
    ("same-trope-as", "Same trope as", "Same-trope works", "reference"),
    ("same-theme-as", "Same theme as", "Same-theme works", "reference"),
    ("similar-premise", "Similar premise", "Similar-premise works", "reference"),
    ("thematic-resonance", "Thematic resonance", "Thematically related works", "reference"),
    ("comparable-to", "Comparable to", "Comparable works", "reference"),
    ("related-to", "Related to", "Related works", "reference"),
    ("alleged-adaptation-of", "Alleged adaptation of", "Alleged adaptations", "reference"),
    ("disputed-remake-of", "Disputed remake of", "Disputed remakes", "reference"),
    ("unofficial-sequel-to", "Unofficial sequel to", "Unofficial sequels", "reference"),
    ("unauthorized-continuation-of", "Unauthorized continuation of", "Unauthorized continuations", "reference"),
    ("fan-theory-link", "Fan-theory link", "Fan-theory links", "reference"),
)


class Command(BaseCommand):
    help = "Idempotently seed the expanded OMA relationship vocabulary."

    def handle(self, *args, **options):
        for code, label, inverse, category in VOCABULARY:
            RelationshipType.objects.update_or_create(
                code=code,
                defaults={"label": label, "inverse_label": inverse, "category": category},
            )
        self.stdout.write(self.style.SUCCESS(f"seeded {len(VOCABULARY)} relationship types"))