from django.contrib import admin
from .models import AppSetting, Classroom, Movement, Student

admin.site.register(Classroom)
admin.site.register(Student)
admin.site.register(Movement)
admin.site.register(AppSetting)
