# myapp/forms.py
from django import forms
from .models import UploadedZipFile

class UploadZipFileForm(forms.ModelForm):
    class Meta:
        model = UploadedZipFile
        fields = ['zip_file']
