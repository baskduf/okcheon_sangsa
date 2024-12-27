
# Create your models here.
# myapp/models.py
# myapp/models.py
from django.db import models

class UploadedZipFile(models.Model):
    zip_file = models.FileField(upload_to='uploads/zips/')
    upload_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.zip_file.name
