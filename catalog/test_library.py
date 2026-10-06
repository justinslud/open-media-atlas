from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from .library import suppress_updates, updates_for
from .models import (CollectionFollow, ContributionProposal, LibraryEvent, MediaList, MediaListEntry,
                     RelationshipType, SavedWork, Source, Work, WorkFollow, WorkRelationship, WorkType)


class LibraryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user('member', password='test-password')
        cls.owner = get_user_model().objects.create_user('owner', password='test-password')
        cls.type = WorkType.objects.create(code='book', label='Book', medium='text')
        cls.work = Work.objects.create(title='First work', work_type=cls.type, visibility='public')
        cls.other = Work.objects.create(title='Second work', work_type=cls.type, visibility='public')
        cls.source = Source.objects.create(title='Test source')
        cls.rel_type = RelationshipType.objects.create(code='adaptation', label='Adaptation of', inverse_label='Adapted as')
        cls.collection = MediaList.objects.create(owner=cls.owner, title='Public collection', visibility='public')

    def setUp(self):
        self.client.force_login(self.member)

    def action(self, action, obj, active=True, client=None, **kwargs):
        return (client or self.client).post(reverse('library-action', args=(action, obj.pk)),
                                          {'active': '1' if active else '0', **kwargs})

    def relationship(self, **kwargs):
        obj = WorkRelationship(from_work=self.work, to_work=self.other, relationship_type=self.rel_type,
                               source=self.source, review_status=kwargs.pop('review_status', 'accepted'), **kwargs)
        obj.save(publish_event=True)
        return obj

    def follow(self):
        self.action('follow-work', self.work)
        self.action('follow-collection', self.collection)

    def library(self, **params):
        return self.client.get(reverse('accounts:account'), params)

    def test_actions_are_idempotent_and_independent(self):
        for action, obj, model in [('save', self.work, SavedWork), ('follow-work', self.work, WorkFollow),
                                   ('follow-collection', self.collection, CollectionFollow)]:
            self.action(action, obj)
            self.action(action, obj)
            self.assertEqual(model.objects.count(), 1)
        self.assertEqual(MediaListEntry.objects.count(), 0)
        self.action('save', self.work, False)
        self.action('save', self.work, False)
        self.assertEqual(SavedWork.objects.count(), 0)
        self.assertEqual(WorkFollow.objects.count(), 1)
        self.action('follow-work', self.work, False)
        self.assertEqual(CollectionFollow.objects.count(), 1)
        self.action('follow-collection', self.collection, False)
        self.assertEqual(CollectionFollow.objects.count(), 0)

    def test_database_duplicate_protection(self):
        for model, field, obj in [(SavedWork, 'work', self.work), (WorkFollow, 'work', self.work),
                                  (CollectionFollow, 'collection', self.collection)]:
            model.objects.create(user=self.member, **{field: obj})
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.create(user=self.member, **{field: obj})

    def test_sign_in_preserves_intent_without_get_mutation(self):
        anonymous = Client()
        response = self.action('save', self.work, client=anonymous, next=self.work.get_absolute_url())
        self.assertIn(reverse('accounts:login'), response.url)
        self.assertEqual(SavedWork.objects.count(), 0)
        anonymous.force_login(self.member)
        self.assertContains(anonymous.get(reverse('library-resume')), 'Save work')
        self.assertEqual(SavedWork.objects.count(), 0)
        self.assertRedirects(anonymous.post(reverse('library-resume')), self.work.get_absolute_url())
        self.assertEqual(SavedWork.objects.count(), 1)

    def test_csrf_and_post_only_and_invalid_state(self):
        url = reverse('library-action', args=('save', self.work.pk))
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'active': 'toggle'}).status_code, 400)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.member)
        self.assertEqual(csrf_client.post(url, {'active': '1'}).status_code, 403)
        response = self.action('save', self.work, next='https://evil.example/')
        self.assertEqual(response.url, reverse('accounts:account'))

    def test_json_and_current_control_state(self):
        response = self.client.post(reverse('library-action', args=('save', self.work.pk)),
                                    {'active': '1'}, HTTP_ACCEPT='application/json')
        self.assertEqual(response.json(), {'active': True})
        self.assertContains(self.client.get(self.work.get_absolute_url()), '>Saved</button>')
        self.assertContains(self.client.get(reverse('discover')), '>Saved</button>')
        self.assertContains(self.client.get(self.work.get_absolute_url()), '>Follow</button>')

    def test_auth_access_and_ownership(self):
        self.collection.visibility = 'private'
        self.collection.save()
        self.assertEqual(self.action('follow-collection', self.collection).status_code, 404)
        self.assertEqual(self.client.get(self.collection.get_absolute_url()).status_code, 404)
        self.work.visibility = 'draft'
        self.work.save()
        self.assertEqual(self.action('save', self.work).status_code, 404)
        self.assertEqual(self.action('follow-work', self.work).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.action('follow-collection', self.collection).status_code, 302)
        self.assertContains(self.client.get(self.collection.get_absolute_url()), 'Following')

    def test_accepted_changes_once_no_noise(self):
        self.follow()
        rel = self.relationship(review_status='unreviewed')
        self.assertEqual(updates_for(self.member).count(), 0)
        rel.review_status = 'accepted'
        rel.save()
        rel.save()
        self.assertEqual(updates_for(self.member).count(), 1)
        self.assertEqual(LibraryEvent.objects.get().kind, 'relationship_added')
        rel.evidence = {'retrieved_at': 'again'}
        rel.save()
        self.assertEqual(LibraryEvent.objects.count(), 1)
        rel.scope_note = 'Only the opening scene'
        rel.save()
        self.assertEqual(LibraryEvent.objects.count(), 2)
        event = LibraryEvent.objects.first()
        self.assertEqual(event.before['scope'], '')
        self.assertEqual(event.after['scope'], 'Only the opening scene')
        rel.review_status = 'disputed'
        rel.save()
        self.assertEqual(LibraryEvent.objects.count(), 3)
        rel.delete()
        self.assertEqual(LibraryEvent.objects.count(), 3)

    def test_deleted_relationship_event_and_rollback(self):
        self.follow()
        rel = self.relationship()
        with self.assertRaises(RuntimeError), transaction.atomic():
            rel.scope_note = 'Rolled back'
            rel.save()
            raise RuntimeError()
        self.assertEqual(LibraryEvent.objects.count(), 1)
        rel.refresh_from_db()
        with self.assertRaises(RuntimeError), transaction.atomic():
            WorkRelationship.objects.filter(pk=rel.pk).delete()
            raise RuntimeError()
        self.assertEqual(LibraryEvent.objects.count(), 1)
        WorkRelationship.objects.filter(pk=rel.pk).delete()
        self.assertEqual(LibraryEvent.objects.first().kind, 'relationship_removed')

    def test_event_failure_rolls_back_mutation(self):
        with patch('catalog.models.LibraryEvent.objects.create', side_effect=RuntimeError('event failed')):
            with self.assertRaises(RuntimeError):
                self.relationship()
        self.assertFalse(WorkRelationship.objects.exists())

    def test_membership_events_and_no_commentary_or_order_noise(self):
        self.follow()
        entry = MediaListEntry.objects.create(media_list=self.collection, work=self.work, position=1)
        entry.commentary = 'Private account identifiers should never appear in updates'
        entry.position = 2
        entry.save()
        self.assertEqual(LibraryEvent.objects.count(), 1)
        self.assertEqual(updates_for(self.member).count(), 1)
        response = self.library(section='updates')
        self.assertContains(response, 'Work added to collection')
        self.assertNotContains(response, entry.commentary)
        entry.delete()
        self.assertEqual(LibraryEvent.objects.count(), 2)
        self.assertEqual(LibraryEvent.objects.first().kind, 'collection_removed')

    def test_private_transition_filters_counts_and_republication(self):
        self.follow()
        MediaListEntry.objects.create(media_list=self.collection, work=self.work, position=1)
        self.assertEqual(updates_for(self.member).count(), 1)
        self.collection.visibility = 'private'
        self.collection.title = 'Secret collection title'
        self.collection.save()
        MediaListEntry.objects.create(media_list=self.collection, work=self.other, position=2)
        self.assertEqual(LibraryEvent.objects.count(), 1)
        self.assertEqual(updates_for(self.member).count(), 0)
        self.assertEqual(self.library(section='following', kind='collections').context['page_obj'].paginator.count, 0)
        self.assertNotContains(self.library(section='updates'), 'Secret collection title')
        # Revoked followers can discard their subscription by known ID, without details.
        self.assertEqual(self.action('follow-collection', self.collection, False).status_code, 302)
        self.collection.visibility = 'public'
        self.collection.save()
        self.action('follow-collection', self.collection)
        self.assertEqual(updates_for(self.member).count(), 0)
        self.collection.entries.get(work=self.other).delete()
        self.assertEqual(updates_for(self.member).count(), 1)

    def test_every_relationship_endpoint_checked_including_before(self):
        self.follow()
        rel = self.relationship()
        third = Work.objects.create(title='Third public work', work_type=self.type, visibility='public')
        rel.to_work = third
        rel.save()
        self.assertEqual(updates_for(self.member).count(), 2)
        self.other.visibility = 'suppressed'
        self.other.save()
        self.assertEqual(updates_for(self.member).count(), 0)

    def test_deleted_endpoint_removes_partial_events(self):
        self.follow()
        self.relationship()
        self.other.delete()
        self.assertEqual(updates_for(self.member).count(), 0)

    def test_start_point_unfollow_and_no_first_import_events(self):
        rel = WorkRelationship.objects.create(from_work=self.work, to_work=self.other,
             relationship_type=self.rel_type, source=self.source, review_status='accepted')
        self.assertFalse(LibraryEvent.objects.exists())
        rel.scope_note = 'An editorial correction'
        rel.save()
        self.follow()
        self.assertEqual(updates_for(self.member).count(), 0)
        rel.scope_note = 'Another correction'
        rel.save()
        self.assertEqual(updates_for(self.member).count(), 1)
        self.action('follow-work', self.work, False)
        self.assertEqual(updates_for(self.member).count(), 0)
        with suppress_updates():
            rel.scope_note = 'Fixture/import correction'
            rel.save()
        self.assertEqual(LibraryEvent.objects.count(), 2)

    def test_pagination_search_filters_and_personal_isolation(self):
        for i in range(25):
            work = Work.objects.create(title=f'Library work {i:02}', work_type=self.type, visibility='public')
            SavedWork.objects.create(user=self.member, work=work)
        SavedWork.objects.create(user=self.owner, work=self.other)
        first = self.library()
        self.assertEqual(len(first.context['page_obj']), 20)
        self.assertEqual(first.context['page_obj'].paginator.count, 25)
        self.assertNotContains(first, 'Second work')
        second = self.library(page=2)
        self.assertEqual(len(second.context['page_obj']), 5)
        filtered = self.library(q='Library work 24', type='book')
        self.assertEqual(filtered.context['page_obj'].paginator.count, 1)
        self.assertEqual(self.library(type='missing').context['page_obj'].paginator.count, 0)
        self.assertEqual(self.client.get(reverse('accounts:account'), {'user': self.owner.pk}).context['page_obj'].paginator.count, 25)
        self.assertNotContains(Client().get(self.work.get_absolute_url()), 'Library work 24')

    def test_follow_and_updates_pagination_and_dedup_both_endpoints(self):
        self.follow()
        self.action('follow-work', self.other)
        rel = self.relationship()
        for i in range(24):
            rel.scope_note = f'Correction {i}'
            rel.save()
        self.assertEqual(updates_for(self.member).count(), 25)
        self.assertEqual(len(self.library(section='updates', page=2).context['page_obj']), 5)
        for i in range(24):
            collection = MediaList.objects.create(owner=self.owner, title=f'Collection {i}', visibility='public')
            CollectionFollow.objects.create(user=self.member, collection=collection)
        self.assertEqual(len(self.library(section='following', kind='collections', page=2).context['page_obj']), 5)

    def test_approved_contribution_and_rejected_proposal(self):
        self.owner.user_permissions.add(Permission.objects.get(codename='review_contributionproposal'))
        def proposal():
            return ContributionProposal.objects.create(kind='relationship', work=self.work, related_work=self.other,
                  relationship_type=self.rel_type, submitted_by=self.member, source_url='https://example.com/source',
                  explanation='Test relationship', work_updated_at=self.work.updated_at,
                  related_work_updated_at=self.other.updated_at)
        self.follow()
        rejected = proposal()
        rejected.review(reviewer=self.owner, approve=False, explanation='Not supported')
        self.assertFalse(LibraryEvent.objects.exists())
        accepted = proposal()
        accepted.review(reviewer=self.owner, approve=True)
        self.assertEqual(updates_for(self.member).count(), 1)
        with self.assertRaises(ValidationError):
            accepted.review(reviewer=self.owner, approve=True)
        self.assertEqual(LibraryEvent.objects.count(), 1)

    def test_deferred_editor_approval_releases_only_on_publication(self):
        self.follow()
        self.other.visibility = 'draft'
        self.other.save()
        rel = self.relationship()
        self.assertTrue(rel.pending_publication)
        self.assertEqual(LibraryEvent.objects.count(), 0)
        self.other.visibility = 'public'
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.other.save()
            raise RuntimeError()
        self.assertEqual(LibraryEvent.objects.count(), 0)
        self.other.save()
        self.other.save()
        self.assertEqual(updates_for(self.member).count(), 1)
        rel.refresh_from_db()
        self.assertFalse(rel.pending_publication)

    def test_import_proposal_approval_and_retry(self):
        from .models import ImportRun, ImportRelationshipProposal
        self.follow()
        run = ImportRun.objects.create(source=self.source)
        proposal = ImportRelationshipProposal.objects.create(run=run, statement_id='test',
            from_work=self.work, to_work=self.other, relationship_type=self.rel_type, source=self.source)
        proposal.approve(self.owner)
        proposal.approve(self.owner)
        self.assertEqual(updates_for(self.member).count(), 1)

    def test_membership_rollback_and_owner_route_checks(self):
        self.follow()
        with self.assertRaises(RuntimeError), transaction.atomic():
            MediaListEntry.objects.create(media_list=self.collection, work=self.work, position=1)
            raise RuntimeError()
        self.assertEqual(LibraryEvent.objects.count(), 0)
        self.assertEqual(self.client.post(reverse('list-add-work', args=(self.collection.pk, self.work.pk))).status_code, 404)
        self.client.force_login(self.owner)
        url = reverse('list-add-work', args=(self.collection.pk, self.work.pk))
        self.client.post(url)
        self.client.post(url)
        self.assertEqual(MediaListEntry.objects.count(), 1)
        self.assertEqual(LibraryEvent.objects.count(), 1)
        entry = MediaListEntry.objects.get()
        with self.assertRaises(RuntimeError), transaction.atomic():
            MediaListEntry.objects.filter(pk=entry.pk).delete()
            raise RuntimeError()
        self.assertEqual(LibraryEvent.objects.count(), 1)

    def test_actions_only_affect_requesting_user(self):
        SavedWork.objects.create(user=self.owner, work=self.work)
        WorkFollow.objects.create(user=self.owner, work=self.work)
        CollectionFollow.objects.create(user=self.owner, collection=self.collection)
        for action, obj in [('save', self.work), ('follow-work', self.work), ('follow-collection', self.collection)]:
            self.action(action, obj, False, user=self.owner.pk)
        self.assertEqual(SavedWork.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(WorkFollow.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(CollectionFollow.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(self.library(section='following').context['page_obj'].paginator.count, 0)
        self.assertEqual(self.library(section='updates').context['page_obj'].paginator.count, 0)

    def test_merge_preserves_personal_actions_without_updates(self):
        from .services import merge_works
        self.owner.is_staff = True
        self.owner.save()
        self.owner.user_permissions.add(Permission.objects.get(codename='merge_work'))
        self.action('save', self.work)
        self.action('follow-work', self.work)
        SavedWork.objects.create(user=self.owner, work=self.work)
        SavedWork.objects.create(user=self.owner, work=self.other)
        merge_works(source=self.work, canonical=self.other, actor=self.owner)
        self.assertTrue(SavedWork.objects.filter(user=self.member, work=self.other).exists())
        self.assertTrue(WorkFollow.objects.filter(user=self.member, work=self.other).exists())
        self.assertEqual(SavedWork.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(LibraryEvent.objects.count(), 0)

    def test_update_fields_does_not_emit_unsaved_membership_change(self):
        self.follow()
        entry = MediaListEntry.objects.create(media_list=self.collection, work=self.work, position=1)
        entry.work = self.other
        entry.commentary = 'Note only'
        entry.save(update_fields=('commentary',))
        self.assertEqual(LibraryEvent.objects.count(), 1)
        entry.refresh_from_db()
        self.assertEqual(entry.work_id, self.work.pk)

    def test_repeated_delete_processing_has_durable_deduplication(self):
        from .library_signals import entry_removed, relationship_removed
        self.follow()
        entry = MediaListEntry.objects.create(media_list=self.collection, work=self.work, position=1)
        entry_removed(MediaListEntry, entry)
        entry_removed(MediaListEntry, entry)
        entry.delete()
        self.assertEqual(LibraryEvent.objects.filter(kind='collection_removed').count(), 1)
        rel = self.relationship()
        relationship_removed(WorkRelationship, rel)
        relationship_removed(WorkRelationship, rel)
        rel.delete()
        self.assertEqual(LibraryEvent.objects.filter(kind='relationship_removed').count(), 1)
