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
