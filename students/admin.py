from django import forms
from django.contrib import admin

from .models import Student
from .utils import normalize_national_id


class StudentAdminForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = "__all__"

    def clean_national_id(self):
        raw = self.cleaned_data.get("national_id", "")
        if not raw:
            raise forms.ValidationError("National ID is required.")
        normalized = normalize_national_id(raw)
        if not normalized or len(normalized) != 14:
            raise forms.ValidationError("National ID must be exactly 14 digits.")
        return normalized

    def clean_academic_year(self):
        raw = self.data.get("academic_year", "")
        if isinstance(raw, str) and "." in raw:
            raise forms.ValidationError("Academic year must be a whole number.")
        value = self.cleaned_data.get("academic_year")
        if value is not None and not isinstance(value, int):
            raise forms.ValidationError("Academic year must be a whole number.")
        return value

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    form = StudentAdminForm
    list_display = ['student_id', 'name', 'gpa', 'status', 'faculty']
    list_filter = ['status', 'faculty']
    search_fields = ['student_id', 'name']
    readonly_fields = ['created_at', 'updated_at']
