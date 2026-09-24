from django import forms

from .models import MediaList, MediaListEntry


class MediaListForm(forms.ModelForm):
    class Meta:
        model = MediaList
        fields = ("title", "description", "visibility")
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}

    def __init__(self, *args, can_publish=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_publish = can_publish
        self.fields["visibility"].help_text = "Publishing requires a verified email address."

    def clean_visibility(self):
        visibility = self.cleaned_data["visibility"]
        if visibility == MediaList.Visibility.PUBLIC and not self.can_publish:
            raise forms.ValidationError("Verify your email address before publishing a list.")
        return visibility


class EntryCommentaryForm(forms.ModelForm):
    class Meta:
        model = MediaListEntry
        fields = ("commentary",)
        widgets = {"commentary": forms.Textarea(attrs={"rows": 3})}

from .models import ContributionProposal, RelationshipType, Work, WorkRelationship


class CorrectionProposalForm(forms.Form):
    FIELD_CHOICES = (("title", "Title"), ("description", "Description"),
                     ("first_publication_date_text", "Original publication date"))
    field_name = forms.ChoiceField(choices=FIELD_CHOICES, label="What should change?")
    proposed_value = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 4}), label="Proposed value")
    explanation = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 4}))
    source_url = forms.URLField(max_length=500, help_text="HTTP or HTTPS only. OMA will not fetch this link automatically.")

    def clean_proposed_value(self):
        value = self.cleaned_data["proposed_value"].strip()
        field = self.cleaned_data.get("field_name")
        limits = {"title": 300, "first_publication_date_text": 80, "description": 2000}
        if field == "title" and not value:
            raise forms.ValidationError("A title cannot be empty.")
        if field in limits and len(value) > limits[field]:
            raise forms.ValidationError(f"Keep this value to {limits[field]} characters or fewer.")
        return value

    def clean_source_url(self):
        value = self.cleaned_data["source_url"]
        if not value.lower().startswith(("http://", "https://")):
            raise forms.ValidationError("Use an HTTP or HTTPS source URL.")
        return value


class RelationshipProposalForm(forms.Form):
    related_work = forms.ModelChoiceField(queryset=Work.objects.none(), label="Other published work")
    relationship_type = forms.ModelChoiceField(queryset=RelationshipType.objects.none())
    explanation = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 4}))
    source_url = forms.URLField(max_length=500, help_text="HTTP or HTTPS only. OMA will not fetch this link automatically.")

    def __init__(self, *args, source_work, **kwargs):
        super().__init__(*args, **kwargs)
        self.source_work = source_work
        self.fields["related_work"].queryset = Work.objects.filter(visibility=Work.Visibility.PUBLIC).exclude(pk=source_work.pk)
        self.fields["relationship_type"].queryset = RelationshipType.objects.order_by("label")

    def clean_source_url(self):
        value = self.cleaned_data["source_url"]
        if not value.lower().startswith(("http://", "https://")):
            raise forms.ValidationError("Use an HTTP or HTTPS source URL.")
        return value

    def clean(self):
        data = super().clean()
        target, rel_type = data.get("related_work"), data.get("relationship_type")
        if target and rel_type and (WorkRelationship.objects.filter(from_work=self.source_work, to_work=target,
            relationship_type=rel_type).exists() or ContributionProposal.objects.filter(kind="relationship", status="pending",
            work=self.source_work, related_work=target, relationship_type=rel_type).exists()):
            raise forms.ValidationError("That relationship already exists or is awaiting review.")
        return data
